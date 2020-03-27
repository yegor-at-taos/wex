#!/usr/bin/env python3
import boto3
from copy import deepcopy
import hashlib
import json
import logging


def retrieve_endpoint_ips():
    # use export `Route53-Inbound-Endpoint-Id` and `Route53Resolver`
    # b/c retrieving endpoint IP addresses is not supported; this is
    # done during template processing. Keep `Fn::ImportValue` in the
    # processed template to let CloudFormation form the correct
    # dependency.
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
    region, shared_arns = event['region'], list()

    wex = event['fragment']['Mappings'].pop('Wex')

    # allow append to existing 'Resources' section
    if 'Resources' not in event['fragment']:
        event['fragment']['Resources'] = dict()

    resources = event['fragment']['Resources']

    if region not in wex['Regions']:
        # return error if created in unsupported region
        return {
                'requestId': event['requestId'],
                'status': 'FAILURE',
                }

    for zone in wex['Infoblox']['HostedZones']:
        hz_rule_id = mk_id(
                [
                    'rrHostedZone',
                    zone,
                    region,
                    ]
                )
        resources[hz_rule_id] = {
                'Type': 'AWS::Route53Resolver::ResolverRule',
                'Properties': {
                    'RuleType': 'FORWARD',
                    'DomainName': zone,
                    'ResolverEndpointId': {
                        'Fn::ImportValue':
                        'Route53-Outbound-Endpoint-Id',
                        },
                    'TargetIps': retrieve_endpoint_ips(),
                    },
                    'Tags': deepcopy(wex['Tags']) + [
                        {
                            'Key': 'Name',
                            'Value': re.sub('\\.', '_', zone.strip())
                            }
                        ],
                }

        hz_rule_assoc_id = mk_id(
                [
                    'rrHostedZoneAssoc',
                    zone,
                    region,
                    ]
                )
        resources[hz_rule_assoc_id] = {
                'Type': 'AWS::Route53Resolver::ResolverRuleAssociation',  # noqa: E501
                'Properties': {
                    'ResolverRuleId': get_attr(hz_rule_id,
                                               'ResolverRuleId'),
                    'VPCId': import_value(event, wex, 'Vpc-Id'),
                    }
                }

        # Do not associate this rule; it's for export only
        del resources[hz_rule_assoc_id]

        shared_arns.append(get_attr(hz_rule_id, 'Arn'))

    # Share created ResolverRule(s)
    principals = set(wex['Infoblox']['Accounts']) \
        - set([event['accountId']])

    if len(shared_arns) > 0 and len(principals) > 0:
        for principal in list(principals):
            # one rule per principal
            share_id = mk_id(
                    [
                        'rrHostedShareRules',
                        principal,
                        region,
                        ]
                    )

            resources[share_id] = {
                    'Type': 'AWS::RAM::ResourceShare',
                    'Properties': {
                        'Name': f'Wex-AWS-Zones-Share-{principal}',
                        'ResourceArns': shared_arns,
                        'Principals': [principal],
                        'Tags': deepcopy(wex['Tags']) + [
                            {
                                'Key': 'Name',
                                'Value': f'Wex-AWS-Zones-Share-{principal}',
                                },
                            ],
                        },
                    }

            auto_accept_id = mk_id(
                    [
                        'rrHostedAutoAccept',
                        region,
                        share_id,
                        ]
                    )

            resources[auto_accept_id] = {
                    'Type': 'AWS::CloudFormation::CustomResource',
                    'Properties': {
                        'ServiceToken': {
                            'Fn::ImportValue':
                                'CloudFormationAutoAcceptFunction:Arn'
                            },
                        'ResourceShareArn': get_attr(share_id, 'Arn'),
                        'Principal': principal,
                        'RoleARN':
                            'WEXResourceAccessManager'
                            'AcceptResourceShareInvitation',
                        }
                    }

    return {
            'requestId': event['requestId'],
            'status': 'SUCCESS',
            'fragment': event['fragment']
            }
