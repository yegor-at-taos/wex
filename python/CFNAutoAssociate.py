#!/usr/bin/python3
import boto3
import logging
import re
import traceback

import utilities

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


def handler(event, context):
    logger.debug(f'Running AutoAssociate: {event}')

    print(event)

    try:
        if event['RequestType'] in ['Create', 'Update']:
            logger.debug('Processing Create')
            sync_remote_associations(event, context)

        elif event['RequestType'] == 'Delete':
            logger.debug('Processing Delete; NOOP')

        else:
            logger.debug(f'Processing other: {event["RequestType"]}; NOOP')

        utilities.send_response('SUCCESS', event, context, dict())

    except Exception as e:
        logger.error(f'{e}: {event} {traceback.format_exc()}')
        utilities.send_response('FAILURE', event, context, dict())


def generate_access_token(event, context):
    role_arn = {
            'RoleArn': event['ResourceProperties']['RoleARN'],
            'RoleSessionName': 'cross_account_lambda'
            }

    peer = boto3.client('sts').assume_role(**role_arn)['Credentials']

    return {
            'aws_access_key_id': peer['AccessKeyId'],
            'aws_secret_access_key': peer['SecretAccessKey'],
            'aws_session_token': peer['SessionToken'],
            }


def sync_remote_associations(event, context):
    access_token = generate_access_token(event, context)

    local_exported_rules = set([
        re.sub('^.*\\/', '', resource['arn'])
        for resource
        in utilities.boto3_call('list_resources',
                                request={
                                    'resourceOwner': 'SELF'
                                    })
        if resource['resourceShareArn']
        == event['ResourceProperties']['ShareArn']
        and resource['type']
        == 'route53resolver:ResolverRule'
        ])

    remote_exported_vpcs = set([
        export['Value']
        for export
        in utilities.boto3_call('list_exports',
                                access_token=access_token)
        if utilities.is_exported_vpc(export)
        ])

    # `need`: associations we should have
    need = set()
    for vpc in remote_exported_vpcs - \
            set(event['ResourceProperties']['VpcDni']):
        for rule_id in local_exported_rules:
            need.add((vpc, rule_id))
    logger.debug(f'{need}')

    # `have`: associations we actually have
    have = set([
        (association['VPCId'], association['ResolverRuleId'])
        for association
        in utilities.boto3_call('list_resolver_rule_associations',
                                access_token=access_token)
        if association['ResolverRuleId'] in local_exported_rules
        and association['Status'] == 'COMPLETE'
        ])
    logger.debug(f'{have}')

    # create missing
    for pair in need - have:
        logger.debug(f'Creating: {pair}')
        utilities.boto3_call('associate_resolver_rule',
                             request={
                                 'VPCId': pair[0],
                                 'ResolverRuleId': pair[1],
                                 'Name': 'CFN-created; do not remove manually',
                                 },
                             access_token=access_token)

    # remove extra
    for pair in have - need:
        logger.debug(f'Removing: {pair}')
        utilities.boto3_call('disassociate_resolver_rule',
                             request={
                                 'VPCId': pair[0],
                                 'ResolverRuleId': pair[1],
                                 },
                             access_token=access_token)
