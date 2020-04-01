#!/bin/bash

. shell-utils.bash

root="$account_name-cfn-endpoints"
stack_name="$root-$short_region-stk"

json=$(remove_on_exit --suffix='.json')
jq ".Transform = [\"CloudFormationTemplateTransformEndpointsMacro\"]
    | .Description = \"WEX Inc., AWS Route 53 Resolver Endpoints and SGs\"" \
    "$json_template" > "$json"

# Even though `Instantiate` is a required parameter, it is ignored
# by this particular stack; use 'Hosted'.
aws --profile "wex-$profile" --region "$region" \
    cloudformation "$(create_or_update "$stack_name")-stack" \
    --stack-name "$stack_name" --template-body "file://$json" \
    --parameters "ParameterKey=Instantiate,ParameterValue=Hosted" \
    --tags "$(jq .Mappings.Wex.Tags "$json_template")" \
    --capabilities CAPABILITY_AUTO_EXPAND
