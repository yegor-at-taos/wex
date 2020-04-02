#!/bin/bash

. shell-utils.bash

if [[ $(aws --profile "wex-$profile" --region "$region" \
    iam list-roles | jq ".Roles
        | map(select(.RoleName == \"$role_master\")) | length") -ne 0 ]]; then
    echo "IAM Role already exists (this is not an error, you can go on)"
    exit 0
fi

# We only need it in one region but let's keep the corporate naming scheme
stack="$account_name-$short_region-cfn-lambda-permissions-stk"

json=$(remove_on_exit --suffix=".json")

json_source="json/lambda-utilities-permissions.json"
json_address=$(jq '.Resources | keys
    | select("Wex.*Role")[0]' "$json_source" | sed -e 's/^"//;s/"$//')

jq ".Resources.$json_address.Properties.Tags |= . +
    $(jq .Mappings.Wex.Tags "$json_template")
    | .Resources.$json_address.Properties.RoleName =
        \"${role_master}\"" "$json_source" > "$json"

aws --profile "wex-$profile" --region "$region" \
    cloudformation "$(create_or_update "$stack")-stack" \
    --stack-name "$stack" --template-body "file://$json" \
    --tags "$(jq .Mappings.Wex.Tags "$json_template")" \
    --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM
