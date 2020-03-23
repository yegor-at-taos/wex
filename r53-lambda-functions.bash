#!/bin/bash -ex

if [[ $1 = 'wex' ]]; then
    profile='wex-544308222195'
    region='us-east-1'
else
    profile='eu'
    region='us-west-2'
fi

bucket="wex-scripts-cloudformation-$region"
stack_name='wexRouteFiftyThreeMacro'
json_source='r53-lambda-functions.json'


json=$(mktemp -u --suffix='.json')

cleanup() {
    trap - EXIT
    rm -f *.zip $json $json.swap
}

trap cleanup EXIT

. create-or-update.bash

if [[ $(aws --profile $profile --region $region s3api list-buckets \
    | jq "[.Buckets[] | select(.Name == \"$bucket\")] | length") -eq 0 ]]; then
    # this is workaround for the well-known bug in aws-cli
    if [[ $region = 'us-east-1' ]]; then
        aws --profile $profile --region $region s3api create-bucket \
            --acl authenticated-read --bucket $bucket
    else
        aws --profile $profile --region $region s3api create-bucket \
            --create-bucket-configuration \
            "{\"LocationConstraint\": \"$region\"}" \
            --acl authenticated-read --bucket $bucket
    fi
fi

cp $json_source $json

for script in VpcAutoAcceptFunction VpcTransformFunction; do
    flake8 $script.py

    if [[ ! $? ]]; then
        echo Flake8 returns an error\; please fix your Python code.
        exit 1
    fi

    zip -9 $script.zip $script.py

    aws --profile $profile --region $region s3 \
        cp $script.zip s3://$bucket

    json_addr=".Resources.$script.Properties"

    cp $json $json.swap ; sync ; ls -l $json.swap

    cat $json.swap | jq "$json_addr.Code.S3Bucket = \"$bucket\" |
        $json_addr.Tags[0].Value = \"$(date --iso-8601=minutes)\"" > $json
done

# WORKAROUND: 'update' won't update the S3 Lambda function
while true; do
    command=$(create_or_update $stack_name)
    [[ $command = 'create' ]] && break
    aws --profile $profile --region $region \
        cloudformation delete-stack --stack-name $stack_name
done


aws --profile $profile --region $region cloudformation $command-stack \
    --stack-name $stack_name --template-body file://$json \
    --capabilities CAPABILITY_IAM
