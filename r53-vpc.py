#!/usr/bin/env python3
import argparse
import copy
import csv
import datetime
import hashlib
import json
import re
import sys

def prepare_python(python_script):
        script = [
                datetime.datetime.now() \
                        .strftime("# Timestamp: %Y/%m/%d %H:%M:%S")
                ]

        with open(python_script) as self:
            for line in self:
                line = line.rstrip()
                if re.match('^if\\s', line):
                    break
                elif re.match('^\\s*#', line):
                    continue

                script.append(line)

        return script


if __name__ == '__main__':  # don't remove; processing stops at '^if\\s'
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--make", action='store_true',
                        help="Create r53-make.json from template",
                        default=False)
    parser.add_argument("-t", "--test", action='store_true',
                        help="Run tests; don't print",
                        default=False)
    parser.add_argument("-f", "--file", type=str,
                        help="Python file",
                        default=None)

    # If nothing is specified then sanitize Python and print
    # Use r53-vpc.bash to update it at AWS S3
    args = parser.parse_args()

    if args.test:
        with open(f'tests/00-config.json') as f:
            event = {
                    "accountId": "544308222195",
                    "fragment": json.load(f),
                    "transformId": "672442290193::wexRouteFiftyThreeMacro",
                    "requestId": "f09bfa28-84da-4f59-9b32-cffa92e37f3a",
                    "region": "us-west-2",
                    "params": {},
                    "templateParameterValues": {}
                    }
        response = handler(event, None)
        print(json.dumps(response))
    else:
        print('\n'.join(prepare_python(args.file)))
