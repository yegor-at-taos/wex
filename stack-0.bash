#!/bin/bash
set -o errexit -o pipefail -o nounset -o noglob

. shell-utils.bash

root="$account_name-lambda-utils-permissions"
json_source='json/lambda-utils-permissions.json'

json=$(mktemp -u --suffix='.json')

cleanup() {
    trap - EXIT
    rm -f *.zip $json $json.swap
}
trap cleanup EXIT

# Process 'json_source' -> 'json'
json_addr='.Resources.LambdaUtilsRole.Properties'
cat $json_source | \
    jq "$json_addr.Tags[0].Value = \"$(date --iso-8601=minutes)\"" > $json

stack="$root-$short_region-stk"

aws --profile wex-$profile --region $region \
    cloudformation $(create_or_update $stack)-stack \
    --stack-name $stack --template-body file://$json \
    --capabilities CAPABILITY_IAM
