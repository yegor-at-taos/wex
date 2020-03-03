#!/usr/bin/env python3
import boto3
import json
import os
import re
import sys
import tempfile

system_cleanup = set([
        'ResponseMetadata',
        'MaxResults',
        'IsTruncated',
        'MaxItems',
        'Marker',
        'NextMarker',
        ])

aws = {
        'hosted-zones': {
            'global': None,
            'group': 0,
            'service': 'route53',
            'command': 'list_hosted_zones',
            },
        'regions': {
            'global': None,
            'group': 0,
            'service': 'ec2',
            'command': 'describe_regions',
            },
        'vpc-association-authorizations': {
            'global': None,
            'service': 'route53',
            'command': 'list_vpc_association_authorizations',
            'cleanup': set(['HostedZoneId']),
            },
        'hosted-zone-associations': {
            'global': None,
            'service': 'route53',
            'command': 'get_hosted_zone',
            'cleanup': set(['HostedZone']),
            },
        'vpcs': {
            'service': 'ec2',
            'command': 'describe_vpcs',
            },
        'resolver-endpoints': {
            'service': 'route53resolver',
            'command': 'list_resolver_endpoints',
            },
        }


class WexAccount:
    def __init__(self, profile):
        self.data = dict([[name, None] for name in aws.keys()])
        self.profile = profile

    def cache_data(self, key, value=list()):
        tempdir = (f'{tempfile.gettempdir()}/{self.profile}')
        if not os.path.isdir(f'{tempdir}'):
            os.mkdir(f'{tempdir}')
        if value:
            with open(f'{tempdir}/{key}.json', 'w') as f:
                json.dump(value, f)
        else:
            try:
                with open(f'{tempdir}/{key}.json') as f:
                    value = json.load(f)
            except FileNotFoundError:
                pass
        return value

    def aws_items(self, item, region, args):
        value = list()

        session = boto3.Session(profile_name=self.profile, region_name=region)
        client = session.client(aws[item]['service'])

        try:
            page = getattr(client, aws[item]['command'])(**args)

            while True:
                keys = page.keys() - system_cleanup
                if 'cleanup' in aws[item]:
                    keys -= aws[item]['cleanup']

                if len(keys) != 1:
                    raise ValueError(f'Unexpected keys: {page.keys()}')

                value += page[list(keys)[0]]

                if 'IsTruncated' not in page.keys():
                    break

                if not json.loads(f'{page["IsTruncated"]}'.lower()):
                    break

                args['Marker'] = page['NextMarker']
                page = getattr(client, aws[item]['command'])(**args)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f'Exception (non-fatal): {e}')
            value.clear()  # eg. route53resolver unavail in sa-east-1

        return value

    def service_key(self, key):
        if 'group' in aws[key]:
            return aws[key]['group']
        return 100

    def load(self):
        for name in sorted(aws.keys(), key=self.service_key):
            cached = self.cache_data(name)
            if cached:
                self.data[name] = cached
                continue  # loaded from cache

            if 'global' in aws[name]:
                if name in [
                        'vpc-association-authorizations',
                        'hosted-zone-associations',
                        ]:
                    zones = [
                            re.sub('.*/', '', zone['Id'])
                            for zone in self.data['hosted-zones']
                            if zone['Config']['PrivateZone']
                            ]

                    self.data[name] = dict()
                    for zone in zones:
                        args = dict()
                        if name == 'vpc-association-authorizations':
                            args['HostedZoneId'] = zone
                        elif name == 'hosted-zone-associations':
                            args['Id'] = zone
                        else:
                            raise ValueError(f'{name} should not be here')
                        self.data[name][zone] = \
                            self.aws_items(name, 'us-east-1', args)
                else:
                    self.data[name] = self.aws_items(name, 'us-east-1', dict())
            else:
                regions = [
                        item['RegionName']
                        for item in self.data['regions']
                        ]

                self.data[name] = dict()
                for region in regions:
                    self.data[name][region] = \
                        self.aws_items(name, region, dict())

            self.cache_data(name, self.data[name])

        return self
