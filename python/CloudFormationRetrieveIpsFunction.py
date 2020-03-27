#!/usr/bin/python3
import logging

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


def handler(event, context):
    print(event)
    event['fragment'] = [
            {
                'Ip': '10.10.10.111',
                'Port': '53',
                },
            {
                'Ip': '10.10.10.222',
                'Port': '53',
                },
            ]
    return {
            'requestId': event['requestId'],
            'status': 'SUCCESS',
            'fragment': event['fragment']
            }
