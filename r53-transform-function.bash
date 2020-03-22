#!/bin/bash -ex

if [[ $1 = 'wex' ]]; then
    profile='wex-544308222195'
    region='us-east-1'
else
    profile='eu'
    region='us-west-2'
fi

bucket="wex-scripts-cloudformation-$region"
script='VpcTransformFunction'
stack_name='wexRouteFiftyThreeMacro'
json_addr=".Resources.VpcTransformFunction.Properties"

temp=$script.zip
json=$(mktemp)

cleanup() {
    trap - EXIT
    rm -f $temp $json
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

./r53-vpc.py > $script.py; zip -9m $script.zip $script.py

aws --profile $profile --region $region s3 \
    cp $temp s3://$bucket/$temp

jq "$json_addr.Code.S3Bucket = \"$bucket\" |
    $json_addr.Tags[0].Value = \"$(date --iso-8601=minutes)\"" \
    r53-vpc.json > $json

# WORKAROUND: 'update' won't update the Lambda function from S3
while true; do
    command=$(create_or_update $stack_name)
    [[ $command = 'create' ]] && break
    aws --profile $profile --region $region \
        cloudformation delete-stack --stack-name $stack_name
done


aws --profile $profile --region $region cloudformation $command-stack \
    --stack-name $stack_name --template-body file://$json \
    --capabilities CAPABILITY_IAM
