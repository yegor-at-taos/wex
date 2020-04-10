#!/bin/bash

. shell-utils.bash

# Even though Roles are global we're creating one Role per region so we
# can import Role ARN from the regional stack.
stack="$account_name-$short_region-cfn-lambda-permissions-stk"

json=$(remove_on_exit --suffix=".json")

json_source="json/lambda-utilities-permissions.json"

json_address=$(jq '.Resources|keys[0]' "$json_source")
jq ".Resources.$json_address.Properties.Tags |= . +
        $(jq .Mappings.Wex.Tags "$json_template")" "$json_source" > "$json"

aws --profile "wex-$profile" --region "$region" \
    cloudformation "$(create_or_update "$stack")-stack" \
    --stack-name "$stack" --template-body "file://$json" \
    --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
    --parameters "[
        {
            \"ParameterKey\": \"RoleName\",
            \"ParameterValue\": $(jq .LambdaUtilitiesRole static_parameters.json)
        }
    ]"
