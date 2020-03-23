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
        digest.update(bytes(json.dumps(arg), 'utf-8'))
    return args[0] + digest.hexdigest()[-17:]

def import_value(event, wex_data, resource):
    region, account_id = event['region'], event['accountId']

    parent_stack_name = wex_data['Regions'][region]['parent-stack-name']

    for overrides in [
            overrides['Overrides']
            for overrides
            in [wex_data, wex_data['Regions'][event['region']]]
            if 'Overrides' in overrides
            ]:
        if account_id not in overrides:
            continue

        overrides = overrides[account_id]

        if 'parent-stack-name' in overrides:
            parent_stack_name = overrides['parent-stack-name']

        if 'Resources' in overrides:
            overrides = overrides['Resources']
            
        if resource in overrides:
            resource = overrides[resource]

    value = resource[1:] if resource.startswith('@') else {
            'Fn::ImportValue' : {
                'Fn::Sub': f'{parent_stack_name}-{resource}'
                }
            }

    return value

def get_attr(resource_name, attribute_name):
    return {
            'Fn::GetAtt': [
                resource_name,
                attribute_name,
                ]
            }

def handler(event, context):
    region, shared_arns = event['region'], list()

    wex = event['fragment']['Mappings'].pop('Wex')

    # allow append to existing 'Resources' section
    if 'Resources' not in event['fragment']:
        event['fragment']['Resources'] = dict()

    resources = event['fragment']['Resources']
    outputs = event['fragment']['Outputs']

    if region not in wex['Regions']:
        # return error if created in unsupported region
        return {
                'requestId': event['requestId'],
                'status': 'FAILURE',
                }

    # In Security Group
    sg_in_id = mk_id(['rrInSG', region, wex])
    resources[sg_in_id] = {
            'Type': 'AWS::EC2::SecurityGroup',
            'Properties': {
                'GroupDescription': 'Incoming DNS over IPv4',
                'VpcId': import_value(event, wex, 'Vpc-Id'),
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

    # Out Security Group
    sg_out_id = mk_id(['rrOutSG', region[0], wex])
    resources[sg_out_id] = {
            'Type': 'AWS::EC2::SecurityGroup',
            'Properties': {
                'GroupDescription': 'Outgoing DNS over IPv4',
                'VpcId': import_value(event, wex, 'Vpc-Id'),
                }
            }


    # In Resolver Endpoint
    ep_in_id = mk_id(['rrInEndpoint', region[0], wex])
    resources[ep_in_id] = {
            'Type': 'AWS::Route53Resolver::ResolverEndpoint',
            'Properties': {
                'Direction': 'INBOUND',
                'IpAddresses': [
                    {
                        'SubnetId': import_value(event, wex, f'PrivateSubnet{i+1}-Id')
                        }
                    for i
                    in range(az_count)
                    ],
                'SecurityGroupIds': [
                    get_attr(sg_in_id, 'GroupId'),
                    ],
                },
            }

    # Out Resolver Endpoint
    ep_out_id = mk_id(['rrOutEndpoint', region[0], wex])
    resources[ep_out_id] = {
            'Type': 'AWS::Route53Resolver::ResolverEndpoint',
            'Properties': {
                'Direction': 'OUTBOUND',
                'IpAddresses': [
                    {
                        'SubnetId': import_value(event, wex, f'PrivateSubnet{i+1}-Id')
                        }
                    for i
                    in range(az_count)
                    ],
                'SecurityGroupIds': [
                    get_attr(sg_out_id, 'GroupId'),
                    ],
                },
            }

    # Create OnPrem rules if this is OnPremHub
    if event['accountId'] in wex['Infoblox']['OnPremHub']:
        for zone in wex['Infoblox']['OnPremZones']:
            opz_rule_id = mk_id(['rrOnPremZone', zone, region[0], wex])
            resources[opz_rule_id] = {
                    'Type': 'AWS::Route53Resolver::ResolverRule',
                    'Properties': {
                        'RuleType': 'FORWARD',
                        'DomainName': zone,
                        'ResolverEndpointId': get_attr(ep_out_id, 'ResolverEndpointId'),
                        'TargetIps': [
                            {
                                'Ip': target_ip,
                                'Port': 53,
                                }
                            for target_ip
                            in wex['Infoblox']['OnPremResolverIps']
                            ],
                        },
                    }

            shared_arns.append(get_attr(opz_rule_id, 'Arn'))

            opz_rule_assoc_id = mk_id(['rrOnPremZoneAssoc', zone, region[0], wex])
            resources[opz_rule_assoc_id] = {
                    'Type': 'AWS::Route53Resolver::ResolverRuleAssociation',
                    'Properties': {
                        'ResolverRuleId': get_attr(opz_rule_id, 'ResolverRuleId'),
                        'VPCId': import_value(event, wex, 'Vpc-Id'),
                        }
                    }

    # Create Hosted rules for this account/region combination
    if event['accountId'] in wex['Infoblox']['Accounts']:
        account_data = wex['Infoblox']['Accounts'][event['accountId']]
        if 'HostedZones' in account_data:
            for zone in account_data['HostedZones'].items():
                hz_rule_id = mk_id(['rrHostedZone', zone, region[0], wex])
                resources[hz_rule_id] = {
                        'Type': 'AWS::Route53Resolver::ResolverRule',
                        'Properties': {
                            'RuleType': 'SYSTEM',
                            'DomainName': zone[1],
                            },
                        }

                shared_arns.append(get_attr(hz_rule_id, 'Arn'))

                hz_rule_assoc_id = mk_id(['rrHostedZoneAssoc', zone, region[0], wex])
                resources[hz_rule_assoc_id] = {
                        'Type': 'AWS::Route53Resolver::ResolverRuleAssociation',
                        'Properties': {
                            'ResolverRuleId': get_attr(hz_rule_id, 'ResolverRuleId'),
                            'VPCId': import_value(event, wex, 'Vpc-Id'),
                            }
                        }

    # Share created ResolverRule(s)
    principals = set(wex['Infoblox']['Accounts']) - set([event['accountId']])
    share_id = mk_id(['rrSharedRules', shared_arns, region[0], wex])
    resources[share_id] = {
            'Type': 'AWS::RAM::ResourceShare',
            'Properties': {
                'Name': 'Route53-Rules-Share',
                'ResourceArns': shared_arns,
                'Principals': list(principals)
                }
            }

    aa_id = mk_id(['aaCustom', region[0], wex])
    resources[aa_id] = {
            'Type': 'AWS::CloudFormation::CustomResource',
            'Properties': {
                'ServiceToken': {
                    'Fn::ImportValue': 'VpcAutoAcceptFunction-Arn'
                    },
                'ResourceShareArn': get_attr(share_id, 'Arn'),
                'Principals': list(principals),
                }
            }

    return {
            'requestId': event['requestId'],
            'status': 'SUCCESS',
            'fragment': event['fragment']
            }


if __name__ == '__main__':  # don't remove; processing stops at '^if\\s'
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--make", action='store_true',
                        help="Create r53-make.json from template",
                        default=False)
    parser.add_argument("-t", "--test", action='store_true',
                        help="Run tests; don't print",
                        default=False)
    parser.add_argument("-c", "--csv", type=str,
                        help="WEX Zones CSV", default="WEX AWS Private Zone's.csv")

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
                'json',
                'hashlib',
                're',
                ]

        script = [
                datetime.datetime.now() \
                        .strftime("# Timestamp: %Y/%m/%d %H:%M:%S")
                ]

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
