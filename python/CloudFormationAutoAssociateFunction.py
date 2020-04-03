#!/usr/bin/python3
import boto3
import logging
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
        logger.error(f'{e}: {traceback.format_exc()}')
        utilities.send_response('FAILURE', event, context, dict())

    logger.info('Done')


def generate_access_token(event, context):
    role_arn = {
            'RoleArn': f'arn:aws:iam::'
            f'{event["ResourceProperties"]["Principal"]}'
            f':role/{event["ResourceProperties"]["RoleARN"]}',
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

    access_token = generate_access_token(event, context)
    muninn = boto3.client('route53resolver', **access_token)

    request_exports = {
            }

    while True:
        response_exports = huginn.list_exports(**request_exports)

        for export in response_exports['Exports']:
            name, value = export['Name'], export['Value']

            if not name.endswith('-vpc-stk-Vpc-Id'):
                logger.info(f'Ignoring VPC (not match): {name}: {value}')
                continue

            if value in event['ResourceProperties']['VpcDni']:
                logger.info(f'Ignoring VPC (DNI): {name}: {value}')
                continue

            request = {
                    'ResolverRuleId': event['ResourceProperties']['RuleId'],
                    'VPCId': value,
                    }
            response = muninn.associate_resolver_rule(**request)
            logger.info(f'Attempted: {value}'
                        f' -> {event["ResourceProperties"]["RuleId"]}'
                        f'; got: {response}')

        if 'NextToken' not in response_exports:
            break
        else:
            request_exports['NextToken'] = response_exports['NextToken']
