#!/usr/bin/env python3
from copy import deepcopy
import json
import hashlib
import logging
import re
import urllib3

az_count = 2

exported = {
        'endpoint_inbound': (
            'cfn-endpoints',
            'route53-inbound-endpoint-id'),
        'endpoint_outbound': (
            'cfn-endpoints',
            'route53-outbound-endpoint-id'),
        'vpc_id': (
            'vpc',
            'Vpc-Id'),
        'privatesubnet1_id': (
            'vpc',
            'PrivateSubnet1-Id'),
        'privatesubnet2_id': (
            'vpc',
            'PrivateSubnet2-Id'),
        'auto_accept_function': (
            'cfn-lambda-utilities',
            'cloudformationautoacceptfunction-arn'),
        'auto_associate_function': (
            'cfn-lambda-utilities',
            'cloudformationautoassociatefunction-arn'),
}

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def mk_id(args):
    digest = hashlib.blake2b()
    for arg in args:
        digest.update(bytes(json.dumps(arg), 'utf-8'))
    return args[0] + digest.hexdigest()[-17:]


def import_value(event, wex, resource):
    '''
    Generates Fn::ImportValue to import resource from the stack
    or hardcode the value if template has @.. inline
    '''
    region = event['region']
    short_region = re.sub('(.).*?-', '\\1', region)

    account_id = event['accountId']
    account_name = 'account-name'

    data = deepcopy(wex['Infoblox']['Regions']['default'])
    data.update(wex['Infoblox']['Regions'][region])

    if account_id in data['Overrides'] \
            and account_name in data['Overrides'][account_id]:
        account_name = data['Overrides'][account_id][account_name]
    else:
        account_name = data[account_name]

    import_name = f'{account_name}-{short_region}' \
        f'-{exported[resource][0]}-stk-{exported[resource][1]}'

    return {
            'Fn::ImportValue': import_name
            }


def get_attr(resource_name, attribute_name):
    return {
        'Fn::GetAtt': [
            resource_name,
            attribute_name,
        ]
    }


def prefix_stack_name(value):
    return {
            'Fn::Join':
            [
                '-',
                [
                    {
                        'Ref': 'AWS::StackName'
                        },
                    value,
                    ]
                ]
            }


def send_response(status, event, context, data):
    headers = {
        "Content-Type": ""
    }

    physical_resource_id = mk_id(
            [
                'customResource',
                event["ServiceToken"],
                event["LogicalResourceId"],
                ]
            )

    request_body = {
        "Status": status,
        "PhysicalResourceId": physical_resource_id,
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": data
    }

    http = urllib3.PoolManager()

    try:
        response = http.request(
                'PUT',
                event["ResponseURL"],
                headers=headers,
                body=json.dumps(request_body),
                retries=False
                )
    except Exception as e:
        logger.error(f'An error occured: {e}')

    logger.debug(f"Response status code: {response.status}")
