#!/bin/bash

. shell-utils.bash

root="$account_name-cloudformation-lambda-utils-permissions"
stack="$root-$short_region-stk"

json=$(remove_on_exit --suffix='.json')

# Process 'json_source' -> 'json'
json_source='json/lambda-utils-permissions.json'

# MAGIC: add LastUpdatedTime and pull the default Tags from the template
jq ".Resources.LambdaUtilsRole.Properties.Tags |= . +
        $(jq .Mappings.Wex.Tags $json_template) |
    .Resources.LambdaUtilsRole.Properties.Tags[0].Value =
        \"$(date --iso-8601=minutes)\"" $json_source > $json

aws --profile wex-$profile --region $region \
    cloudformation $(create_or_update $stack)-stack \
    --stack-name $stack --template-body file://$json \
    --capabilities CAPABILITY_IAM
