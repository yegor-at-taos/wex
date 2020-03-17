#!/usr/bin/env python3
import argparse
import copy
import datetime
import hashlib
import json
import re
import sys


def mk_id(args):
    digest = hashlib.blake2b()
    for arg in args:
        digest.update(bytes(arg, 'utf-8'))
    return digest.hexdigest()[-17:]


def handler(event, context):
    unbound = event['fragment']['Mappings'].pop('unbound')
    regions = event['fragment']['Mappings'].pop('regions')
    wex_tags = event['fragment']['Mappings'].pop('wex_tags')

    # if no more 'Mappings' left delete section (optional)
    if not event['fragment']['Mappings']:
        event['fragment'].pop('Mappings')

    # allow append to existing 'Resources' section
    if 'Resources' not in event['fragment']:
        event['fragment']['Resources'] = dict()
    resources = event['fragment']['Resources']

    r53endpoint_tmpl = {
            'Type': 'AWS::Route53Resolver::ResolverEndpoint',
            'Properties': {
                'Direction': None,
                'IpAddresses': [],
                'SecurityGroupIds': [],
                'Name': None,
                'Tags': wex_tags,
                },
            }

    r53rule_template = {
            'Type': 'AWS::Route53Resolver::ResolverRule',
            'Properties':
            {
                'DomainName': None,
                'ResolverEndpointId': None,
                'RuleType': 'FORWARD',
                'TargetIps': [
                    {
                        'Ip': address,
                        'Port': 53,
                        }
                    for address
                    in unbound['addresses']
                    ],
                'Tags': wex_tags,
                },
            }

    r53ruleassoc_template = {
            'Type': 'AWS::Route53Resolver::ResolverRuleAssociation',
            'Properties': {
                'ResolverRuleId': None,
                'VPCId': None,
                },
            'Tags': wex_tags,
            }

    for region in regions.items():
        if event['region'] != region[0]:
            continue

        for vpc in region[1].items():
            oep_id = 'rrOutPoint' + mk_id([region[0], vpc[0]])

            oep = copy.deepcopy(r53endpoint_tmpl)
            oep['Properties']['Name'] = f'{region[0]}/{vpc[0]}'
            oep['Properties']['IpAddresses'] = [
                    {
                        'SubnetId': subnet_id
                        }
                    for subnet_id
                    in vpc[1]['private-subnets']
                    ]
            oep['Properties']['SecurityGroupIds'] = vpc[1]['security-groups']
            oep['Properties']['Direction'] = 'OUTBOUND'
            resources[oep_id] = oep

            for zone in unbound['zones']:
                rule_id = 'rrRule' + mk_id([region[0], zone])

                rule = copy.deepcopy(r53rule_template)
                rule['Name'] = f'{region[0]}_{vpc[0]}_{zone}'
                rule['Properties']['Tags'].append(
                        {
                            'Key': 'Name',
                            'Value': rule['Name']
                            }
                        )
                rule['Properties']['DomainName'] = zone
                rule['Properties']['ResolverEndpointId'] = {
                        'Fn::GetAtt': [
                            oep_id, 'ResolverEndpointId'
                            ]
                        }
                resources[rule_id] = rule

                rassoc_id = 'rrRuleAssoc' + mk_id([region[0], vpc[0], zone])

                rassoc = copy.deepcopy(r53ruleassoc_template)
                rassoc['Properties']['ResolverRuleId'] = {
                        'Fn::GetAtt': [
                            rule_id, 'ResolverRuleId'
                            ]
                        }
                rassoc['Properties']['VPCId'] = vpc[0]

    return {
            'requestId': event['requestId'],
            'status': 'SUCCESS',
            'fragment': event['fragment']
            }


if __name__ == '__main__':  # don't remove; processing stops at '^if\\s'
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--test", action='store_true',
                        help="Run tests; don't print", default=False)
    args = parser.parse_args()

    if args.test:
        for test in ['00']:  # TODO go over 'tests' directory
            with open(f'tests/{test}-event.json') as t:
                event = json.load(t)
            response = handler(event, None)
            print(json.dumps(response))
    else:
        keep_imports = [
                'copy',
                'hashlib',
                're',
                ]

        script = []

        with open(sys.argv[0]) as self:
            for line in self:
                line = line.rstrip()
                if re.match('^import\\s', line):
                    temp = re.split('\\s', line)
                    if temp[1] not in keep_imports:
                        continue
                elif re.match('^if\\s', line):
                    break
                script.append(line)

        with open(re.sub('\\.py$', '.json', sys.argv[0])) as f:
            tmpl = json.load(f)

        function = tmpl['Resources']['VpcTransformFunction']
        function['Properties']['Code']['ZipFile'] = {
                'Fn::Join': [ '\n', script ]
                }
        function['Properties']['Tags'] = [
                {
                    'Key': 'Timestamp',
                    'Value': f'{datetime.datetime.now()}',
                    }
                ]

        print(json.dumps(tmpl, sort_keys=True,
            indent=2, separators=(',', ': ')))
