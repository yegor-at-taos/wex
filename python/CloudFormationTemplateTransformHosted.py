#!/usr/bin/env python3
import boto3
from copy import deepcopy
import json
import logging
import os
import re
import utilities


logger = logging.getLogger()
logger.setLevel(logging.INFO)


def retrieve_endpoint_ips():
    if 'AWS_UNITTEST_INBOUND_IPS' in os.environ:
        # We're running unit test, no AWS infrastructure is present
        return json.loads(os.environ['AWS_UNITTEST_INBOUND_IPS'])

    # Use export `Route53-Inbound-Endpoint-Id` and `Route53Resolver`
    # b/c retrieving endpoint IP addresses is not supported; this is
    # done during template processing. Keep `Fn::ImportValue` in the
    # processed template to let CloudFormation form the correct
    # implicit dependency.
    # When/if API is updated you can remove this function and just
    # import the IP addresses with Fn::ImportValue.
    cfm = boto3.client('cloudformation')

    resolver_id = None

    # TODO: handle multi page output correctly
    # TODO: add error handling
    for export in cfm.list_exports()['Exports']:
        if export['Name'] == 'Route53-Inbound-Endpoint-Id':
            resolver_id = export['Value']
            break

    if resolver_id is None:
        return None

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

    return value


def handler(event, context):
    region, shared = event['region'], list()

    wex = event['fragment']['Mappings'].pop('Wex')

    # allow append to existing 'Resources' section
    if 'Resources' not in event['fragment']:
        event['fragment']['Resources'] = dict()

    resources = event['fragment']['Resources']

    if region not in wex['Regions']:
        # return error if created in unsupported region
        logger.warn(f'Region {region} is not in the config.')
        return {
                'requestId': event['requestId'],
                'status': 'FAILURE',
                }

    for zone in wex['Infoblox']['HostedZones']:
        hz_rule_id = utilities.mk_id(
                [
                    'rrHostedZone',
                    zone,
                    region,
                    ]
                )

        zone_name = re.sub('_$', '', re.sub('\\.', '_', zone.strip()))

        resources[hz_rule_id] = {
                'Type': 'AWS::Route53Resolver::ResolverRule',
                'Properties': {
                    'Name': zone_name,
                    'RuleType': 'FORWARD',
                    'DomainName': zone,
                    'ResolverEndpointId': {
                        'Fn::ImportValue':
                        'Route53-Outbound-Endpoint-Id',
                        },
                    'TargetIps': retrieve_endpoint_ips(),
                    'Tags': deepcopy(wex['Tags']) + [
                        {
                            'Key': 'Name',
                            'Value': zone_name,
                            },
                        ],
                    },
                }

        hz_rule_assoc_id = utilities.mk_id(
                [
                    'raHostedZoneAssoc',
                    zone,
                    region,
                    ]
                )
        resources[hz_rule_assoc_id] = {
                'Type': 'AWS::Route53Resolver::ResolverRuleAssociation',  # noqa: E501
                'Properties': {
                    'ResolverRuleId': utilities.get_attr(hz_rule_id,
                                                         'ResolverRuleId'),
                    'VPCId': utilities.import_value(event, wex, 'Vpc-Id'),
                    }
                }

        shared.append(hz_rule_id)

    # Share created ResolverRule(s)
    principals = set(wex['Infoblox']['Accounts']) \
        - set([event['accountId']])

    if shared:  # don't create 'empty' shares if nothing to share
        for principal in list(principals):

            # Create one share with all rules per principal
            share_id = utilities.mk_id(
                    [
                        'rsHostedResourceShare',
                        region,
                        principal,
                        ]
                    )

            resources[share_id] = {
                    'Type': 'AWS::RAM::ResourceShare',
                    'Properties': {
                        'Name': f'Wex-AWS-Zones-Share-{principal}',
                        'ResourceArns': [
                                utilities.get_attr(shared_id, 'Arn')
                                for shared_id
                                in shared
                                ],
                        'Principals': [principal],
                        'Tags': deepcopy(wex['Tags']) + [
                            {
                                'Key': 'Name',
                                'Value': f'Wex-AWS-Zones-Share-{principal}',
                                },
                            ],
                        },
                    }

            # Create one auto-accept object per principal
            auto_accept_id = utilities.mk_id(
                    [
                        'crHostedAutoAccept',
                        region,
                        principal,
                        ]
                    )

            resources[auto_accept_id] = {
                    'Type': 'AWS::CloudFormation::CustomResource',
                    'Properties': {
                        'ServiceToken': {
                            'Fn::ImportValue':
                                'CloudFormationAutoAcceptFunction:Arn'
                            },
                        'ResourceShareArn':
                        utilities.get_attr(share_id, 'Arn'),
                        'Principal': principal,
                        'RoleARN':
                        'WexRamCloudFormationCrossAccount',
                        },
                    'DependsOn': [
                        share_id
                        ],
                    }

            # Create one auto-association object per rule
            # NOTE: rule_id s the same across the accounts. However,
            # AWS documentation does not formally guarantee this.
            for rule_id in shared:
                auto_associate_id = utilities.mk_id(
                        [
                            'crHostedAutoAssociate',
                            region,
                            principal,
                            rule_id,
                            ]
                        )

            resources[auto_associate_id] = {
                    'Type': 'AWS::CloudFormation::CustomResource',
                    'Properties': {
                        'ServiceToken': {
                            'Fn::ImportValue':
                                'CloudFormationAutoAssociateFunction:Arn'
                            },
                        'Principal': principal,
                        'RuleId': utilities.get_attr(rule_id,
                                                     'ResolverRuleId'),
                        'RoleARN':
                        'WexRamCloudFormationCrossAccountRole',
                        },
                    'DependsOn': [
                        auto_accept_id
                        ],
                    }

    return {
            'requestId': event['requestId'],
            'status': 'SUCCESS',
            'fragment': event['fragment']
            }
