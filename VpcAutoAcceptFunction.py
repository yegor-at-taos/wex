#!/usr/bin/python3
import json
import logging
import urllib3

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


def handler(event, context):
    logger.info("Received event: " + json.dumps(event, indent=2))
    response_data = {}

    try:
        if event["RequestType"] == "Create":
            logger.debug('Processing Create')

        elif event["RequestType"] == "Delete":
            pass

        send_response("SUCCESS", event, context, response_data)

    except Exception as e:
        logger.error(f"An error occured: {e}")
        send_response("FAILURE", event, context, response_data)


def send_response(status, event, context, data):
    headers = {
        "Content-Type": ""
    }

    request_body = {
        "Status": status,
        "PhysicalResourceId": context.log_stream_name,
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": data
    }

    logger.debug(request_body)

    http = urllib3.PoolManager()

    response = http.request(
            'PUT',
            event["ResponseURL"],
            headers=headers,
            body=json.dumps(request_body),
            retries=False
            )

    logger.info(f"Response status code: {response.status}")
