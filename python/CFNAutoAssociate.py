#!/usr/bin/python3
import boto3
import logging
import re

import utilities

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


def handler(event, context):
    logger.debug(f'Running AutoAssociate: {event}')

    try:
        if event['RequestType'] in ['Create', 'Update']:
            logger.debug(f'Processing: {event["RequestType"]}')
            sync_remote_associations(event, context)

        else:
            logger.debug(f'Processing: {event["RequestType"]}; NOOP')

        utilities.send_response('SUCCESS', 'OK', event, context)

    except Exception as e:
        utilities.send_response('FAILED', f'{e}', event, context)


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
    logger.debug(f'local needs: {need}')

    # `have`: associations we actually have
    have = set([
        (association['VPCId'], association['ResolverRuleId'])
        for association
        in utilities.boto3_call('list_resolver_rule_associations',
                                access_token=access_token)
        if association['ResolverRuleId'] in local_exported_rules
        ])
    logger.debug(f'remote has: {have}')

    remote_rules = [
            remote_rule['Id']
            for remote_rule
            in utilities.boto3_call('list_resolver_rules',
                                    access_token=access_token)
            ]
    logger.debug(f'=== {remote_rules} ===')

    # create missing; format error nicely as this happens often
    remote_rules = list()
    for pair in need - have:
        logger.debug(f'>>> Creating: {pair} <<<')
        try:
            for _ in range(3):
                if pair[1] in remote_rules:
                    logger.debug('=== Found! ===')
                    break
                logger.debug(f'=== Not found: {pair[1]} (retrying) ===')
                remote_rules = [
                        remote_rule['Id']
                        for remote_rule
                        in utilities.boto3_call('list_resolver_rules',
                                                access_token=access_token)
                        ]

            # ready or not - attempt to associate; raises on error
            utilities.boto3_call('associate_resolver_rule',
                                 request={
                                     'VPCId': pair[0],
                                     'ResolverRuleId': pair[1],
                                     'Name': 'Do not remove manually',
                                     },
                                 access_token=access_token)
        except Exception as e:
            account = re.sub('^arn:aws:iam::(\\d+):.*', '\\1',
                             event['ResourceProperties']['RoleARN'])
            domain = [
                    rr['DomainName']
                    for rr
                    in utilities.boto3_call('list_resolver_rules')
                    if rr['Id'] == pair[1]
                    ]
            raise RuntimeError(f'{account}: failed to associate RR {pair[1]}'
                               f' {domain}'
                               f' to the VPC {pair[0]} : {e}') from e

    # remove extra
    for pair in have - need:
        logger.debug(f'Removing: {pair}')
        utilities.boto3_call('disassociate_resolver_rule',
                             request={
                                 'VPCId': pair[0],
                                 'ResolverRuleId': pair[1],
                                 },
                             access_token=access_token)
