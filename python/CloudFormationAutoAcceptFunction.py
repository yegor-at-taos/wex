#!/usr/bin/python3
import boto3
import logging
import traceback

import utilities

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    try:
        if event['RequestType'] == 'Create':
            logger.info('Processing Create')

            accept_resource_share_invitation(event, context)

        elif event['RequestType'] == 'Delete':
            logger.info('Processing Delete; NOOP')

        else:
            logger.info(f'Processing other: {event["RequestType"]}; NOOP')

        utilities.send_response('SUCCESS', event, context, dict())

    except Exception as e:
        logger.error(f'{e}: {traceback.format_exc()}')
        utilities.send_response('FAILURE', event, context, dict())

    logger.info('Done')


def accept_resource_share_invitation(event, context):
    # Check if resource share is already accepted (via 'AutoAccept')
    # we can cheat here and use this account without assuming the role
    invitation = event['ResourceProperties']['ResourceShareArn']

    request = {
            'resourceShareArns': [
                invitation,
                ],
            'resourceOwner': 'SELF'
            }

    client = boto3.client('ram')
    response = client.get_resource_shares(**request)

    pending = None
    for resourceShare in response['resourceShares']:
        if 'status' in resourceShare:
            if resourceShare['status'] == 'ACTIVE':
                logger.info(f'Resource share is already ACTIVE')
                return

            elif resourceShare['status'] == 'PENDING':
                pending = True
                break

            else:
                raise ValueError(f'Wrong ResourceShare status')

    if not pending:
        raise ValueError(f'ResourceShare not found')

    role_arn = {
            'RoleArn': f'arn:aws:iam::'
            f'{event["ResourceProperties"]["Principal"]}'
            f':role/{event["ResourceProperties"]["RoleARN"]}',
            'RoleSessionName': 'cross_account_lambda'
            }
    logger.info(f'Using remote role ARN: {role_arn}')

    client = boto3.client('sts')
    peer = client.assume_role(**role_arn)['Credentials']

    access_token = {
            'aws_access_key_id': peer['AccessKeyId'],
            'aws_secret_access_key': peer['SecretAccessKey'],
            'aws_session_token': peer['SessionToken'],
            }
    request = {
            'resourceShareInvitationArn': invitation,
            }
    logger.info(f'Using: {access_token}, {request}')

    client = boto3.client('ram', **access_token)
    response = client.accept_resource_share_invitation(**request)
