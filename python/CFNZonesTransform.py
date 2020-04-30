#!/usr/bin/env python3
from argparse import Namespace
from copy import deepcopy
from datetime import datetime
import logging
import re
import traceback
import utilities


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


def resource_share(parm, zone_slot, zone_list, principal_slot, principal_list):
    friendly_name = parm.share_prefix + '-' + \
            ('%04x' % principal_slot) + \
            ('%04x' % zone_slot)

    resource_ids = [
            retrieve_logical_id(parm, 'DomainName', zone_name)
            for zone_name
            in zone_list
            ]

    share_id = utilities.mk_id(
            [
                f'rs{parm.kind}ResourceShare',
                parm.region_name,
                parm.target_env,
                parm.share_prefix,
                principal_list,
                zone_slot,
                ]
            )

    return (
            share_id,
            {
                'Type': 'AWS::RAM::ResourceShare',
                'Properties': {
                    'Name': friendly_name,
                    'ResourceArns': [
                        utilities.fn_get_att(resource_id, 'Arn')
                        for resource_id
                        in resource_ids
                        ],
                    'Principals': principal_list,
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


def load_existing_data(parm):
    parm.ram_shares = \
        utilities.boto3_call('get_resource_shares',
                             request={
                                 'resourceOwner': 'SELF',
                                 }
                             )

    parm.ram_resources = \
        utilities.boto3_call('list_resources',
                             request={
                                 'resourceOwner': 'SELF',
                                 'resourceType':
                                 'route53resolver:ResolverRule',
                                 }
                             )

    parm.ram_principals = \
        utilities.boto3_call('list_principals',
                             request={
                                 'resourceOwner': 'SELF',
                                 'resourceType':
                                 'route53resolver:ResolverRule',
                                 }
                             )

    parm.r53resolver_rules = \
        utilities.boto3_call('list_resolver_rules')


def join_resources(parm):
    return dict(
            [
                (
                    int(share['name'][-4:], 16),
                    [
                        [
                            rule['DomainName']
                            for rule in parm.r53resolver_rules
                            if resource['arn'] == rule['Arn']
                            and rule['Status'] == 'COMPLETE'
                            ][0]
                        for resource in parm.ram_resources
                        if resource['type'] == 'route53resolver:ResolverRule'
                        and resource['resourceShareArn']
                        == share['resourceShareArn']
                        ]
                    )
                for share in [
                    share for share
                    in parm.ram_shares
                    if re.match(parm.share_prefix + '-\\d{8}$', share['name'])
                    and share['status'] == 'ACTIVE'
                    ]
                ]
            )


def join_principals(parm):
    return dict(
            [
                (
                    int(share['name'][-8:-4], 16),
                    [
                        principal['id']
                        for principal in parm.ram_principals
                        if principal['resourceShareArn']
                        == share['resourceShareArn']
                        ]
                    )
                for share in [
                    share for share
                    in parm.ram_shares
                    if re.match(parm.share_prefix + '-\\d{8}$', share['name'])
                    and share['status'] == 'ACTIVE'
                    ]
                ]
            )


def pre_to_post(pre, new_objs, max_objs):
    post = dict(
            [
                (
                    int(number),
                    list()
                    )
                for number
                in pre
                ]
            )

    for idx in pre:
        new_idx = int(idx)  # use `idx` as-is, make `new_idx` int
        for old_obj in sorted(pre[idx]):
            if old_obj in new_objs and \
                    len(post[new_idx]) < int(max_objs):
                post[new_idx].append(old_obj)
                new_objs.remove(old_obj)

    serial = 0  # start scanning from zero
    while True:
        for new_obj in sorted(new_objs):
            for idx in sorted(post):
                if len(post[idx]) < int(max_objs):
                    post[idx].append(new_obj)
                    new_objs.remove(new_obj)
                    break

        if not new_objs:
            break

        while serial in post:
            serial += 1

        post[serial] = list()

    return post


def clean_zone_names(zones):
    return set([
        zone if zone.endswith('.') else zone + '.'
        for zone
        in [zone.strip() for zone in zones]
        ])


def target_endpoint_ips(parm):
    if parm.kind == 'AwsZones':
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
    else:
        raise RuntimeError('Internal: kind should be AwsZones|OnPremZones')


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

    load_existing_data(parm)

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
    infra_pre = join_resources(parm)
    infra_post = pre_to_post(infra_pre, set(
        [
            resource['Properties']['DomainName']
            for resource
            in parm.resources.values()
            if resource['Type'] == 'AWS::Route53Resolver::ResolverRule'
            ]
        ),
        parm.max_rules)

    principal_pre = join_principals(parm)
    principal_post = pre_to_post(principal_pre, deepcopy(
        parm.principals
        ),
        parm.max_rules)

    throttle = None  # chain resources together to avoid API throttling
    for principal_slot, principal_list in principal_post.items():
        for zone_slot, zone_list in infra_post.items():
            share_id, share_data = \
                    resource_share(parm,
                                   zone_slot,
                                   zone_list,
                                   principal_slot,
                                   principal_list)
            # add a twist, make 'em depend one from the other
            if throttle is not None:
                share_data['DependsOn'] = [
                        throttle
                        ]
            throttle = share_id
            parm.resources[share_id] = share_data

            for principal in principal_list:
                saa_id, saa_data = \
                        resource_auto_associate(parm, share_id, principal)

                saa_data['DependsOn'] = [
                        throttle
                        ]
                throttle = saa_id

                parm.resources[saa_id] = saa_data

    return {
            'requestId': event['requestId'],
            'status': 'SUCCESS',
            'fragment': event['fragment']
            }
