#!/usr/bin/env python3
from copy import deepcopy

import utilities


def handler(event, context):
    try:
        return create_template(event, context)

    except Exception as e:
        return {
                'requestId': event['requestId'],
                'status': 'BIGBADABOOM',  # anything but SUCCESS in a failure
                'fragment': event['fragment'],
                'errorMessage': f'{e}',
                }


def create_template(event, context):
    region = event['region']

    wex = event['fragment']['Mappings'].pop('Wex')

    resources = dict()
    event['fragment']['Resources'] = resources

    outputs = dict()
    event['fragment']['Outputs'] = outputs

    # In Security Group
    sg_in_id = utilities.mk_id(
            [
                'rrInSG',
                region,
                ]
            )
    resources[sg_in_id] = {
            'Type': 'AWS::EC2::SecurityGroup',
            'Properties': {
                'GroupDescription': 'Incoming DNS over IPv4 + ICMP',
                'VpcId': utilities.import_value(event, wex, 'Vpc-Id'),
                'SecurityGroupIngress': [
                    {
                        'CidrIp': '0.0.0.0/0',
                        'IpProtocol': 'udp',
                        'FromPort': 53,
                        'ToPort': 53,
                        },
                    {
                        'CidrIp': '0.0.0.0/0',
                        'IpProtocol': 'icmp',
                        'FromPort': -1,
                        'ToPort': -1,
                        },
                    ],
                'Tags': deepcopy(wex['Tags']),
                },
            }

    # In Resolver Endpoint
    ep_in_id = utilities.mk_id(
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
                        'SubnetId':
                        utilities.import_value(event,
                                               wex,
                                               f'PrivateSubnet{i+1}-Id')
                        }
                    for i
                    in range(utilities.az_count)
                    ],
                'SecurityGroupIds': [
                    utilities.get_attr(sg_in_id, 'GroupId'),
                    ],
                'Tags': deepcopy(wex['Tags']),
                },
            }

    outputs[ep_in_id] = {
            'Description': 'Route 53: Inbound Endpoint',
            'Value': {
                'Fn::GetAtt': [
                    ep_in_id,
                    'ResolverEndpointId'
                    ],
                },
            'Export': {
                'Name':
                utilities.prefix_stack_name(f'route53-inbound-endpoint-id')
                },
            }

    # Out Security Group
    sg_out_id = utilities.mk_id(
            [
                'rrOutSG',
                region,
                ]
            )
    resources[sg_out_id] = {
            'Type': 'AWS::EC2::SecurityGroup',
            'Properties': {
                'GroupDescription': 'Outgoing DNS over IPv4',
                'VpcId': utilities.import_value(event, wex, 'Vpc-Id'),
                'Tags': deepcopy(wex['Tags']),
                },
            }

    # Out Resolver Endpoint
    ep_out_id = utilities.mk_id(['rrOutEndpoint', region[0], wex])
    resources[ep_out_id] = {
            'Type': 'AWS::Route53Resolver::ResolverEndpoint',
            'Properties': {
                'Direction': 'OUTBOUND',
                'IpAddresses': [
                    {
                        'SubnetId':
                        utilities.import_value(event,
                                               wex,
                                               f'PrivateSubnet{i+1}-Id')
                        }
                    for i
                    in range(utilities.az_count)
                    ],
                'SecurityGroupIds': [
                    utilities.get_attr(sg_out_id, 'GroupId'),
                    ],
                'Tags': deepcopy(wex['Tags']),
                },
            }

    outputs[ep_out_id] = {
            'Description': 'Route 53: Outbound Endpoint',
            'Value': {
                'Fn::GetAtt': [
                    ep_out_id,
                    'ResolverEndpointId'
                    ],
                },
            'Export': {
                'Name':
                utilities.prefix_stack_name(f'route53-outbound-endpoint-id')
                },
            }

    return {
            'requestId': event['requestId'],
            'status': 'SUCCESS',
            'fragment': event['fragment']
            }
