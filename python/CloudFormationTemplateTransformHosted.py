#!/usr/bin/env python3
import hashlib
import json
import logging

az_count = 2

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def mk_id(args):
    digest = hashlib.blake2b()
    for arg in args:
        digest.update(bytes(json.dumps(arg), 'utf-8'))
    return args[0] + digest.hexdigest()[-17:]


def import_value(event, wex_data, resource):
    region, account_id = event['region'], event['accountId']

    parent_stack_name = wex_data['Regions'][region]['parent-stack-name']

    for overrides in [
            overrides['Overrides']
            for overrides
            in [wex_data, wex_data['Regions'][event['region']]]
            if 'Overrides' in overrides
            ]:
        if account_id not in overrides:
            continue

        overrides = overrides[account_id]

        if 'parent-stack-name' in overrides:
            parent_stack_name = overrides['parent-stack-name']

        if 'Resources' in overrides:
            overrides = overrides['Resources']

        if resource in overrides:
            resource = overrides[resource]

    value = resource[1:] if resource.startswith('@') else {
            'Fn::ImportValue': f'{parent_stack_name}-{resource}'
            }

    return value


def get_attr(resource_name, attribute_name):
    return {
            'Fn::GetAtt': [
                resource_name,
                attribute_name,
                ]
            }


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

    # Create Hosted rules for this account/region combination
    if event['accountId'] in wex['Infoblox']['HostedHub']:
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
                        },
                    }

            shared_arns.append(get_attr(hz_rule_id, 'Arn'))

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
