#!/usr/bin/env python3
import boto3
import json
import os
import re
import tempfile
import logging

from argparse import Namespace

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
            'match': 'RegionName',
            },
        'vpc-association-authorizations': {
            'global': None,
            'dep': {
                'hosted-zones': None,
                },
            'service': 'route53',
            'command': 'list_vpc_association_authorizations',
            'cleanup': set(['HostedZoneId']),
            },
        'hosted-zone-associations': {
            'global': None,
            'dep': {
                'hosted-zones': None,
                },
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
            'dep': {
                'vpcs': None,
                },
            'service': 'ec2',
            'command': 'describe_availability_zones',
            },
        'subnets': {
            'service': 'ec2',
            'command': 'describe_subnets',
            'match': 'SubnetId',
            },
        'security-groups': {
            'service': 'ec2',
            'command': 'describe_security_groups',
            },
        'security-group-references': {
            'dep': {
                'security-groups': {
                    'GroupId': ['GroupId'],  # TODO command uses list(...)
                    },
                },
            'service': 'ec2',
            'command': 'describe_security_group_references',
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
            'dep': {
                'resolver-endpoints': {
                    'Id': 'ResolverEndpointId',  # TODO command uses string
                    },
                },
            'service': 'route53resolver',
            'command': 'list_resolver_endpoint_ip_addresses',
            'skip-regions': [
                'sa-east-1',
                'me-south-1',
                ],
            },
        'resolver-rules': {
            'dep': {
                'vpcs': None,
                },
            'service': 'route53resolver',
            'command': 'list_resolver_rules',
            'skip-regions': [
                'sa-east-1',
                'me-south-1',
                ],
            },
        'resolver-rule-associations': {
            'dep': {
                'vpcs': None,
                },
            'service': 'route53resolver',
            'command': 'list_resolver_rule_associations',
            'skip-regions': [
                'sa-east-1',
                'me-south-1',
                ],
            },
        }


class WexAccount:
    def __init__(self, args, profile):
        self.logger = logging.getLogger('WexAnalyzer')
        self.logger.setLevel(args.logging)

        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)

        formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)

        self.logger.addHandler(ch)

        self.profile = profile
        self.data = dict([
            [name, dict()]
            for name in aws.keys()
            ])
        self.retrieve_all()

    def cache_data(self, key, value=None):
        tempdir = (f'{tempfile.gettempdir()}/{self.profile}')

        if not os.path.isdir(f'{tempdir}'):
            os.mkdir(f'{tempdir}')

        if value is not None:
            with open(f'{tempdir}/{key}.json', 'w') as f:
                json.dump(value, f)
            return

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

                if 'NextToken' not in page:
                    if 'IsTruncated' not in page or \
                            not json.loads(f'{page["IsTruncated"]}'.lower()):
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
        Returns AWS service names in the correct order; TODO deadlock detection
        '''
        regional, worldwide, objects = list(), list(), list(aws.keys())

        while True:
            name = objects.pop(0)

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
                    objects.append(name)
                else:
                    dst.append(name)

            if not objects:
                break

        return worldwide + regional

    def retrieve_all(self):
        for name in self.resolve_dependencies():

            # check if we have cached data stored under `/tmp/{profile}`
            cached = self.cache_data(name)
            if cached is not None:
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
                        for region
                        in self.data['regions']
                        if 'skip-regions'
                        not in aws[name]
                        or region['RegionName']
                        not in aws[name]['skip-regions']
                        ]

                for region in regions:
                    # TODO avoid copy/paste, make it a table lookup
                    if name in [
                            'resolver-endpoint-ip-addresses',
                            ]:
                        self.data[name][region] = dict()
                        for id in [
                                id['Id']
                                for id
                                in self.data['resolver-endpoints'][region]
                                ]:
                            args = {
                                    'Item': name,
                                    'Region': region,
                                    'ResolverEndpointId': id,
                                    }
                            self.data[name][region][id] = self.aws_items(args)
                    elif name in [
                            'security-group-references',
                            ]:
                        self.data[name][region] = dict()
                        for id in [
                                id['GroupId']
                                for id
                                in self.data['security-groups'][region]
                                ]:
                            args = {
                                    'Item': name,
                                    'Region': region,
                                    'GroupId': [id],
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

    def retrieve_object(self, args):
        '''
        args = {
            'name': (subnets|vpcs|...),
            'match': (subnet_id|vpc_id|...),
            'region': region_name,  # optional
            }
        '''
        src = self.data[args['name']]

        if 'global' not in aws[args['name']]:
            # region is present; use data from args['region'] only
            src = src[args['region']]

        if isinstance(src, dict):
            if args['match'] in src:
                return src[args['match']]
        elif isinstance(src, list):
            for obj in src:
                if obj[aws[args['name']]['match']] == args['match']:
                    return obj

        self.logger.warn(f'Object not found: {json.dumps(args)}')
        return None

    def resolver_ip_public(self, region_name, ip):
        '''
        Per requirement we only care about 'Name' tag to contain
        'private' substring
        '''
        subnet = self.retrieve_object({
            'name': 'subnets',
            'region': region_name,
            'match': ip['SubnetId'],
            })

        if 'Tags' not in subnet:
            self.logger.warn(f'Subnet is untagged: {json.dumps(subnet)}')

        value = None

        for pair in subnet['Tags']:
            if 'Key' not in pair or 'Value' not in pair:
                continue
            if pair['Key'] != 'Name':
                continue
            value = pair['Value'].lower().find('private') == -1
            break

        if value is None:
            self.logger.warn(f'Subnet is tagged but no `Name` tag:'
                             f'{json.dumps(subnet)}')
        return value

    def resolver_ip_az(self, region_name, ip):
        subnet = self.retrieve_object({
            'name': 'subnets',
            'region': region_name,
            'match': ip['SubnetId'],
            })
        return subnet['AvailabilityZoneId']

    def is_resolver_endpoint_valid(self, region_name, endpoint):
        '''
        WEX Inc. requirements:
        1. 2 IP addresses
        2. Different AZs
        3. Private subnets
        '''
        endpoint_ips = self.retrieve_object({
            'name': 'resolver-endpoint-ip-addresses',
            'region': region_name,
            'match': endpoint['Id'],
            })

        endpoints = dict([
            [
                ip["IpId"], {
                    'az': self.resolver_ip_az(region_name, ip),
                    'pub': self.resolver_ip_public(region_name, ip),
                    }
                ]
            for ip in endpoint_ips
            ])

        private = dict([
                endpoint
                for endpoint
                in endpoints.items()
                if not endpoint[1]['pub']
                ])

        private_azs = set([
            endpoint[1]['az']
            for endpoint
            in private.items()
            ])

        if len(private) != 2:
            self.logger.warn(f'Endpoint has {len(private)} private IPs:'
                             f' {endpoint["Id"]}')

        if len(private_azs) != 2:
            self.logger.warn(f'Endpoint has {len(private)} AZs:'
                             f' {endpoint["Id"]}')

        return len(private) == 2 and len(private_azs) == 2


if __name__ == '__main__':
    wex = WexAccount(Namespace(logging='DEBUG'), "wex-prod")
    endpoint = wex.data['resolver-endpoints']['us-east-1'][0]
    wex.is_resolver_endpoint_valid('us-east-1', endpoint)

    exit(0)

    if True:
        print(wex.retrieve_object({
            'name': 'resolver-endpoint-ip-addresses',
            'region': 'us-east-1',
            'match': 'rslvr-in-ca740e04c9c840849',
            }))
    if True:
        print(wex.retrieve_object({
            'name': 'regions',
            'match': 'us-east-1',
            }))
