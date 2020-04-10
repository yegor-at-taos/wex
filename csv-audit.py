#!/usr/bin/env python3
import argparse
import csv
import re
import sys
import json
import glob

import WexAccount
import Unbound


class WexAnalyzer:
    def __init__(self, args):
        self.args = args
        self.csv_writer = csv.writer(sys.stdout)

    def import_csv(self, csv_file_name):
        csv_data, csv_name = dict(), dict()

        with open(csv_file_name) as csvfile:
            for line in csv.reader(csvfile):
                m = re.match('^(\\d+)', line[0].strip())
                if not m:
                    continue  # skip title line

                acct = m.group(0)
                if len(acct) != 12:
                    acct = '0' * (12 - len(acct)) + acct

                csv_data[acct] = set()

                for zone in line[1].split(','):
                    zone = zone.strip()

                    m = re.search('(Z[A-Z0-9]+)', zone)
                    if not m:
                        continue  # ZoneId not found

                    zone_id = m.group(0)

                    csv_data[acct].add(zone_id)

                    # auto-detect format: 1) 'id (name)' 2) 'name (id)'
                    if re.search(f'\\(\\s*{zone_id}\\s*\\)', zone):
                        # format 2, ZoneId in brackets
                        zone_name = re.sub('\\s*\\(.*', '', zone)
                    else:
                        # format 1, ZoneName in brackets
                        zone_name = re.search('\\((.*?)\\)', zone).group(1)

                    zone_name = re.sub('\\.$', '', zone_name)

                    if zone_name:
                        csv_name[m.group(0)] = f'csv: {zone_name}'
                    else:
                        csv_name[m.group(0)] = f'csv: UNKNOWN'

                if not csv_data[acct]:
                    del csv_data[acct]
        return (csv_data, csv_name)

    def generate(self, csv_data, csv_name):
        unbound = Unbound.Unbound(self.args)

        with open('json/cloudformation-template.json') as f:
            tmpl = json.load(f)

        infoblox = tmpl['Mappings']['Wex']
        infoblox.update({
            'Accounts': set(),
            'AwsZones': set(),
            'OnPremZones': unbound.zones(),

            })

        for account in csv_data.items():
            infoblox['Accounts'].add(account[0])

            for zone_id in account[1]:
                # aggregate wexglobal.com
                hosted_zone = re.sub('\\.*$', '',
                                     csv_name[zone_id][5:].strip())
                hosted_zone = hosted_zone.split('.')

                if hosted_zone[-1].endswith('failed'):
                    continue

                if hosted_zone[-1] == 'com':
                    if hosted_zone[-2] in ['wexglobal']:
                        if hosted_zone[-3] in \
                                ['ue1', 'ec1', 'uw2', 'ae1', 'ae2', 'ew1']:
                            hosted_zone = hosted_zone[-3:]

                infoblox['AwsZones'].add('.'.join(hosted_zone) + '.')

        for key in ['Accounts', 'OnPremZones', 'AwsZones']:
            infoblox[key] = list(infoblox[key])

        # do the cleanup
        regions = tmpl['Mappings']['Wex']['Infoblox']['Regions']

        if self.args.generate == 'AwsZones':
            del infoblox['OnPremZones']
            for k in set(regions.keys()):
                if k not in [self.args.region, 'default']:
                    del regions[k]
                    continue

                if 'OnPremResolverIps' in regions[k]:
                    del regions[k]['OnPremResolverIps']

                if not regions[k]:
                    del regions[k]
        elif self.args.generate == 'OnPremZones':
            del infoblox['AwsZones']
            for k in set(regions.keys()):
                if k not in [self.args.region, 'default']:
                    del regions[k]
                    continue

                if not regions[k]:
                    del regions[k]
        else:
            raise NotImplementedError(f'Generate: {self.args.generate}')

        print(json.dumps(tmpl, indent=2))

    def run(self):
        csv_data, csv_name = dict(), dict()

        for csv_file in glob.glob(args.file):
            s_data, s_name = self.import_csv(csv_file)
            csv_data.update(s_data)
            csv_name.update(s_name)

        if self.args.generate:
            if self.args.generate not in ['AwsZones', 'OnPremZones']:
                raise ValueError(f'Can generate AwsZones|OnPremZones, got:'
                                 f'{self.args.generate}')
            self.generate(csv_data, csv_name)
        elif self.args.accounts:
            # used to generate access credentials
            accounts = set([
                    '253431644400',  # coreservices dev
                    '189106039250',  # coreservices prod
                    '198895985159',  # coreservices stage
                    ])
            accounts.update(csv_data.keys())
            print('\n'.join(sorted(list(accounts))))
        else:
            # generate audit report
            self.csv_writer.writerow([
                'Account ID',
                'Hosted Zone',
                'Diff: not in AWS',
                'Diff: not in CSV',
                ])

            for csv_account_id in csv_data.keys():
                if csv_account_id in [
                        '544308222195',
                        '344287180399',
                        ]:
                    continue
                aws_account = WexAccount.WexAccount(self.args,
                                                    'wex-' + csv_account_id)

                aws_pvt_zone = dict([
                    [re.sub('.*\\/', '', zone['Id']), zone['Name']]
                    for zone in aws_account.data['hosted-zones']
                    if zone['Config']['PrivateZone']
                    ])

                self.csv_writer.writerow([csv_account_id])

                all_set = csv_data[csv_account_id].union(aws_pvt_zone.keys())
                aws_set = all_set - aws_pvt_zone.keys()
                csv_set = all_set - csv_data[csv_account_id]

                all_list = sorted(list(all_set), reverse=True)
                aws_list = sorted(list(aws_set), reverse=True)
                csv_list = sorted(list(csv_set), reverse=True)

                while True:
                    row = [None]

                    if not all_list:
                        break

                    zone_id = all_list.pop()

                    if zone_id in aws_pvt_zone:
                        row.append(f'{zone_id} (aws: {aws_pvt_zone[zone_id]})')
                    else:
                        row.append(f'{zone_id} ({csv_name[zone_id]})')

                    row.append(aws_list.pop() if aws_list else None)
                    row.append(csv_list.pop() if csv_list else None)

                    self.csv_writer.writerow(row)


parser = argparse.ArgumentParser()
parser.add_argument("-f", "--file", type=str,
                    help="WEX exported CSV",
                    default="infra/WEX-AWS-?.csv")
parser.add_argument("-l", "--logging", type=str,
                    help="logging level", default="WARN")
parser.add_argument("-g", "--generate", type=str,
                    help="Generate OnPremZones|AwsZones config from CSV",
                    default=False)
parser.add_argument("-a", "--accounts", action='store_true',
                    help="Generate config from CSV",
                    default=False)
parser.add_argument("-u", "--unbound", type=str,
                    help="Unbound networks",
                    default="172.16.0.0/12,10.78.0.0/16")
parser.add_argument("-p", "--path", type=str,
                    help="Unbound configurations path",
                    default="infra/unbound")
parser.add_argument("-r", "--region", type=str,
                    help="AWS region name, eg. 'us-east-1'",
                    default="us-east-1")
args = parser.parse_args()

WexAnalyzer(args).run()
