#!/usr/bin/env python3
from copy import deepcopy
import hashlib
import json
import logging
import re

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

    # Create OnPrem rules if this is OnPremHub
    for zone in wex['Infoblox']['OnPremZones']:
        opz_rule_id = mk_id(
                [
                    'rrOnPremZone',
                    zone,
                    region
                    ]
                )

        resources[opz_rule_id] = {
                'Type': 'AWS::Route53Resolver::ResolverRule',
                'Properties': {
                    'Name': re.sub('\\.', '_', zone.strip()),
                    'RuleType': 'FORWARD',
                    'DomainName': zone,
                    'ResolverEndpointId': {
                            'Fn::ImportValue':
                                'Route53-Outbound-Endpoint-Id',
                        },
                    'TargetIps': [
                        {
                            'Ip': target_ip,
                            'Port': 53,
                            }
                        for target_ip
                        in wex['Infoblox']['OnPremResolverIps'][region]
                        ],
                    'Tags': deepcopy(wex['Tags']) + [
                        {
                            'Key': 'Name',
                            'Value': re.sub('\\.', '_', zone.strip())
                            }
                        ],
                    },
                }

        opz_rule_assoc_id = mk_id(
                [
                    'rrOnPremZoneAssoc',
                    zone,
                    region,
                    ]
                )

        resources[opz_rule_assoc_id] = {
                'Type': 'AWS::Route53Resolver::ResolverRuleAssociation',
                'Properties': {
                    'ResolverRuleId': get_attr(opz_rule_id,
                                               'ResolverRuleId'),
                    'VPCId': import_value(event, wex, 'Vpc-Id'),
                    }
                }

        shared_arns.append(get_attr(opz_rule_id, 'Arn'))

    # Share created ResolverRule(s)
    principals = set(wex['Infoblox']['Accounts']) \
        - set([event['accountId']])

    if len(shared_arns) > 0 and len(principals) > 0:
        for principal in list(principals):
            # one rule per principal
            share_id = mk_id(
                    [
                        'rrOnPermShareRules',
                        principal,
                        region,
                        ]
                    )

            resources[share_id] = {
                    'Type': 'AWS::RAM::ResourceShare',
                    'Properties': {
                        'Name': f'Route53-OnPrem-Rules-Share-to-{principal}',
                        'ResourceArns': shared_arns,
                        'Principals': [principal],
                        'Tags': deepcopy(wex['Tags']) + [
                            {
                                'Key': 'Name',
                                'Value': f'Wex-OnPrem-Zones-Share-{principal}',
                                },
                            ],
                        }
                    }

            auto_accept_id = mk_id(
                    [
                        'rrAutoAccept',
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
