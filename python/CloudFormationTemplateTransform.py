#!/usr/bin/env python3
import boto3
from copy import deepcopy
import json
import logging
import os
import re
import utilities


logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


def handler(event, context):
    try:
        return create_template(event, context)

    except Exception as e:
        return {
                'requestId': event['requestId'],
                'status': 'BIGBADABOOM',  # anything but SUCCESS is a failure
                'fragment': event['fragment'],
                'errorMessage': f'{e}',
                }


def retrieve_inbound_ips(data):
    if 'AWS_UNITTEST_INBOUND_IPS' in os.environ:
        # We're running unit test, no AWS infrastructure is present
        return json.loads(os.environ['AWS_UNITTEST_INBOUND_IPS'])

    # Use CloudFormation export and `Route53Resolver`
    # b/c retrieving endpoint IP addresses is not supported; this is
    # done during template processing. Keep `Fn::ImportValue` in the
    # processed template to let CloudFormation form the correct
    # implicit dependency.
    # When/if API is updated you can remove this function and just
    # import the IP addresses with Fn::ImportValue.
    cfm = boto3.client('cloudformation')
    request = {
            }
    resolver_id = None

    while True:
        response = cfm.list_exports(**request)

        for export in response['Exports']:
            if export['Name'] == data['endpoints-stack-name'] \
                    + '-' + utilities.endpoint_inbound_suffix:
                resolver_id = export['Value']
                break

        if resolver_id or 'NextToken' not in response:
            break
        else:
            request['NextToken'] = response['NextToken']

    if resolver_id is None:
        raise RuntimeError("Can't retrieve resolver_id")

    value = list()

    r53 = boto3.client('route53resolver')
    for ip in r53.list_resolver_endpoint_ip_addresses(
            ResolverEndpointId=resolver_id
            )['IpAddresses']:
        value.append(
                {
                    'Ip': ip['Ip'],
                    'Port': '53',
                    }
                )

    if not value:
        raise RuntimeError("Can't retrieve endpoint IP addresses")

    logger.debug(f'Retrieved endpoint IPs: {value}')

    return value


def create_template(event, context):
    '''
    Assuming the correct template; do not attempt to recover.
    '''
    region, shared = event['region'], list()

    wex = event['fragment']['Mappings'].pop('Wex')

    data = deepcopy(wex['Infoblox']['Regions']['default'])
    data.update(wex['Infoblox']['Regions'][region])

    kind = event['templateParameterValues']['Instantiate']

    if kind == 'Hosted':
        target_endpoint_ips = retrieve_inbound_ips(data)
    elif kind == 'OnPrem':
        target_endpoint_ips = [
                {
                    'Ip': target_ip,
                    'Port': 53,
                    }
                for target_ip
                in data['OnPremResolverIps'][region]
                ]
    else:
        raise RuntimeError(f'Transform type {kind} is invalid')

    resources = dict()
    event['fragment']['Resources'] = resources

    for zone in data[kind]:
        zone_name = re.sub('_$', '', re.sub('\\.', '_', zone.strip()))

        rule_id = utilities.mk_id(
                [
                    f'rr{kind}Zone',
                    zone,
                    region,
                    ]
                )

        shared.append(rule_id)  # always share generated rules

        resources[rule_id] = {
                'Type': 'AWS::Route53Resolver::ResolverRule',
                'Properties': {
                    'Name': zone_name,
                    'RuleType': 'FORWARD',
                    'DomainName': zone,
                    'ResolverEndpointId':
                        utilities.import_value(
                            event,
                            data,
                            'endpoint_outbound'
                            ),
                    'TargetIps': target_endpoint_ips,
                    'Tags': wex['Tags'] + [
                        {
                            'Key': 'Name',
                            'Value': zone_name,
                            },
                        ],
                    },
                }

        # This is a 'local' association. It applies to onprem zone to
        # coreservices VPC returned by the '...-vpc-stk' as '...-Vpc-Id'
        if kind == 'OnPrem':
            rule_assoc_id = utilities.mk_id(
                    [
                        f'ra{kind}ZoneAssoc',
                        zone,
                        region,
                        ]
                    )

            resources[rule_assoc_id] = {
                    'Type': 'AWS::Route53Resolver::ResolverRuleAssociation',
                    'Properties': {
                        'ResolverRuleId':
                            utilities.get_attr(rule_id, 'ResolverRuleId'),
                        'VPCId':
                            utilities.import_value(
                                event,
                                data,
                                'vpc_id'
                                ),
                        }
                    }

    # Share created ResolverRule(s) to all principals (except self)
    principals = set(data['Accounts']) - set([event['accountId']])

    if not shared:  # don't create 'empty' shares if nothing to share
        principals.clear()

    for principal in list(principals):
        # Create one share with all rules per principal
        share_id = utilities.mk_id(
                [
                    f'rs{kind}ResourceShare',
                    region,
                    principal,
                    ]
                )

        logger.debug(f'Sharing to principal {principal} id: {share_id}')

        resources[share_id] = {
                'Type': 'AWS::RAM::ResourceShare',
                'Properties': {
                    'Name': f'Wex-{kind}-Zones-Share-{principal}',
                    'ResourceArns': [
                            utilities.get_attr(shared_id, 'Arn')
                            for shared_id
                            in shared
                            ],
                    'Principals': [principal],
                    'Tags': wex['Tags'] + [
                        {
                            'Key': 'Name',
                            'Value': f'Wex-{kind}-Zones-Share-{principal}',
                            },
                        ],
                    },
                }

        print(f'{resources[share_id]}')
        return

        # Create one auto-accept object per principal
        auto_accept_id = utilities.mk_id(
                [
                    f'cr{kind}AutoAccept',
                    region,
                    principal,
                    ]
                )

        resources[auto_accept_id] = {
                'Type': 'AWS::CloudFormation::CustomResource',
                'Properties': {
                    'ServiceToken':
                        utilities.import_value(
                            event,
                            data,
                            'auto_accept_function'
                            ),
                    'RoleARN': utilities.cross_account_role,
                    'Principal': principal,
                    'ResourceShareArn':
                        utilities.get_attr(share_id, 'Arn'),
                    },
                }

        # Create one auto-association object per rule
        # NOTE: rule_id s the same across the accounts. However,
        # AWS documentation does not formally guarantee this.
        for rule_id in shared:
            auto_associate_id = utilities.mk_id(
                    [
                        f'cr{kind}AutoAssociate',
                        region,
                        principal,
                        rule_id,
                        ]
                    )

            logger.debug(f'Auto-association id for {principal}/{rule_id}:'
                         f'{auto_associate_id}')

            resources[auto_associate_id] = {
                    'Type': 'AWS::CloudFormation::CustomResource',
                    'Properties': {
                        'ServiceToken':
                            utilities.import_value(
                                event,
                                data,
                                'auto_associate_function'
                                ),
                        'RoleARN': utilities.cross_account_role,
                        'Principal': principal,
                        'RuleId': utilities.get_attr(rule_id,
                                                     'ResolverRuleId'),
                        },
                    'DependsOn': [
                        auto_accept_id  # fire after share is accepted
                        ],
                    }

    return {
            'requestId': event['requestId'],
            'status': 'SUCCESS',
            'fragment': event['fragment']
            }
