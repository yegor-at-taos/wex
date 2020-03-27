#!/usr/bin/env python3
import hashlib
import json
import logging

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
                    'RuleType': 'SYSTEM',
                    'DomainName': zone,
                    'ResolverEndpointId': {
                            'Fn::ImportValue':
                                'Route53-Inbound-Endpoint-Id',
                        },
                    },
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
                        'Name': f'Route53-Hosted-Rules-Share-to-{principal}',
                        'ResourceArns': shared_arns,
                        'Principals': [principal]
                        }
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
