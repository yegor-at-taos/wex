#!/bin/bash

. shell-utils.bash

if [[ $region != 'global' ]]; then
    echo IAM Roles should use region 'global', not "$region".
    exit 1
fi

cat <<EOF
Stack name: Lambda Role stack [stack name will change during execution in prod]

Input parameters: Lambda role name
Output Parameters: Export Lambda role name (NOTE: not used)
EOF

if [[ $(aws --profile "wex-$profile" --region "us-east-1" \
    iam list-roles | jq ".Roles
        | map(select(.RoleName == \"$role_utilities\")) | length") -ne 0 ]]; then
    echo "IAM Role already exists (this is not an error, you can go on)"
    exit 0
fi

stack="$account_name-$region-cfn-lambda-permissions-stk"
json_source="json/lambda-utilities-role-regional.json"

json=$(remove_on_exit --suffix=".json")

json_address=$(jq -r '.Resources|keys[0]' "$json_source")
jq ".Resources.$json_address.Properties.Tags |= . +
    $(retrieve_tags) | .Resources.$json_address.Properties.RoleName =
        \"${role_utilities}\"" "$json_source" > "$json"

aws --profile "wex-$profile" --region "us-east-1" \
    cloudformation "$(create_or_update "$stack")-stack" \
    --stack-name "$stack" --template-body "file://$json" \
    --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
    --tags "$(retrieve_tags)" \
    --parameters "[
      {
        \"ParameterKey\": \"RoleName\",
        \"ParameterValue\": \"$role_utilities\"
      }
    ]"
