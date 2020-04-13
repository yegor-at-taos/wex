#!/usr/bin/python3
import boto3
import logging
import re
import traceback

import utilities

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    logger.info(f'Running AutoAssociate: {event}')

    try:
        if event['RequestType'] == 'Create':
            logger.info('Processing Create')

            associate_rule_to_the_vpc(event, context)

        elif event['RequestType'] == 'Delete':
            logger.info('Processing Delete; NOOP')

        else:
            logger.info(f'Processing other: {event["RequestType"]}; NOOP')

        utilities.send_response('SUCCESS', event, context, dict())

    except Exception as e:
        logger.error(f'{e}: {event} {traceback.format_exc()}')
        utilities.send_response('FAILURE', event, context, dict())


def generate_access_token(event, context):
    # This is a nasty hack: substitute principal ID with the target
    # principal ID. Note that we have to deploy satellite stack locally
    role_arn = {
            'RoleArn': re.sub('::\\d+:',
                              f'::{event["ResourceProperties"]["Principal"]}:',
                              event["ResourceProperties"]["RoleARN"]),
            'RoleSessionName': 'cross_account_lambda'
            }
    logger.info(f'Using remote role ARN: {role_arn}')

    client = boto3.client('sts')
    peer = client.assume_role(**role_arn)['Credentials']

    return {
            'aws_access_key_id': peer['AccessKeyId'],
            'aws_secret_access_key': peer['SecretAccessKey'],
            'aws_session_token': peer['SessionToken'],
            }


def associate_rule_to_the_vpc(event, context):
    access_token = generate_access_token(event, context)
    huginn = boto3.client('cloudformation', **access_token)
    muninn = boto3.client('route53resolver', **access_token)

    request_exports = {
            }

    while True:
        response_exports = huginn.list_exports(**request_exports)

        for export in response_exports['Exports']:
            name, value = export['Name'], export['Value']

            if not name.endswith('-vpc-stk-Vpc-Id'):
                continue

            if value in event['ResourceProperties']['VpcDni']:
                continue

            request = {
                    'ResolverRuleId': event['ResourceProperties']['RuleId'],
                    'VPCId': value,
                    }
            logger.info(f'Attempting association: {value}'
                        f' -> {event["ResourceProperties"]["RuleId"]}')
            response = muninn.associate_resolver_rule(**request)
            logger.info(f'; got: {response}')

        if 'NextToken' not in response_exports:
            break
        else:
            request_exports['NextToken'] = response_exports['NextToken']
