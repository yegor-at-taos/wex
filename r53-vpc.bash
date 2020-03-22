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

exit 0

# Make bucket if it doesn't exist
if [[ $(aws --profile $profile --region $region s3api list-buckets \
    | jq ".Buckets[] | select(.Name | test(\"$bucket\"))" \
    | wc -l) -eq 0 ]]; then
    if [[ $region = 'us-east-1' ]]; then
        # this is workaround for the well-known bug in aws-cli
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

jq "$json_addr.Code.S3Bucket = \"$bucket\"" \
    | jq "$json_addr.Tags[0].LastUpdated = \"$(date)\"" r53-vpc.json > $json

if [[ $(aws --profile $profile --region $region cloudformation list-stacks \
    | jq ".StackSummaries[] | select(.StackName | test(\"$stack_name\"))" \
    | wc -l) -eq 0 ]]; then
    command='create'
else
    command='update'
fi

aws --profile $profile --region $region cloudformation $command-stack \
    --stack-name $stack_name --template-body file://$json \
    --capabilities CAPABILITY_IAM
