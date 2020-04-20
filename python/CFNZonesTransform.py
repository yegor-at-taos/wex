#!/usr/bin/env python3
from copy import deepcopy
from datetime import datetime
import logging
import re
import traceback
import utilities


logger = logging.getLogger()
logger.setLevel(logging.INFO)


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


def retrieve_cfn_export(event, wex, export):
    # Generate template import statement, however use generated value to
    # resolve endpoint addresses via route53resolver
    export_name = utilities.import_value(event, wex, export)
    export_name = export_name['Fn::ImportValue']

    for export in utilities.boto3_call('list_exports'):
        if export['Name'] == export_name:
            return export['Value']

    raise RuntimeError(f'{export_name} not found in CFN exports')


def retrieve_inbound_ips(event, wex):
    endpoint_id = retrieve_cfn_export(event, wex, 'endpoint_inbound')

    value = [
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

    if not value:
        raise RuntimeError("Can't retrieve endpoint IP addresses")

    return value


def create_template(event, context):
    '''
    Assuming the correct template; do not attempt to recover.
    '''
    region, shared = event['region'], list()

    wex = event['fragment']['Mappings'].pop('Wex')

    # check if default settings are present in Infoblox
    if 'default' in wex['Infoblox']['Regions']:
        data = deepcopy(wex['Infoblox']['Regions']['default'])
    else:
        data = dict()

    # Update if regional data block is present
    if region in wex['Infoblox']['Regions']:
        data.update(wex['Infoblox']['Regions'][region])

    kind = event['templateParameterValues']['Instantiate']

    if kind == 'AwsZones':
        target_endpoint_ips = retrieve_inbound_ips(event, wex)
    elif kind == 'OnPremZones':
        target_endpoint_ips = [
                {
                    'Ip': target_ip,
                    'Port': 53,
                    }
                for target_ip
                in data['OnPremResolverIps']
                ]
    else:
        raise RuntimeError(f'Transform type {kind} is invalid')

    resources = dict()
    event['fragment']['Resources'] = resources

    for zone in wex[kind]:
        zone_name = re.sub('_$', '', re.sub('\\.', '_', zone.strip()))

        rule_id = utilities.mk_id(
                [
                    f'rr{kind}Zone',
                    zone,
                    region,
                    ]
                )

        shared.append(rule_id)  # always share generated rules

        resources[rule_id] = {
                'Type': 'AWS::Route53Resolver::ResolverRule',
                'Properties': {
                    'Name': zone_name,
                    'RuleType': 'FORWARD',
                    'DomainName': zone,
                    'ResolverEndpointId':
                        utilities.import_value(
                            event,
                            wex,
                            'endpoint_outbound'
                            ),
                    'TargetIps': target_endpoint_ips,
                    'Tags': wex['Tags'] + [
                        {
                            'Key': 'Name',
                            'Value': zone_name,
                            },
                        ],
                    },
                }

        # Associate to all locally exported VPCs (except the ones listed
        # in the DNI section).
        if kind == 'OnPremZones':
            for export in utilities.boto3_call('list_exports'):
                if not utilities.is_exported_vpc(export):
                    continue
                if 'VpcDni' in data and \
                        export['Name'] in data['VpcDni']:
                    continue
                rule_assoc_id = utilities.mk_id(
                        [
                            f'ra{kind}ZoneAssoc',
                            zone,
                            region,
                            ]
                        )

                resources[rule_assoc_id] = {
                        'Type':
                        'AWS::Route53Resolver::ResolverRuleAssociation',
                        'Properties': {
                            'ResolverRuleId':
                                utilities.fn_get_att(rule_id,
                                                     'ResolverRuleId'),
                            'VPCId': export['Value'],
                            }
                        }

    # Share created ResolverRule(s) to all principals (except self)
    principals = set(wex['Accounts']) - set([event['accountId']])

    # Per Naidu: create just one ResourceShare object for everything
    if shared:
        share_id = utilities.mk_id(
                [
                    f'rs{kind}ResourceShare',
                    region,
                    ]
                )

        resources[share_id] = {
                'Type': 'AWS::RAM::ResourceShare',
                'Properties': {
                    'Name': f'Wex-{kind}-Zones-Share',
                    'ResourceArns': [
                            utilities.fn_get_att(shared_id, 'Arn')
                            for shared_id
                            in shared
                            ],
                    'Principals': list(principals),
                    'Tags': wex['Tags'] + [
                        {
                            'Key': 'Name',
                            'Value': f'Wex-{kind}-Zones-Share',
                            },
                        ],
                    },
                }

    # Do not remove 'LastUpdated'; it forces service Lambda to run on update
    # NOTE: rule_id s the same across the accounts.
    # However, AWS documentation does not formally guarantee that.
    for principal in principals:
        auto_associate_id = utilities.mk_id(
                [
                    f'cr{kind}AutoAssociate',
                    region,
                    principal,
                    ]
                )

        resources[auto_associate_id] = {
                'Type': 'AWS::CloudFormation::CustomResource',
                'Properties': {
                    'ServiceToken':
                        utilities.import_value(
                            event,
                            wex,
                            'auto_associate_function'
                            ),
                    'VpcDni': data['VpcDni'],
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
                                                'Ref': 'CrossAccountRoleName',
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

    return {
            'requestId': event['requestId'],
            'status': 'SUCCESS',
            'fragment': event['fragment']
            }
