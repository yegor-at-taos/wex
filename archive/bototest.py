#!/usr/bin/env python3
import boto3
import json
import logging

logging.basicConfig(
        level=logging.DEBUG,
        format=f'%(asctime)s %(levelname)s %(message)s'
        )
logger = logging.getLogger()

session = boto3.Session(
        profile_name='eu',
        region_name='us-east-1'
        )

client = boto3.client('sts')

role_arn = {
        'RoleArn': 'arn:aws:iam::265468622424:role/WexRamCloudFormationCrossAccountRole',
        'RoleSessionName': 'cross_account_lambda'
        }
peer = client.assume_role(**role_arn)['Credentials']

access_token = {
        'region_name': 'us-east-1',
        'aws_access_key_id': peer['AccessKeyId'],
        'aws_secret_access_key': peer['SecretAccessKey'],
        'aws_session_token': peer['SessionToken'],
        }

client = boto3.client('route53resolver', **access_token)
response = client.associate_resolver_rule(
        ResolverRuleId="rslvr-rr-8e47f676d04d4a3c8",
        VPCId="vpc-053f2acc73b064292"
        )

print(json.dumps(response))
