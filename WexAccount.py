#!/usr/bin/env python3
import boto3
import json
import os
import re
import tempfile
import logging

system_cleanup = set([
        'ResponseMetadata',
        'MaxResults',
        'IsTruncated',
        'MaxItems',
        'Marker',
        'NextMarker',
        'NextToken',
        ])

aws = {
        'regions': {
            'global': None,
            'service': 'ec2',
            'command': 'describe_regions',
            },
        'vpc-association-authorizations': {
            'global': None,
            'dep': [
                'hosted-zones',
                ],
            'service': 'route53',
            'command': 'list_vpc_association_authorizations',
            'cleanup': set(['HostedZoneId']),
            },
        'hosted-zone-associations': {
            'global': None,
            'dep': [
                'hosted-zones',
                ],
            'service': 'route53',
            'command': 'get_hosted_zone',
            'cleanup': set(['HostedZone']),
            },
        'hosted-zones': {
            'global': None,
            'service': 'route53',
            'command': 'list_hosted_zones',
            },
        'vpcs': {
            'service': 'ec2',
            'command': 'describe_vpcs',
            },
        'availability-zones': {
            'dep': [
                'vpcs',
                ],
            'service': 'ec2',
            'command': 'describe_availability_zones',
            },
        'subnets': {
            'service': 'ec2',
            'command': 'describe_subnets',
            },
        'route-tables': {
            'service': 'ec2',
            'command': 'describe_route_tables',
            },
        'prefix-lists': {
            'service': 'ec2',
            'command': 'describe_prefix_lists',
            },
        'resolver-endpoints': {
            'service': 'route53resolver',
            'command': 'list_resolver_endpoints',
            'skip-regions': [
                'sa-east-1',  # Route 53 Resolver unsupported in São Paulo
                'me-south-1',  # Route 53 Resolver unsupported in Bahrain
                ],
            },
        'resolver-endpoint-ip-addresses': {
            'dep': [
                'resolver-endpoints'
                ],
            'service': 'route53resolver',
            'command': 'list_resolver_endpoint_ip_addresses',
            'skip-regions': [
                'sa-east-1',
                'me-south-1',
                ],
            },
        'resolver-rules': {
            'dep': [
                'vpcs',
                ],
            'service': 'route53resolver',
            'command': 'list_resolver_rules',
            'skip-regions': [
                'sa-east-1',
                'me-south-1',
                ],
            },
        'resolver-rule-associations': {
            'dep': [
                'vpcs',
                ],
            'service': 'route53resolver',
            'command': 'list_resolver_rule_associations',
            'skip-regions': [
                'sa-east-1',
                'me-south-1',
                ],
            },
        }


class WexAccount:
    def __init__(self, profile):
        self.logger = logging.getLogger('WexAnalyzer')
        self.logger.setLevel(logging.DEBUG)


        formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        ch = logging.StreamHandler()
        ch.setLevel(logging.WARNING)

        self.logger.addHandler(ch)

        self.profile = profile
        self.data = dict([
            [name, dict()]
            for name in aws.keys()
            ])
        self.load()

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

    def aws_items(self, args):
        value = list()

        self.logger.info(f'loading {args} ..')

        item, region = args.pop('Item'), args.pop('Region')

        session = boto3.Session(profile_name=self.profile, region_name=region)
        client = session.client(aws[item]['service'])

        try:
            while True:
                page = getattr(client, aws[item]['command'])(**args)
                keys = page.keys() - system_cleanup

                # if extra cleanup is required - do it now
                if 'cleanup' in aws[item]:
                    keys -= aws[item]['cleanup']

                # at this point there should be only one key; bail if more
                if len(keys) != 1:
                    raise ValueError(f'Unexpected keys: {keys}')

                value += page[list(keys)[0]]

                if 'NextToken' not in page and \
                        ('IsTruncated' not in page or \
                        not json.loads(f'{page["IsTruncated"]}'.lower())):
                    break

                # more results expected; process NextToken/NextMarker
                if 'NextMarker' in page:
                    args['Marker'] = page['NextMarker']
                elif 'NextToken' in page:
                    args['NextToken'] = page['NextToken']
                else:
                    raise ValueError(f'Internal error: {page}')

                self.logger.info(f'\t.. more results expected: {args}')
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f'Internal error {item}/{region}: {e}')
            raise

        return value

    def resolve_dependencies(self):
        '''
        Returns AWS services in order that allows to resolve the dependencies
        TODO deadlock detection
        '''
        regional, worldwide, defined = list(), list(), list(aws.keys())

        while True:
            name = defined.pop(0)  # take left element

            dst = worldwide if 'global' in aws[name] else regional
            dep = list() if 'dep' not in aws[name] else list(aws[name]['dep'])

            for index in range(len(dst)):
                if not dep:
                    dst.insert(index, name)
                    name = None
                    break

                if dst[index] in dep:
                    dep.remove(dst[index])

            if name:
                if dep:
                    defined.append(name)
                else:
                    dst.append(name)

            if not defined:
                break

        return worldwide + regional

    def load(self):
        for name in self.resolve_dependencies():

            # check if we have cached data stored under `/tmp/{profile}`
            cached = self.cache_data(name)
            if cached:
                self.data[name] = cached
                continue  # data is loaded from cache; don't reload

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

                    for zone in zones:
                        args = {
                                'Item': name,
                                'Region': 'us-east-1',
                                }

                        if name == 'vpc-association-authorizations':
                            args['HostedZoneId'] = zone
                        elif name == 'hosted-zone-associations':
                            args['Id'] = zone
                        else:
                            raise ValueError(f'{name} should not be here')

                        self.data[name][zone] = self.aws_items(args)
                else:
                    args = {
                            'Item': name,
                            'Region': 'us-east-1',
                            }
                    self.data[name] = self.aws_items(args)
            else:
                # collect data for all regions (minus unsupported)
                regions = [
                        region['RegionName']
                        for region in self.data['regions']
                        if 'skip-regions' not in aws[name]
                        or region['RegionName']
                        not in aws[name]['skip-regions']
                        ]

                for region in regions:
                    if name in [
                            'resolver-endpoint-ip-addresses',
                            ]:
                        self.data[name][region] = dict()
                        for id in [
                                id['Id']
                                for id in
                                self.data['resolver-endpoints'][region]
                                ]:
                            args = {
                                    'Item': name,
                                    'Region': region,
                                    'ResolverEndpointId': id,
                                    }
                            self.data[name][region][id] = self.aws_items(args)
                    else:
                        args = {
                                'Item': name,
                                'Region': region,
                                }
                        self.data[name][region] = self.aws_items(args)

            self.cache_data(name, self.data[name])

        return self

    def get_regions(self, name):
        '''
        Returns regions having `name` objects defined.
        Returns None for global types (hosted-zones, etc.)
        '''
        if 'global' in aws[name]:
            return None
        return [
                region
                for region in self.data[name]
                if self.data[name][region]
                ]


if __name__ == '__main__':
    wex = WexAccount('wex-prod').load()
    print(wex.get_regions('vpcs'))
