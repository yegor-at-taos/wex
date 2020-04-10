#!/bin/bash

. shell-utils.bash

stack_name="$account_name-$short_region-cfn-endpoints-stk"

json=$(remove_on_exit --suffix='.json')
jq ".Transform = [\"CFNEndpointsTransformMacro\"]
    | .Description = \"WEX Inc., AWS Route 53 Resolver Endpoints and SGs\"" \
    "$json_template" > "$json"

# Even though `Instantiate` is a required parameter, it is ignored
# by this particular stack; use 'Hosted'.
aws --profile "wex-$profile" --region "$region" \
    cloudformation "$(create_or_update "$stack_name")-stack" \
    --stack-name "$stack_name" --template-body "file://$json" \
    --tags "$(jq .Mappings.Wex.Tags "$json_template")" \
    --capabilities CAPABILITY_AUTO_EXPAND \
    --parameters "[
        {
            \"ParameterKey\": \"Lob\",
            \"ParameterValue\": \"$wex_lob\"
        },
        {
            \"ParameterKey\": \"Environment\",
            \"ParameterValue\": \"$wex_environment\"
        },
        {
            \"ParameterKey\": \"Instantiate\",
            \"ParameterValue\": \"Hosted\"
        }
    ]"
