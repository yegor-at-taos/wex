#!/usr/bin/python3
import boto3
import logging

import utilities

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


def handler(event, context):
    try:
        if event['RequestType'] == 'Create':
            logger.debug('Processing Create')

            associate_rule_to_the_vpc(event, context)

        elif event['RequestType'] == 'Delete':
            logger.debug('Processing Delete; NOOP')

        else:
            logger.debug(f'Processing other: {event["RequestType"]}; NOOP')

        utilities.send_response('SUCCESS', event, context, dict())

    except Exception as e:
        logger.error(f'An error occured: {e}; sending FAILURE')
        utilities.send_response('FAILURE', event, context, dict())

    logger.debug('Done')


def generate_access_token(event, context):
    role_arn = {
            'RoleArn': f'arn:aws:iam::'
            f'{event["ResourceProperties"]["Principal"]}'
            f':role/{event["ResourceProperties"]["RoleARN"]}',
            'RoleSessionName': 'cross_account_lambda'
            }
    logger.debug(f'Using remote role ARN: {role_arn}')

    client = boto3.client('sts')
    peer = client.assume_role(**role_arn)['Credentials']

    return {
            'aws_access_key_id': peer['AccessKeyId'],
            'aws_secret_access_key': peer['SecretAccessKey'],
            'aws_session_token': peer['SessionToken'],
            }


def associate_rule_to_the_vpc(event, context):
    access_token = generate_access_token(event, context)

    client = boto3.client('cloudformation', **access_token)
    request = {
            }
    vpc_id = None

    while True:
        response = client.list_exports(**request)

        for export in response['Exports']:
            # TODO: Generate real export name, like:
            #   `coreservices-stage-ue1-vpc-stk-Vpc-Id`
            if export['Name'].endswith('-vpc-stk-Vpc-Id'):
                vpc_id = export['Value']
                break

        if vpc_id or 'NextToken' not in response:
            break
        else:
            request['NextToken'] = response['NextToken']

    if not vpc_id:
        raise RuntimeError(f'Remote export for Vpc-Id not found')

    access_token = generate_access_token(event, context)
    request = {
            'ResolverRuleId': event['ResourceProperties']['RuleId'],
            'VPCId': vpc_id,
            }

    client = boto3.client('route53resolver', **access_token)
    response = client.associate_resolver_rule(**request)
