#!/usr/bin/env python3
from copy import deepcopy
import re

import utilities


def handler(event, context):
    region, shared = event['region'], list()

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
        opz_rule_id = utilities.mk_id(
                [
                    'rrOnPremZone',
                    zone,
                    region
                    ]
                )

        zone_name = re.sub('_$', '', re.sub('\\.', '_', zone.strip()))

        resources[opz_rule_id] = {
                'Type': 'AWS::Route53Resolver::ResolverRule',
                'Properties': {
                    'Name': zone_name,
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
                            'Value': zone_name,
                            }
                        ],
                    },
                }

        opz_rule_assoc_id = utilities.mk_id(
                [
                    'raOnPremZoneAssoc',
                    zone,
                    region,
                    ]
                )

        resources[opz_rule_assoc_id] = {
                'Type': 'AWS::Route53Resolver::ResolverRuleAssociation',
                'Properties': {
                    'ResolverRuleId': utilities.get_attr(opz_rule_id,
                                                         'ResolverRuleId'),
                    'VPCId': utilities.import_value(event, wex, 'Vpc-Id'),
                    }
                }

        shared.append(opz_rule_id)

    # Share created ResolverRule(s)
    principals = set(wex['Infoblox']['Accounts']) \
        - set([event['accountId']])

    if shared:
        for principal in list(principals):
            # one rule per principal
            share_id = utilities.mk_id(
                    [
                        'rsOnPermShareRules',
                        region,
                        principal,
                        ]
                    )

            resources[share_id] = {
                    'Type': 'AWS::RAM::ResourceShare',
                    'Properties': {
                        'Name': f'Wex-OnPrem-Zones-Share-{principal}',
                        'ResourceArns': [
                                utilities.get_attr(shared_id, 'Arn')
                                for shared_id
                                in shared
                            ],
                        'Principals': [principal],
                        'Tags': deepcopy(wex['Tags']) + [
                            {
                                'Key': 'Name',
                                'Value': f'Wex-OnPrem-Zones-Share-{principal}',
                                },
                            ],
                        },
                    }

            auto_accept_id = utilities.mk_id(
                    [
                        'crAutoAccept',
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
                        'ResourceShareArn': utilities.get_attr(share_id,
                                                               'Arn'),
                        'Principal': principal,
                        'RoleARN': 'WEXRamCloudFormationCrossAccountRole'
                        }
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
                        'RoleARN': utilities.cross_account_role,
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
