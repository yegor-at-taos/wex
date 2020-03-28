#!/usr/bin/python3
import boto3
import hashlib
import json
import logging
import urllib3

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


def handler(event, context):
    print(event)

    try:
        if event["RequestType"] == "Create":
            logger.debug('Processing Create')

            arn = f'arn:aws:iam::{event["ResourceProperties"]["Principal"]}' \
                f':role/{event["ResourceProperties"]["RoleARN"]}'
            logger.debug(f'Accepting invitation for: {arn}')

            sts_connection = boto3.client('sts')
            peer = sts_connection.assume_role(
                RoleArn=arn,
                RoleSessionName='cross_acct_lambda'
            )

            client = boto3.client(
                'ram',
                aws_access_key_id=peer['Credentials']['AccessKeyId'],
                aws_secret_access_key=peer['Credentials']['SecretAccessKey'],
                aws_session_token=peer['Credentials']['SessionToken']
            )

            invitationArn = event["ResourceProperties"]["ResourceShareArn"]
            logger.debug(f'Confirming invitation: {invitationArn}')

            response = client.accept_resource_share_invitation(
                    resourceShareInvitationArn=invitationArn
                    )
            logger.debug(f'Got response: {response}')

        elif event["RequestType"] == "Delete":
            logger.debug('Processing Delete')

    except Exception as e:
        # report 'SUCCESS' even if ack had been failed
        logger.error(f'An error occured: {e}')

    send_response("SUCCESS", event, context, dict())


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
