#!/usr/bin/env python3
import json
import sys

sys.path.insert(1, '.')

from python import CloudFormationTemplateTransformOnPrem

with open('mock/infra-mock.json') as f:
    event = {
            "accountId": "544308222195",
            "fragment": json.load(f),
            "transformId": "672442290193::wexRouteFiftyThreeMacro",
            "requestId": "f09bfa28-84da-4f59-9b32-cffa92e37f3a",
            "region": "us-west-2",
            "params": {},
            "templateParameterValues": {}
            }
response = CloudFormationTemplateTransformOnPrem.handler(event, None)

print(json.dumps(response))
