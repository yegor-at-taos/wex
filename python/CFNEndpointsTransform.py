#!/usr/bin/env python3
import boto3
import re
import traceback

import utilities


def handler(event, context):
    try:
        return create_template(event, context)

    except Exception as e:

        return {
                'requestId': event['requestId'],
                'status': 'BIGBADABOOM',  # anything but SUCCESS is a failure
                'fragment': event['fragment'],
                'errorMessage': f'{e}: {traceback.format_exc()}',
                }


def count_exported_subnets(event, context):
    m = event['templateParameterValues']['Lob'] + \
            '-' + event['templateParameterValues']['Environment'] + \
            '-' + re.sub("(.).*?-", "\\1", event['region']) + \
            '-vpc-stk-PrivateSubnet(\\d)-Id'

    count = 0

    cfn = boto3.client('cloudformation')

    request_exports = {
            }

    while True:
        response_exports = cfn.list_exports(**request_exports)

        for export in response_exports['Exports']:
            s = re.match(m, export['Name'])
            if not s:
                continue
            subnet = int(s.group(1))
            if subnet > count:
                count = subnet

        if 'NextToken' not in response_exports:
            break
        else:
            request_exports['NextToken'] = response_exports['NextToken']

    return min(count, int(event['templateParameterValues']['MaxIpAddresses']))


def create_template(event, context):
    region = event['region']

    wex = event['fragment']['Mappings'].pop('Wex')

    az_count = count_exported_subnets(event, context)

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
                'VpcId': utilities.import_value(event,
                                                wex,
                                                'vpc_id'),
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
                'Tags': wex['Tags'],
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
                                               f'privatesubnet{i+1}_id')
                        }
                    for i
                    in range(az_count)
                    ],
                'SecurityGroupIds': [
                    utilities.get_attr(sg_in_id, 'GroupId'),
                    ],
                'Tags': wex['Tags'],
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
                'VpcId': utilities.import_value(event,
                                                wex,
                                                'vpc_id'),
                'Tags': wex['Tags'],
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
                                               f'privatesubnet{i+1}_id')
                        }
                    for i
                    in range(az_count)
                    ],
                'SecurityGroupIds': [
                    utilities.get_attr(sg_out_id, 'GroupId'),
                    ],
                'Tags': wex['Tags'],
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
