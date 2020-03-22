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

temp=$script.zip
json=$(mktemp)

cleanup() {
    trap - EXIT
    rm -f $temp $json
}

trap cleanup EXIT

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

# TODO: check if 'wexRouteFiftyThreeMacro' exists
jq ".Resources.VpcTransformFunction.Properties.Code.S3Bucket = \"$bucket\"" \
    r53-vpc.json > $json


aws --profile $profile --region $region cloudformation create-stack \
    --stack-name wexRouteFiftyThreeMacro \
    --template-body file://$json \
    --capabilities CAPABILITY_IAM
