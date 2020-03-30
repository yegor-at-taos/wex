import json
import hashlib
import logging
import urllib3

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


def send_response(status, event, context, data):
    headers = {
        "Content-Type": ""
    }

    physical_resource_id = mk_id(
            [
                'ResolveRuleShare',
                event["ResourceProperties"]["ResourceShareArn"],
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
