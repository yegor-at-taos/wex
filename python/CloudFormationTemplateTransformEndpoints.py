#!/usr/bin/env python3
from copy import deepcopy
import hashlib
import json
import logging

def handler(event, context):
    region = event['region']

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
                'GroupDescription': 'Incoming DNS over IPv4 + ICMP',
                'VpcId': import_value(event, wex, 'Vpc-Id'),
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
                },
                'Tags': deepcopy(wex['Tags']),
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
                'Tags': deepcopy(wex['Tags']),
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
                'Name': f'Route53-Inbound-Endpoint-Id',
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
                'Tags': deepcopy(wex['Tags']),
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
                'Tags': deepcopy(wex['Tags']),
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
                'Name': f'Route53-Outbound-Endpoint-Id',
                }
            }

    return {
            'requestId': event['requestId'],
            'status': 'SUCCESS',
            'fragment': event['fragment']
            }
