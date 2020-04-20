#!/bin/bash

. shell-utils.bash

declare -r kind='AwsZones'

stack_name="$account_name-$short_region-cfn-r53-$(tr '[:upper:]' '[:lower:]' \
    <<< $kind)-stk"

json=$(remove_on_exit --suffix='.json')

./csv-audit.py --generate "$kind" --region "$region" > "$json"

fragment=$(remove_on_exit --suffix=.json)
combined=$(remove_on_exit --suffix=.json)

cat > "$fragment" <<EOF
{
  "Description": "WEX Inc., AWS Route 53 Resolver $kind rules and shares",
  "Mappings": {
    "Wex": {
      "Tags": $(retrieve_tags)
    }
  },
  "Parameters": {
    "CrossAccountRoleName": {
      "Type": "String",
      "Description": "Lambda Satellite IAM Role name"
    }
  },
  "Transform": [
    $(jq '.CFNZonesTransformMacro' static_parameters.json)
  ]
}
EOF
jq -n 'reduce inputs as $i ({}; . * $i)' "$json" "$fragment" > "$combined"
mv "$combined" "$json"

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
            \"ParameterKey\": \"Instantiate\",
            \"ParameterValue\": \"$kind\"
        }
    ]"
