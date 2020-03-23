#!/bin/bash -ex

if [[ $1 = 'wex' ]]; then
    profile='wex-544308222195'
    region='us-east-1'
else
    profile='eu'
    region='us-west-2'
fi

prereq_name="wexRouteFiftyThreeMacro"
stack_name="wex-cloudformation-route53-stack-$region"

json=$(mktemp)

cleanup() {
    trap - EXIT
    rm -f $json
}

trap cleanup EXIT

. create-or-update.bash

if [[ -f stack-mock.json ]]; then
    cp stack-mock.json $json
else
    ./csv-audit.py --generate > $json
fi

if [[ $(aws --profile $profile --region $region cloudformation list-stacks \
    | jq "[.StackSummaries[]
        | select(.StackName == \"$prereq_name\")] | length") -eq 0 ]]; then
    echo Required Transform stack does not exist, please create it first.
    exit 1
fi

command=$(create_or_update $stack_name)

aws --profile $profile --region $region cloudformation $command-stack \
    --stack-name $stack_name --template-body file://$json \
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND
