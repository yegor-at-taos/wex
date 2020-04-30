#!/bin/bash

. shell-utils.bash

if [[ $region = 'global' ]]; then
    echo "This stack is regional; can't use pseudo-region 'global'"
    exit 1
fi

cat <<EOF
Stack name: Route54 resolver stack [stack name will change during execution in prod]
Input parmeters:
    Lambda transform macros stack name
    Number of IP’s to created for the route53 resolver for inbound, values 1,2,3
    Number of IP’s to created for the route53 resolver for outbound values 1,2,3
    Vpc stack name (where these resolvers will created)
Output parameters:
    Export Resolver id’s for inbound and outbound
    Export Resolver Ip’s for inbound and outbound
    Export number of Ip values parameter 
EOF

stack_name="$account_name-$short_region-cfn-endpoints-stk"

json=$(remove_on_exit --suffix='.json')

cp "$json_template" "$json"

fragment=$(remove_on_exit --suffix=.json)
combined=$(remove_on_exit --suffix=.json)

# Currently, you can use intrinsic functions in resource properties,
# metadata attributes, and update policy attributes.
#
# docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/intrinsic-function-reference.html
cat > "$fragment" <<EOF
{
  "Description": "WEX Inc., AWS Route 53 Resolver Endpoints and SGs",
  "Transform": [
    $(jq '.CFNEndpointsTransformMacro' "$static_parameters")
  ],
  "Parameters": {
    "LambdaStack": {
      "Type": "String",
      "Description": "Lambda Utilities stack name"
    },
    "MaxIpAddresses": {
      "Type": "Number",
      "Description": "Max. number of IP addresses to allocate per endpoint",
      "AllowedValues": [
        1,
        2,
        3
      ]
    }
  }
}
EOF
jq -n 'reduce inputs as $i ({}; . * $i)' \
    "$json" "$fragment" > "$combined"

jq ".Mappings.Wex.Infoblox.Regions |=
    with_entries(select(.key|test(\"default|$region\")))" \
        "$combined" > "$json"

# Even though `Instantiate` is a required parameter, it is ignored
# by this particular stack; use 'Hosted'.
aws --profile "wex-$profile" --region "$region" \
    cloudformation "$(create_or_update "$stack_name")-stack" \
    --stack-name "$stack_name" --template-body "file://$json" \
    --tags "$(retrieve_tags)" \
    --capabilities CAPABILITY_AUTO_EXPAND \
    --parameters "[
        {
            \"ParameterKey\": \"LambdaStack\",
            \"ParameterValue\": \"$wex_lob-$wex_environment-$short_region-lambda-utilities-stk\"
        },
        {
            \"ParameterKey\": \"MaxIpAddresses\",
            \"ParameterValue\": \"2\"
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
            \"ParameterValue\": \"AwsZones\"
        }
    ]"
