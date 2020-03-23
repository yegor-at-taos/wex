#!/usr/bin/env python3
import VpcTransformFunction
import json

with open('tests/00-config.json') as f:
    fragment = json.load(f)

event = {
        "accountId": "544308222195",
        "fragment": fragment,
        "transformId": "672442290193::wexRouteFiftyThreeMacro",
        "requestId": "f09bfa28-84da-4f59-9b32-cffa92e37f3a",
        "region": "us-west-2",
        "params": {},
        "templateParameterValues": {}
        }
response = VpcTransformFunction.handler(event, None)

print(json.dumps(response))
