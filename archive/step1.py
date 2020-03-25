#!/usr/bin/env python3
import argparse
import re
import sys

import WexAccount


class WexAnalyzer:
    def __init__(self, args, root, node):
        self.args = args
        self.root = root
        self.node = node
        self.zones = [
                re.sub('.*/', '', zone['Id'])
                for zone in self.root.data['hosted-zones']
                if zone['Config']['PrivateZone']
                ]
        self.regions = [
                region['RegionName']
                for region in self.root.data['regions']
                ]

    def cleanup_authorizations(self):
        '''
        Go over the established associations and check if any
        authorizations are no longer needed.
        '''
        value = list()
        for zone in self.zones:
            links = self.root.data['hosted-zone-associations'][zone]
            auths = self.root.data['vpc-association-authorizations'][zone]
            for auth in auths:
                for link in links:
                    if auth['VPCId'] != link['VPCId']:
                        continue
                    if auth['VPCRegion'] != link['VPCRegion']:
                        '''
                        There's no guarantee for the VPCId to be unique
                        across regions. However, chances are very slim.
                        Treat it as an operator error and cleanup this auth.
                        '''
                        print(f'WARNING:\n'
                              f'\tWrong region in the auth {auth}\n'
                              f'\tShould be {link}?', file=sys.stderr)
                        if not self.args.unsafe:
                            print(f'\tSafe mode is enabled, not removing.',
                                  file=sys.stderr)
                            continue
                    value.append((zone, auth['VPCId'], auth['VPCRegion']))
        for link in value:
            if self.args.display:
                print(f'aws --profile {self.args.root}'
                      f' --region us-east-1'
                      f' route53 delete-vpc-association-authorization'
                      f' --hosted-zone-id={link[0]}'
                      f' --vpc=VPCRegion={link[2]},VPCId={link[1]}')
            else:
                raise Exception('Yet to be written')

    def create_authorizations_and_associations(self):
        value = list()

        for zone in self.zones:
            links = self.root.data['hosted-zone-associations'][zone]
            auths = self.root.data['vpc-association-authorizations'][zone]
            for region in self.regions:
                for vpc in [
                        vpc['VpcId']
                        for vpc in self.node.data['vpcs'][region]
                        ]:
                    create_link = True

                    # check if zone is already linked to VpcID:VpcRegion
                    for link in links:
                        if link['VPCId'] == vpc \
                                and link['VPCRegion'] == region:
                            create_link = False

                    # check if auth is already exists for VpcID:VpcRegion
                    for auth in auths:
                        if auth['VPCId'] == vpc \
                                and auth['VPCRegion'] == region:
                            create_link = False

                    if create_link:
                        value.append((zone, region, vpc))
                    else:
                        print(f'Not creating {zone}/{region}/{vpc}',
                              file=sys.stderr)

        for auth in value:
            if self.args.display:
                print(f'aws --profile {self.args.root}'
                      f' --region us-east-1'
                      f' route53 create-vpc-association-authorization'
                      f' --hosted-zone-id={auth[0]}'
                      f' --vpc=VPCRegion={auth[1]},VPCId={auth[2]}')
            else:
                raise Exception('Yet to be written')

        for auth in value:
            if self.args.display:
                print(f'aws --profile {self.args.node}'
                      f' --region us-east-1'
                      f' route53 associate-vpc-with-hosted-zone'
                      f' --hosted-zone-id={auth[0]}'
                      f' --vpc=VPCRegion={auth[1]},VPCId={auth[2]}')
            else:
                raise Exception('Yet to be written')


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
                    help="allow heuristic guesses", default=False)
args = parser.parse_args()

root = WexAccount.WexAccount(args, args.root)
node = WexAccount.WexAccount(args, args.node)

analyzer = WexAnalyzer(args, root, node)

print('#!/bin/bash -ex\n\n')

analyzer.cleanup_authorizations()
analyzer.create_authorizations_and_associations()
