#!/usr/bin/env python3
from argparse import Namespace
from copy import deepcopy
from datetime import datetime
import logging
import re
import traceback
import utilities

import json


logger = logging.getLogger('CFNZonesTransform')
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
logger.addHandler(ch)


def handler(event, context):
    try:
        return create_template(event, context)

    except Exception as e:
        return {
                'requestId': event['requestId'],
                'status': 'BIGBADABOOM',  # anything but SUCCESS is a failure
                'fragment': event['fragment'],
                'errorMessage': f'{e}: {event} {traceback.format_exc()}',
                }


def is_local_test(parm):  # TODO: remove
    return 'LocalTest' in parm.event['templateParameterValues']


def retrieve_cfn_export(event, wex, export):
    # Generate template import statement, however use generated value to
    # resolve endpoint addresses via route53resolver
    export_name = utilities.import_value(event, wex, export)
    export_name = export_name['Fn::ImportValue']

    for export in utilities.boto3_call('list_exports'):
        if export['Name'] == export_name:
            return export['Value']

    raise RuntimeError(f'{export_name} not found in CFN exports')


def retrieve_logical_id(parm, name, match):
    if name == 'DomainName':
        aws_type = 'AWS::Route53Resolver::ResolverRule'
    else:
        aws_type = 'AWS::Route53Resolver::ResolverRule'

    for k, v in parm.resources.items():
        if v['Type'] == aws_type and v['Properties'][name] == match:
            return k
    raise ValueError(f'Can\'t find LogicalId for: {name}')


def resource_rule(parm, zone):
    zone_friendly_name = re.sub('\\.', '_', zone + parm.target_env)

    rule_id = utilities.mk_id(
            [
                f'rr{parm.kind}Zone',
                parm.region_name,
                parm.target_env,
                zone,
                ]
            )

    return (
            rule_id,
            {
                'Type': 'AWS::Route53Resolver::ResolverRule',
                'Properties': {
                    'Name': zone_friendly_name,
                    'RuleType': 'FORWARD',
                    'DomainName': zone,
                    'ResolverEndpointId':
                    utilities.import_value(
                        parm.event,
                        parm.wex,
                        'endpoint_outbound'
                        ),
                    'TargetIps': parm.target_endpoint_ips,
                    'Tags': parm.wex['Tags'] + [
                        {
                            'Key': 'Name',
                            'Value': zone_friendly_name,
                            },
                        {
                            'Key': 'LogicalId',
                            'Value': rule_id,
                            },
                        ],
                    },
                }
            )


def resource_rule_association(parm, vpc_id, rule_id):
    return (
            utilities.mk_id(
                [
                    f'ra{parm.kind}ZoneAssoc',
                    parm.region_name,
                    parm.target_env,
                    vpc_id,
                    rule_id,
                    ]
                ),
            {
                'Type':
                'AWS::Route53Resolver::ResolverRuleAssociation',
                'Properties': {
                    'VPCId': vpc_id,
                    'ResolverRuleId': utilities.fn_get_att(rule_id,
                                                           'ResolverRuleId'),
                    }
                }
            )


def resource_share(parm, serial, domain_names):
    friendly_name = parm.share_prefix + ('-%04x' % serial)

    resource_arns = [
            retrieve_logical_id(parm, 'DomainName', domain_name)
            for domain_name
            in domain_names
            ]

    share_id = utilities.mk_id(
            [
                f'rs{parm.kind}ResourceShare',
                parm.region_name,
                parm.target_env,
                serial,
                ]
            )

    return (
            share_id,
            {
                'Type': 'AWS::RAM::ResourceShare',
                'Properties': {
                    'Name': friendly_name,
                    'ResourceArns': resource_arns,
                    'Principals': parm.principals,
                    'Tags': parm.wex['Tags'] + [
                        {
                            'Key': 'Name',
                            'Value': friendly_name,
                            },
                        {
                            'Key': 'LogicalId',
                            'Value': share_id,
                            },
                        ],
                    },
                }
            )


def resource_auto_associate(parm, share_id, principal):
    return (
            utilities.mk_id(
                [
                    f'cr{parm.kind}ZoneAutoAssoc',
                    parm.region_name,
                    parm.target_env,
                    share_id,
                    principal,
                    ]
                ),
            {
                'Type': 'AWS::CloudFormation::CustomResource',
                'Properties': {
                    'ServiceToken':
                        utilities.import_value(
                            parm.event,
                            parm.wex,
                            'auto_associate_function'
                            ),
                    'VpcDni': parm.region_data['VpcDni'],
                    'RoleARN': {
                        'Fn::Join': [
                            ':', [
                                'arn:aws:iam:',
                                principal,
                                {
                                    'Fn::Join': [
                                        '/', [
                                            'role',
                                            {
                                                'Ref':
                                                'CrossAccountRoleName',
                                                },
                                            ],
                                        ],
                                    },
                                ],
                            ],
                        },
                    'ShareArn': utilities.fn_get_att(share_id, 'Arn'),
                    'LastUpdated': datetime.isoformat(datetime.now()),
                    },
                'DependsOn': [
                    share_id,
                    ]
                }
            )


def load_infra(parm):
    '''
    Retrieve existing infra.
    '''
    if is_local_test(parm):  # TODO remove
        with open('mock.infra') as f:
            return json.load(f)

    ram_shares = [
            share
            for share
            in utilities.boto3_call('get_resource_shares',
                                    request={
                                        'resourceOwner': 'SELF'
                                        }
                                    )
            if re.match(parm.share_prefix + '-\\d{4}$', share['name'])
            and share['status'] == 'ACTIVE'
            ]

    ram_resources = [
            resource for resource
            in utilities.boto3_call('list_resources',
                                    request={
                                        'resourceOwner': 'SELF'
                                        }
                                    )
            ]

    r53resolver_rules = [
            rule
            for rule
            in utilities.boto3_call('list_resolver_rules')
            ]

    return dict(
            [
                (
                    int(share['name'][-4:], 16),
                    [
                        [
                            rule['DomainName']
                            for rule in r53resolver_rules
                            if resource['arn'] == rule['Arn']
                            and rule['Status'] == 'COMPLETE'
                            ][0]
                        for resource in ram_resources
                        if resource['type'] == 'route53resolver:ResolverRule'
                        and resource['resourceShareArn']
                        == share['resourceShareArn']
                        ]
                    )
                for share in ram_shares
                ]
            )


def clean_zone_names(zones):
    return set([
        zone if zone.endswith('.') else zone + '.'
        for zone
        in [zone.strip() for zone in zones]
        ])


def target_endpoint_ips(parm):
    if is_local_test(parm):  # TODO remove
        return [
                {
                    'Ip': '127.0.0.1',
                    'Port': '53',
                    }
                ]
    elif parm.kind == 'AwsZones':
        endpoint_id = retrieve_cfn_export(parm.event,
                                          parm.wex,
                                          'endpoint_inbound')
        return [
                {
                    'Ip': ip['Ip'],
                    'Port': '53',
                    }
                for ip
                in utilities.boto3_call('list_resolver_endpoint_ip_addresses',
                                        request={
                                            'ResolverEndpointId': endpoint_id,
                                            }
                                        )
            ]
    elif parm.kind == 'OnPremZones':
        return [
                {
                    'Ip': target_ip,
                    'Port': 53,
                    }
                for target_ip
                in parm.region_data['OnPremResolverIps']
                ]


def create_template(event, context):
    '''
    Assuming the correct template; do not attempt to recover.
    '''
    parm = Namespace(
            event=event,
            region_name=event['region'],
            region_data=dict(),
            wex=event['fragment']['Mappings'].pop('Wex'),
            )

    # calculate region data by updating `default` with the specific region
    for k in ['default', parm.region_name]:
        if k in parm.wex['Infoblox']['Regions']:
            parm.region_data.update(
                    deepcopy(parm.wex['Infoblox']['Regions'][k]))

    for k, v in [
            ('Instantiate', 'kind'),
            ('Environment', 'env'),
            ('TargetEnvironment', 'target_env'),
            ('MaxRulesPerShare', 'max_rules'),
            ]:
        parm.__setattr__(v, event['templateParameterValues'][k])

    # prefix for the resources exported by this stack (eg. RAM shares)
    parm.share_prefix = \
        f'wex-{parm.kind}-zones-share-{parm.target_env}'.lower()

    # list of principals to share rules to
    parm.principals = sorted(set(parm.wex['Accounts']) -
                             set([parm.event['accountId']]))

    # cache target endpoint ips, they are common for all the rules
    parm.target_endpoint_ips = target_endpoint_ips(parm)

    parm.resources = dict()  # acts as a symlink to event[..]
    event['fragment']['Resources'] = parm.resources

    if is_local_test(parm):  # TODO: remove
        parm.vpcs = [
                'vpc-0123456789',
                'vpc-1234567890'
                ]
    else:
        if parm.kind == 'OnPremZones':
            if 'VpcDni' not in parm.region_data:
                parm.region_data['VpcDni'] = set()

            parm.vpcs = [
                    export['Value']
                    for export
                    in utilities.boto3_call('list_exports')
                    if utilities.is_exported_vpc(export)
                    and export['Value'] not in parm.region_data['VpcDni']
                    ]
        else:
            parm.vpcs = list()  # do not ever associate hosted zones

    for zone in clean_zone_names(parm.wex[parm.kind]):
        rule_id, rule_data = resource_rule(parm, zone)
        parm.resources[rule_id] = rule_data

        # Associate to all locally exported VPCs
        # (except the ones listed in the DNI section)
        for vpc_id in parm.vpcs:
            rule_assoc_id, rule_assoc_data = \
                    resource_rule_association(parm, vpc_id, rule_id)
            parm.resources[rule_assoc_id] = rule_assoc_data

    # zones are created and possibly associated to [some] local VPC(s)

    # load existing infra; note some keys might be missing, like '1' here:
    # {
    #   0: [
    #      "giftvoucher.com.",
    #       ...
    #   ],
    #   2: [
    #      "giftvoucher.net.",
    #      ...
    #   ],
    #   ...
    # }
    infra_pre = load_infra(parm)

    # create target infra scuffolds:
    #  same as infra_pre with no ResourceShare references
    infra_post = dict(
            [
                (
                    int(number),
                    list()
                    )
                for number
                in infra_pre
                ]
            )

    # zones we are about to create; let's use half-baked template
    zones = set(
            [
                resource['Properties']['DomainName']
                for resource
                in parm.resources.values()
                if resource['Type'] == 'AWS::Route53Resolver::ResolverRule'
                ]
            )

    # 1. Copy parts of an existing infra that is still relevant
    for idx in infra_pre:
        idx_int = int(idx)
        for zone in sorted(infra_pre[idx]):
            if zone in zones and \
                    len(infra_post[idx_int]) < int(parm.max_rules):
                infra_post[idx_int].append(zone)
                zones.remove(zone)

    serial = 0  # start scanning from zero
    while True:
        # 2a. Process remaining rules; append to existing shares
        for zone in sorted(zones):
            for idx in sorted(infra_post):
                if len(infra_post[idx]) < int(parm.max_rules):
                    infra_post[idx].append(zone)
                    zones.remove(zone)
                    break

        if not zones:
            break

        # 2b. Create one blank share
        if serial not in infra_post:
            infra_post[serial] = list()
        else:
            serial += 1

    # infra created, translate to resources
    for serial, domain_names in infra_post.items():
        share_id, share_data = \
                resource_share(parm, serial, domain_names)
        parm.resources[share_id] = share_data
        for principal in parm.principals:
            saa_id, saa_data = \
                    resource_auto_associate(parm, share_id, principal)
            parm.resources[saa_id] = saa_data

    return {
            'requestId': event['requestId'],
            'status': 'SUCCESS',
            'fragment': event['fragment']
            }
