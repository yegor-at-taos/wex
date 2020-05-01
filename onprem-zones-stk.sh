#!/bin/bash

. shell-utils.bash

declare -r kind='OnPremZones'

stack_name="$account_name-$target_environment-$short_region-cfn-r53-$( \
    tr '[:upper:]' '[:lower:]' <<< $kind)-stk"

json=$(remove_on_exit --suffix='.json')

cp 'json/cloudformation-template.json' "$json"

fragment=$(remove_on_exit --suffix=.json)
combined=$(remove_on_exit --suffix=.json)

cat > "$fragment" <<EOF
{
  "Description": "WEX Inc., AWS Route 53 Resolver $kind rules and shares",
  "Mappings": {
    "Wex": {
      "Tags": $(retrieve_tags),
      "$kind": $(jq .$kind "$static_parameters"),
      "Accounts": $(jq .Accounts "$static_parameters")
    }
  },
  "Parameters": {
    "CrossAccountRoleName": {
      "Type": "String",
      "Description": "Lambda Satellite IAM Role name"
    },
    "TargetEnvironment": {
      "Type": "String",
      "Description": "Wex Target Environment; stack tag"
    },
    "MaxRulesPerShare": {
      "Type": "Number",
      "Description": "Limit RuleId count per RAM Share",
      "Default": "50"
    }
  },
  "Transform": [
    $(jq '.CFNZonesTransformMacro' "$static_parameters")
  ]
}
EOF
jq -n 'reduce inputs as $i ({}; . * $i)' \
    "$json" "$fragment" > "$combined"


jq ".Mappings.Wex.Infoblox.Regions |=
    with_entries(select(.key|test(\"default|$region\"))) |
    .Mappings.Wex.Infoblox.Regions.default.VpcDni =
    $(jq .VpcDni "$static_parameters")" \
        "$combined" > "$json"

aws --profile "wex-$profile" --region "$region" \
    cloudformation "$(create_or_update "$stack_name")-stack" \
    --stack-name "$stack_name" --template-body "file://$json" \
    --tags "$(retrieve_tags)" \
    --capabilities CAPABILITY_AUTO_EXPAND \
    --parameters "[
        {
            \"ParameterKey\": \"CrossAccountRoleName\",
            \"ParameterValue\": \"$role_satellite\"
        },
        {
            \"ParameterKey\": \"Lob\",
            \"ParameterValue\": \"$wex_lob\"
        },
        {
            \"ParameterKey\": \"Environment\",
            \"ParameterValue\": \"$wex_environment\"
        },
        {
            \"ParameterKey\": \"TargetEnvironment\",
            \"ParameterValue\": \"$target_environment\"
        },
        {
            \"ParameterKey\": \"Instantiate\",
            \"ParameterValue\": \"$kind\"
        }
    ]"
