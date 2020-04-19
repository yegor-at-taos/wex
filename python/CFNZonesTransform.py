#!/usr/bin/env python3
import boto3
from copy import deepcopy
import logging
import re
import traceback
import utilities


logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


def handler(event, context):
    try:
        value = create_template(deepcopy(event), context)

        sync_remote_associations(event, value, context)

        return value

    except Exception as e:
        return {
                'requestId': event['requestId'],
                'status': 'BIGBADABOOM',  # anything but SUCCESS is a failure
                'fragment': event['fragment'],
                'errorMessage': f'{e}: {event} {traceback.format_exc()}',
                }


def sync_remote_resource(resource, original, processed, context):
    return


def sync_remote_associations(original, processed, context):
    # This kind of duplicates the functionality of AutoAssociate but
    # only for existing objects as AutoAssociate is not get called for them.
    # Also, unlike AutoAssociate it does disassociate in case VPC got
    # added to the DNI list.
    wex = original['fragment']['Mappings']['Wex']

    resources = utilities.boto3_list('stack_resources',
                                     dict(),
                                     {
                                         'StackName': wex['StackName']
                                         }
                                     )
    print(resources)

    # AWS::CloudFormation::CustomResource is a resource used for cross-account
    # link; however, only process cross-account resources in the 'processed'
    # template. Assuming that if resource is going away then rule share is
    # also going away and will be gone (and disassociated automatically).
    for resource_name, resource in processed['fragment']['Resources'].items():
        if resource['Type'] != 'AWS::CloudFormation::CustomResource':
            continue

        if not isinstance(resource['Properties']['RoleARN'], dict) or \
                resource['Properties']['RoleARN'].keys() != set(['Ref']) or \
                not isinstance(resource['Properties']['RoleARN']['Ref'], str):
            raise ValueError('RoleARN must be a Ref')

        role_arn = original["templateParameterValues"][
                resource["Properties"]["RoleARN"]["Ref"]
                ]
        role_arn = {
                'RoleArn': 'arn:aws:iam::'
                           f'{resource["Properties"]["Principal"]}:role/'
                           f'{role_arn}',
                'RoleSessionName': 'cross_account_lambda'
                }

        peer = boto3.client('sts').assume_role(**role_arn)['Credentials']

        access_token = {
                'aws_access_key_id': peer['AccessKeyId'],
                'aws_secret_access_key': peer['SecretAccessKey'],
                'aws_session_token': peer['SessionToken'],
                }
        print(access_token)


def retrieve_cfn_export(event, wex, export):
    # Generate template import statement, however use generated value to
    # resolve endpoint addresses via route53resolver
    export_name = utilities.import_value(event, wex, export)
    export_name = export_name['Fn::ImportValue']

    for export in utilities.boto3_list('exports'):
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
            in utilities.boto3_list('resolver_endpoint_ip_addresses',
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
            for export in utilities.boto3_list('exports'):
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

    # Create one auto-association object per rule
    # NOTE: rule_id s the same across the accounts. However,
    # AWS documentation does not formally guarantee this.
    for principal in principals:
        for rule_id in shared:
            auto_associate_id = utilities.mk_id(
                    [
                        f'cr{kind}AutoAssociate',
                        region,
                        principal,
                        rule_id,
                        ]
                    )

            logger.debug(f'Auto-association id for {principal}/{rule_id}:'
                         f'{auto_associate_id}')

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
                            'Ref': 'CrossAccountRoleName'
                            },
                        'Principal': principal,
                        'RuleId': utilities.fn_get_att(rule_id,
                                                       'ResolverRuleId'),
                        },
                    'DependsOn': [
                        share_id,
                        rule_id
                        ]
                    }

    return {
            'requestId': event['requestId'],
            'status': 'SUCCESS',
            'fragment': event['fragment']
            }
