#!/usr/bin/env python3
import ipaddress
import argparse
import boto3
import json
import os
import re
import sys
import tempfile
import logging

import WexAccount

class Unbound:
    def __init__(self):
        pass

    def parse_unbound_config(self, name):
        with open(name) as f:
            current = dict()
            for line in f:
                line = line.rstrip()
                if re.match('^forward-zone:$', line):
                    yield current
                    current.clear()
                elif re.match('^\s+name:\s', line):
                    line = re.sub('^\s+name:\s+', '', line).strip()
                    line = re.sub('^["\']*', '', line)  # trim lead quotation
                    line = re.sub('["\']*$', '', line)  # trim trail quotation
                    current['name'] = line.lower() + '.'
                elif re.match('^\s+forward-addr:\s', line):
                    if 'forward-addr' not in current:
                        current['forward-addr'] = dict()
                    addr = line.split(':')[1].strip()
                    current['forward-addr'][addr] = None
            yield current

    def load_all_unbound_configs(self, path):
        value = {}
        for name in os.listdir(path):
            for zone in self.parse_unbound_config(f'{path}/{name}'):
                if not zone:
                    continue
                if 'forward-addr' not in zone:
                    continue
                if 'name' not in zone:
                    continue
                if zone['name'] not in value:
                    value[zone['name']] = dict()
                value[zone['name']].update(zone['forward-addr'])
        del value['..']
        return value

    def locate_ip(self, data, addr):
        ip_addr = ipaddress.ip_address(addr)
        for region in data['subnets']:
            for subnet in data['subnets'][region]:
                ip_cidr = ipaddress.ip_network(subnet['CidrBlock'])
                if ip_addr in ip_cidr:
                    return None
                return subnet['VpcId']

class WexAnalyzer:
    def __init__(self, args, root, node):
        self.args = args
        self.root = root
        self.node = node

        self.logger = logging.getLogger('WexAnalyzer')
        self.logger.setLevel(args.logging)


        formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        ch = logging.StreamHandler()
        ch.setLevel(logging.WARNING)

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

        raise ValueError(f'Invalid RouteTableId: {rt_id}')

    def process_vpc(self, region_name, vpc_id):
        endpoints = list()

        # Check if Route 53 Resolver outbound endpoint is OK
        for endpoint in self.node.data['resolver-endpoints'][region_name]:
            if endpoint['HostVPCId'] != vpc_id or \
                    endpoint['Direction'] != 'OUTBOUND':
                self.logger.info(f'\tSkipping endpoint: {endpoint["Id"]}')
                continue

    def run(self):
        for region_name in [
                region['RegionName']
                for region
                in self.node.data['regions']
                ]:
            for vpc_id in [
                    vpc['VpcId']
                    for vpc
                    in self.node.data['vpcs'][region_name]
                    ]:
                self.process_vpc(region_name, vpc_id)
            

parser = argparse.ArgumentParser()
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

root = WexAccount.WexAccount(args, args.root)
node = WexAccount.WexAccount(args, args.node)

analyzer = WexAnalyzer(args, root, node)
analyzer.run()
