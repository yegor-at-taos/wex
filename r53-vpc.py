#!/usr/bin/env python3
import argparse
import copy
import csv
import datetime
import hashlib
import json
import re
import sys


az_count = 2

def mk_id(args):
    digest = hashlib.blake2b()
    for arg in args:
        digest.update(bytes(arg, 'utf-8'))
    return args[0] + digest.hexdigest()[-17:]

def import_value(wex_stack, resource):
    return {
            'Fn::ImportValue' : {
                'Fn::Sub': f'{wex_stack}-{resource}'
                }
            }

def handler(event, context):
    wex = event['fragment']['Mappings'].pop('Wex')

    # if no more 'Mappings' left delete section (this is optional)
    if not event['fragment']['Mappings']:
        event['fragment'].pop('Mappings')

    # allow append to existing 'Resources' section
    if 'Resources' not in event['fragment']:
        event['fragment']['Resources'] = dict()

    resources = event['fragment']['Resources']

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
                    in wex['Infoblox']['Addresses']
                    ],
                'Tags': wex['Tags'],
                },
            }

    r53ruleassoc_template = {
            'Type': 'AWS::Route53Resolver::ResolverRuleAssociation',
            'Properties': {
                'ResolverRuleId': None,
                'VpcId': None,
                'Tags': wex['Tags'],
                },
            }

    for region in wex['Regions'].items():
        if event['region'] != region[0]:
            continue

        wex_stack = region[1]['stack-name']

        sg_in_id = mk_id(['rrInSG', region[0], wex_stack])
        resources[sg_in_id] = {
                'Type': 'AWS::EC2::SecurityGroup',
                'Properties': {
                    'GroupDescription': 'Incoming DNS over IPv4',
                    'VpcId': import_value(wex_stack, 'Vpc-Id'),
                    'SecurityGroupIngress': [
                        {
                            'CidrIp': '0.0.0.0/0',
                            'IpProtocol': 'udp',
                            'FromPort': 53,
                            'ToPort': 53,
                            }
                        ],
                    }
                }

        sg_out_id = mk_id(['rrOutSG', region[0], wex_stack])
        resources[sg_out_id] = {
                'Type': 'AWS::EC2::SecurityGroup',
                'Properties': {
                    'GroupDescription': 'Outgoing DNS over IPv4',
                    'VpcId': import_value(wex_stack, 'Vpc-Id'),
                    }
                }

        resources[mk_id(['rrInEndpoint', region[0], wex_stack])] = {
                'Type': 'AWS::Route53Resolver::ResolverEndpoint',
                'Properties': {
                    'Direction': 'INBOUND',
                    'IpAddresses': [
                        {
                            'SubnetId': import_value(wex_stack, f'PublicSubnet{i+1}-Id')
                            }
                        for i
                        in range(az_count)
                        ],
                    'SecurityGroupIds': [
                        {
                            'Fn::GetAtt': [
                                sg_in_id,
                                'GroupId'
                                ]
                            }
                        ],
                    },
                }

        resources[mk_id(['rrOutEndpoint', region[0], wex_stack])] = {
                'Type': 'AWS::Route53Resolver::ResolverEndpoint',
                'Properties': {
                    'Direction': 'OUTBOUND',
                    'IpAddresses': [
                        {
                            'SubnetId': import_value(wex_stack, f'PrivateSubnet{i+1}-Id')
                            }
                        for i
                        in range(az_count)
                        ],
                    'SecurityGroupIds': [
                        {
                            'Fn::GetAtt': [
                                sg_out_id,
                                'GroupId'
                                ]
                            }
                        ],
                    },
                }

    return {
            'requestId': event['requestId'],
            'status': 'SUCCESS',
            'fragment': event['fragment']
            }


if __name__ == '__main__':  # don't remove; processing stops at '^if\\s'
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--make", action='store_true',
                        help="Create r53-make.json from tmpl", default=False)
    parser.add_argument("-t", "--test", action='store_true',
                        help="Run tests; don't print", default=False)
    parser.add_argument("-c", "--csv", type=str,
                        help="WEX Zones CSV", default="WEX AWS Private Zone's.csv")
    # If nothing specified then sanitize Python and print
    # Use r53-vpc.bash to update it at AWS S3
    args = parser.parse_args()

    if args.test:
        for test in ['00']:  # TODO implement proper tests
            with open(f'tests/{test}-event.json') as t:
                event = json.load(t)
            response = handler(event, None)
            print(json.dumps(response))
    elif args.make:
        data = dict()
        with open(args.csv) as csvfile:
            for line in csv.reader(csvfile):
                m = re.match('^(\\d+)', line[0])
                if not m:
                    continue  # skip title line
                acct = int(m.group(0))
                data[acct] = list()
                for zone in line[1].split(','):
                    m = re.match('(Z[A-Z0-9]+)', zone)
                    if not m:
                        continue
                    data[acct].append(m.group(0))
                if not data[acct]:
                    del data[acct]
                else:
                    print(acct)
        print(json.dumps(data))

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
                elif re.match('^\\s*#', line):
                    continue

                m = re.match('(\\s+)', line)
                if m:
                    index = len(m.group(0))
                    assert(index % 4 == 0)
                    line = ' ' * (index >> 2) + line[index:]
                script.append(line)

        print('\n'.join(script))

        exit(0)

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

        print(json.dumps(tmpl, separators=(',', ':')))
