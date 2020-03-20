#!/usr/bin/env python3
import argparse
import csv
import re
import sys

import WexAccount


class WexAnalyzer:
    def __init__(self, args):
        self.args = args
        self.csv_writer = csv.writer(sys.stdout)

    def import_csv(self):
        csv_data = dict()
        csv_name = dict()
        with open(args.file) as csvfile:
            for line in csv.reader(csvfile):
                m = re.match('^(\\d+)', line[0])
                if not m:
                    continue  # skip title line
                acct = m.group(0)
                csv_data[acct] = set()
                for zone in line[1].split(','):
                    zone = zone.strip()
                    m = re.match('(Z[A-Z0-9]+)', zone)
                    if not m:
                        continue

                    csv_data[acct].add(m.group(0))

                    # see if there's zone name in brackets: (...)
                    n = re.search('\\((.*?)\\)', zone)
                    if n:
                        csv_name[m.group(0)] = f'csv: {n.group(0)}'
                    else:
                        csv_name[m.group(0)] = f'csv: UNKNOWN'

                if not csv_data[acct]:
                    del csv_data[acct]
        return (csv_data, csv_name)

    def run(self):
        self.csv_writer.writerow([
            'Account ID',
            'Hosted Zone',
            'Diff: not in AWS',
            'Diff: not in CSV',
            ])

        csv_data, csv_name = self.import_csv()

        for csv_account_id in csv_data.keys():
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
                    default="WEX AWS Private Zone's.csv")
parser.add_argument("-l", "--logging", type=str,
                    help="logging level", default="WARN")
args = parser.parse_args()

analyzer = WexAnalyzer(args)

analyzer.run()
