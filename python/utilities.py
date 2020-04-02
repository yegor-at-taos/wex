import json
import hashlib
import logging
import urllib3

az_count = 2

cross_account_role = 'WexRamCloudFormationCrossAccountRole'
outbount_endpoint_id_export = 'Route53-Outbound-Endpoint-Id'
inbount_endpoint_id_export = 'Route53-Inbound-Endpoint-Id'

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def mk_id(args):
    digest = hashlib.blake2b()
    for arg in args:
        digest.update(bytes(json.dumps(arg), 'utf-8'))
    return args[0] + digest.hexdigest()[-17:]


def import_value(event, wex, resource):
    account_id = event['accountId']

    # NOTE: This is where to replace merge with deepmerge if needed
    data = wex['Infoblox']['Regions']['default']
    data.update(wex['Infoblox']['Regions'][event['region']])

    parent_stack_name = data['parent-stack-name']

    if 'Overrides' in data and account_id in data['Overrides']:
        overrides = data['Overrides'][account_id]

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
