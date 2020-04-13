#!/usr/bin/env python3
import json
import hashlib
import logging
import re
import urllib3

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
        'privatesubnet3_id': (
            'vpc',
            'PrivateSubnet3-Id'),
        'auto_associate_function': (
            'cfn-lambda-utilities',
            'cfnautoassociate-arn'),
        'satellite-role': (
            'cfn-satellite-permissions',
            'role-arn'),
}

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def mk_id(args):
    digest = hashlib.blake2b()
    for arg in args:
        digest.update(bytes(json.dumps(arg), 'utf-8'))
    return args[0] + digest.hexdigest()[-17:]


def import_value(event, wex, resource, region=None):
    if region is None:
        region = re.sub('(.).*?-', '\\1', event['region'])
    else:
        region = 'global'

    import_name = event['templateParameterValues']['Lob'] + \
        '-' + event['templateParameterValues']['Environment'] + \
        '-' + region + \
        '-' + '-stk-'.join(exported[resource])

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
