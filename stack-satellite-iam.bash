#!/bin/bash

. shell-utils.bash

root="$account_name-cfn-satellite-permissions"
stack="$root-$short_region-stk"

json=$(remove_on_exit --suffix='.json')

# Process 'json_source' -> 'json'
json_source='json/satellite-permissions.json'
json_address=$(jq '."Resources" | keys
    | select("Wex.*Role")[0]' "$json_source")

jq ".Resources.$json_address.Properties.Tags |= . +
        $(jq .Mappings.Wex.Tags "$json_template")" \
        "$json_source" > "$json"

aws --profile "wex-$profile" --region "$region" \
    cloudformation "$(create_or_update "$stack")-stack" \
    --stack-name "$stack" --template-body "file://$json" \
    --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM
