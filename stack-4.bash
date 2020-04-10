#!/bin/bash

. shell-utils.bash

declare -r kind='OnPremZones'

stack_name="$account_name-$short_region-cfn-r53-$(tr '[:upper:]' '[:lower:]' \
    <<< $kind)-stk"

json=$(remove_on_exit --suffix='.json')
./csv-audit.py --generate "$kind" --region "$region" | \
    jq ".Transform = [\"CFNZonesTransformMacro\"] |
        .Description =
        \"WEX Inc., AWS Route 53 Resolver $kind rules and shares\"" > "$json"

aws --profile "wex-$profile" --region "$region" \
    cloudformation "$(create_or_update "$stack_name")-stack" \
    --stack-name "$stack_name" --template-body "file://$json" \
    --tags "$(jq .Mappings.Wex.Tags "$json_template")" \
    --capabilities CAPABILITY_AUTO_EXPAND \
    --on-failure DO_NOTHING \
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
            \"ParameterValue\": \"$kind\"
        }
    ]"
