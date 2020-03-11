#!/usr/bin/env python3
import argparse
import ipaddress
import json
import os
import re
import logging

import WexAccount
import Unbound


class WexAnalyzer:
    def __init__(self, args, root, node):
        self.args = args
        self.root = root
        self.node = node

        self.logger = logging.getLogger('WexAnalyzer')
        self.logger.setLevel(args.logging)

        ch = logging.StreamHandler()
        ch.setLevel(args.logging)

        formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)

        self.logger.addHandler(ch)

    def match_tag(self, tags, name, match):
        for tag in tags:
            if 'Key' not in tag \
                    or 'Value' not in tag \
                    or tag['Key'] != name:
                continue

            if tag['Value'].lower().find(match):
                return True
            else:
                break

        return False

    def is_private_rt(self, data, region, rt_id):
        # `rt_data` is like data['route_tables']['us-east-1']
        for rt in data['route-tables'][region]:
            if rt['RouteTableId'] != rt_id:
                continue

            if not rt['Tags']:
                self.logger.warning(f'{rt_id} is untagged')

            if self.match_tag(rt['Tags'], 'Name', 'private'):
                return True

            # TODO: check routes and see if 0.0.0.0/0 has no GatewayId
            return False

        raise ValueError(f'Invalid RouteTableId: {rt_id}')

    def is_private_subnet(self, data, region, subnet_id):
        for sn in data['subnets'][region]:
            if sn['SubnetId'] != subnet_id:
                continue

            if not sn['Tags']:
                self.logger.warning(f'{subnet_id} is untagged')

            if self.match_tag(sn['Tags'], 'Name', 'private'):
                return True

            # TODO: check routing tables and see if they are private
            return False

        raise ValueError(f'Invalid RouteTableId: {sn}')

    def process_vpc(self, region_name, vpc_id):
        self.logger.info(f'Processing: {region_name} {vpc_id}')

        outbound_endpoints = list()

        # Check if Route 53 Resolver outbound endpoint is OK
        for endpoint in self.node.r53_resolver_outpoints(region_name, vpc_id):
            if self.node.is_resolver_endpoint_valid(region_name, endpoint):
                outbound_endpoints.append(endpoint)
            else:
                self.logger.info(f'{region_name}/{vpc_id}/{endpoint["Id"]}'
                                 f' exists but invalid')

        if len(outbound_endpoints) == 0:
            self.generate_vpc_outendpoint(region_name, vpc_id)
            return None
        elif len(outbound_endpoints) >= 1:
            return outbound_endpoints[0]

    def process_rules(self):
        pass

    def run(self):
        for region_name in [
                region['RegionName']
                for region in self.node.data['regions']
                ]:
            for vpc_id in [
                    vpc['VpcId']
                    for vpc in self.node.data['vpcs'][region_name]
                    ]:
                print(f'XXXXX {vpc_id}')
                print(f'\t{self.process_vpc(region_name, vpc_id)}')


parser = argparse.ArgumentParser()
parser.add_argument("-p", "--path", type=str,
                    help="Unbound configurations path", default="unbound")
parser.add_argument("-r", "--root", type=str,
                    help="'root' profile", default="wex-prod")
parser.add_argument("-n", "--node", type=str,
                    help="'node' profile", default="wex-dev")
parser.add_argument("-l", "--logging", type=str,
                    help="logging level", default="WARN")
parser.add_argument("-d", "--display", action='store_true',
                    help="display AWS CLI commands; don't run", default=True)
parser.add_argument("-u", "--unsafe", action='store_true',
                    help="always do safest guesses", default=False)
args = parser.parse_args()

unbound = Unbound.Unbound(args)
print(json.dumps(unbound.data))

exit(0)

root = WexAccount.WexAccount(args, args.root)
node = WexAccount.WexAccount(args, args.node)

WexAnalyzer(args, root, node).run()
