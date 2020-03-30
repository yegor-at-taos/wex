#!/usr/bin/python3
import boto3
import logging

import utilities

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


def handler(event, context):
    print(event)

    try:
        if event["RequestType"] == "Create":
            logger.debug('Processing Delete')
            role_arn = {
                    'RoleArn': f'arn:aws:iam::'
                    f'{event["ResourceProperties"]["Principal"]}'
                    f':role/{event["ResourceProperties"]["RoleARN"]}',
                    'RoleSessionName': 'cross_account_lambda'
                    }

            logger.debug(f'Remote role ARN: {role_arn}')

            client = boto3.client('sts')
            peer = client.assume_role(**role_arn)['Credentials']

            access_token = {
                    'aws_access_key_id': peer['AccessKeyId'],
                    'aws_secret_access_key': peer['SecretAccessKey'],
                    'aws_session_token': peer['SessionToken'],
                    }

            invitation = event["ResourceProperties"]["ResourceShareArn"]

            accept_resource_share_invitation(access_token, invitation)

        elif event["RequestType"] == "Delete":
            logger.debug('Processing Delete')
        else:
            logger.debug(f'Processing other: {event["RequestType"]}')

    except Exception as e:
        # report 'SUCCESS' even if ack had been failed
        logger.error(f'An error occured: {e}')

    utilities.send_response("SUCCESS", event, context, dict())


def accept_resource_share_invitation(access_token, invitation):
    try:
        # check if resource share is already accepted (eg. 'AutoAccept' in on)
        # we can cheat here and use this account without assuming the role
        client = boto3.client('ram')

        request = {
                'resourceShareArns': [
                    invitation,
                    ],
                'resourceOwner': 'SELF'
                }
        response = client.get_resource_shares(**request)

        pending = None
        for resourceShare in response['resourceShares']:
            if 'status' in resourceShare:
                if resourceShare['status'] == 'ACTIVE':
                    logger.info(f'Resource share is already ACTIVE')
                    return

                if resourceShare['status'] == 'PENDING':
                    pending = True
                    break

                raise ValueError(f'Wrong ResourceShare status')

        if not pending:
            raise ValueError(f'ResourceShare not found')

        client = boto3.client('ram', **access_token)

        request = {
                'resourceShareInvitationArn': invitation,
                }

        # never mind the returned status as it is not a requirement
        client.accept_resource_share_invitation(**request)
    except Exception as e:
        logger.error(f'Error occured while checking if share is accepted: {e}')
        raise
