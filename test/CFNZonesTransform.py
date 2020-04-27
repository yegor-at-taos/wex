#!/usr/bin/env python3
import json
import sys

sys.path.insert(1, '.')
sys.path.insert(1, './python')

from python import CFNZonesTransform

with open('test/CFNZonesTransform_awszones_test.json') as f:
    data = json.load(f)

data['templateParameterValues']['LocalTest'] = True

response = CFNZonesTransform.create_template(data, None)

print(json.dumps(response))
