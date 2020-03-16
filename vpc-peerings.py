#!/usr/bin/env python3
import argparse
import ipaddress
import logging
import json
import re
import sys

import WexAccount


class WexAnalyzer:
    def __init__(self, args, root):
        self.logger = logging.getLogger('WexAccount')
        self.logger.setLevel(args.logging)

        ch = logging.StreamHandler()
        ch.setLevel(args.logging)

        formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)

        self.args = args
        self.root = root
        self.unbounds = [
                ipaddress.ip_address(ip)
                for ip in self.args.unbound.split(',')
                ]

    def yield_objs(self, obj_name):
        for (region, objs) in self.root.data[obj_name].items():
            for obj in objs:
                obj['CidrBlock'] = ipaddress.ip_network(obj['CidrBlock'])
                obj['_Region'] = region
                obj_id = None
                if 'VpcId' in obj:
                    obj_id = obj['VpcId']
                elif 'SubnetId' in obj:
                    obj_id = obj['SubnetId']
                if obj_id is None:
                    raise ValueError(f'Unsupported {obj_name}')
                obj['_ObjId'] = obj_id
                yield obj

    def validate_objs(self, obj_name):
        vpcs = [vpc for vpc in self.yield_objs(obj_name)]
        errors = []

        for src in vpcs:
            error = [src, []]
            errors.append(error)
            for dst in vpcs:
                if src is dst:
                    continue
                if src["CidrBlock"] == dst["CidrBlock"]:
                    error[1].append(('Equals',dst))
                elif src["CidrBlock"].overlaps(dst["CidrBlock"]):
                    error[1].append(('Overlaps',dst))
        for error in errors:
            if len(error[1]) == 0:
                continue
            self.logger.warn(f'{error[0]["_Region"]}'
                             f'/{error[0]["_ObjId"]}'
                             f': {error[0]["CidrBlock"]}')
            for x in error[1]:
                self.logger.warn(f'\t{x[1]["_Region"]}'
                                 f'/{x[1]["_ObjId"]}'
                                 f': {x[1]["CidrBlock"]}')

    def lookup_vpc(self, ip):
        for vpc in self.yield_objs('vpcs'):
            ignore =  False
            for vpc_id in self.args.ignore.split(','):
                if vpc_id == vpc['VpcId']:
                    ignore = True
                    break
            if ignore or ip not in vpc["CidrBlock"]:
                continue
            return vpc['VpcId']
        raise ValueError(f'Can\'t locate VPC for {ip}')

    def peering_template(self, tgt):
        vpcids = set([
            vpc['VpcId']
            for vpc
            in self.yield_objs('vpcs')
            if vpc['VpcId'] != tgt
            ])
        vpcids -= set([vpc for vpc in self.args.ignore.split(',')])

        # don't create already existing VPC peering connections
        existing = set()
        for (region, objs) in self.root.data['vpc-peering-connections'].items():
            for obj in objs:
                requester_id = obj['RequesterVpcInfo']['VpcId']
                accepter_id = obj['AccepterVpcInfo']['VpcId']
                if tgt not in [requester_id, accepter_id]:
                    continue
                if tgt == requester_id:
                    existing.add(accepter_id)
                else:
                    existing.add(requester_id)

        vpcids -= existing

        return dict([
            [
                f'VPCPeeringConnection-{tgt}-{vpc["VpcId"]}',
                {
                    'Type': 'AWS::EC2::VPCPeeringConnection',
                    'Properties': {
                        'VpcId': tgt,
                        'PeerRegion': vpc["_Region"],
                        'PeerVpcId': vpc["VpcId"],
                        }
                    }
                ]
            for vpc
            in self.yield_objs('vpcs')
            if vpc['VpcId'] in vpcids
            ])

    def create_peerings(self):
        self.validate_objs('vpcs')

        tgts = set()
        for ip in [
                ipaddress.ip_address(ip)
                for ip in self.args.unbound.split(',')
                ]:
            tgts.add(self.lookup_vpc(self.unbounds[0]))

        self.logger.info(f'Target VPC(s): {tgts}')

        for tgt in tgts:
            print(json.dumps(self.peering_template(tgt)))


parser = argparse.ArgumentParser()
parser.add_argument("-u", "--unbound", type=str,
                    help="Unbound IP addresses",
                    default="10.98.1.166,10.94.5.87,10.97.1.99,10.94.1.77")
parser.add_argument("--ignore", type=str,
                    help="Ignore VPCs, comma-separated", default="vpc-89f1aaee")
parser.add_argument("-r", "--root", type=str,
                    help="'root' profile", default="wex-prod")
parser.add_argument("-l", "--logging", type=str,
                    help="logging level", default="WARN")
args = parser.parse_args()

root = WexAccount.WexAccount(args, args.root)

analyzer = WexAnalyzer(args, root)

analyzer.create_peerings()
