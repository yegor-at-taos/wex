#!/bin/bash

. shell-utils.bash

root="$account_name-cfn-l-perms"
# Even though Roles are global we're creating one Role per region so we
# can import Role ARN from the regional stack.
stack="$root-$short_region-stk"

json=$(remove_on_exit --suffix=".json")

json_source="json/lambda-utilities-permissions.json"
json_address=$(jq '."Resources" | keys | select("Wex.*Role")[0]' "$json_source")
# shellcheck disable=SC2001
json_phys_name=$(sed -e "s/\"$/$upper_region\"/" <<< "$json_address")

jq ".Resources.$json_address.Properties.RoleName = $json_phys_name |
    .Resources.$json_address.Properties.Tags |= . +
        $(jq .Mappings.Wex.Tags "$json_template")" "$json_source" > "$json"

aws --profile "wex-$profile" --region "$region" \
    cloudformation "$(create_or_update "$stack")-stack" \
    --stack-name "$stack" --template-body "file://$json" \
    --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM
