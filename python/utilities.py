import json
import hashlib
import logging
import urllib3

az_count = 2

cross_account_role = 'WexRamCloudFormationCrossAccountRole'

inbound_endpoint_suffix = '-cfn-endpoints-stk-route53-inbound-endpoint-id'
outbound_endpoint_suffix = '-cfn-endpoints-stk-route53-outbound-endpoint-id'

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def mk_id(args):
    digest = hashlib.blake2b()
    for arg in args:
        digest.update(bytes(json.dumps(arg), 'utf-8'))
    return args[0] + digest.hexdigest()[-17:]


def import_value(event, data, stack, resource):
    '''
    Generates Fn::ImportValue to import resource from the stack
    or hardcode the value if template has @.. inline
    '''
    account_id = event['accountId']

    stack_name = data[f'{stack}-stack-name']

    if 'Overrides' in data and account_id in data['Overrides']:
        overrides = data['Overrides'][account_id]

        if f'{stack}-stack-name' in overrides:
            stack_name = overrides[f'{stack}-stack-name']

        if 'Resources' in overrides:
            overrides = overrides['Resources']

        if resource in overrides:
            resource = overrides[resource]

    if resource.startswith('@'):
        return resource[1:]  # hardcode the value

    return {
            'Fn::ImportValue': f'{stack_name}-{resource}'
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
