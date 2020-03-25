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
            'Fn::ImportValue': {
                'Fn::Sub': f'{parent_stack_name}-{resource}'
                }
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
    region = event['region']

    print(event)
    print(context)

    wex = event['fragment']['Mappings'].pop('Wex')

    # allow append to existing 'Resources' section
    if 'Resources' not in event['fragment']:
        event['fragment']['Resources'] = dict()

    resources = event['fragment']['Resources']
    outputs = event['fragment']['Outputs']

    if region not in wex['Regions']:
        # return error if created in unsupported region
        return {
                'requestId': event['requestId'],
                'status': 'FAILURE',
                }

    # In Security Group
    sg_in_id = mk_id(
            [
                'rrInSG',
                region,
                ]
            )
    resources[sg_in_id] = {
            'Type': 'AWS::EC2::SecurityGroup',
            'Properties': {
                'GroupDescription': 'Incoming DNS over IPv4',
                'VpcId': import_value(event, wex, 'Vpc-Id'),
                'SecurityGroupIngress': [
                    {
                        'CidrIp': '0.0.0.0/0',
                        'IpProtocol': 'udp',
                        'FromPort': 53,
                        'ToPort': 53,
                        }
                    ],
                }
            }

    # In Resolver Endpoint
    ep_in_id = mk_id(
            [
                'rrInEndpoint',
                region
                ]
            )
    resources[ep_in_id] = {
            'Type': 'AWS::Route53Resolver::ResolverEndpoint',
            'Properties': {
                'Direction': 'INBOUND',
                'IpAddresses': [
                    {
                        'SubnetId': import_value(event, wex,
                                                 f'PrivateSubnet{i+1}-Id')
                        }
                    for i
                    in range(az_count)
                    ],
                'SecurityGroupIds': [
                    get_attr(sg_in_id, 'GroupId'),
                    ],
                },
            }

    outputs[ep_in_id] = {
            'Description': 'Route 53: Inbound Endpoint',
            'Value': {
                'Fn::GetAtt': [
                    ep_in_id,
                    'Arn'
                    ],
                },
            'Export': {
                'Name': f'Route53-Inbound-Endpoint-Arn',
                }
            }

    # Out Security Group
    sg_out_id = mk_id(
            [
                'rrOutSG',
                region,
                ]
            )
    resources[sg_out_id] = {
            'Type': 'AWS::EC2::SecurityGroup',
            'Properties': {
                'GroupDescription': 'Outgoing DNS over IPv4',
                'VpcId': import_value(event, wex, 'Vpc-Id'),
                }
            }

    # Out Resolver Endpoint
    ep_out_id = mk_id(['rrOutEndpoint', region[0], wex])
    resources[ep_out_id] = {
            'Type': 'AWS::Route53Resolver::ResolverEndpoint',
            'Properties': {
                'Direction': 'OUTBOUND',
                'IpAddresses': [
                    {
                        'SubnetId': import_value(event, wex,
                                                 f'PrivateSubnet{i+1}-Id')
                        }
                    for i
                    in range(az_count)
                    ],
                'SecurityGroupIds': [
                    get_attr(sg_out_id, 'GroupId'),
                    ],
                },
            }

    outputs[ep_out_id] = {
            'Description': 'Route 53: Outbound Endpoint',
            'Value': {
                'Fn::GetAtt': [
                    ep_out_id,
                    'Arn'
                    ],
                },
            'Export': {
                'Name': f'Route53-Outbound-Endpoint-Arn',
                }
            }

    return {
            'requestId': event['requestId'],
            'status': 'SUCCESS',
            'fragment': event['fragment']
            }
