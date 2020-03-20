#!/bin/bash -ex

profile='eu'
region='us-west-2'
bucket='wex-scripts'
script='VpcTransformFunction'

temp=$script.zip

cleanup() {
    trap - EXIT
    rm -f $temp
}

trap cleanup EXIT

# Make bucket if it doesn't exist
if [[ $(aws --profile $profile --region $region s3api list-buckets \
    | jq ".Buckets[] | select(.Name | test(\"$bucket\"))" \
    | wc -l) -eq 0 ]]; then
    aws --profile $profile --region $region s3api create-bucket \
        --create-bucket-configuration '{"LocationConstraint": "us-west-2"}' \
        --acl authenticated-read --bucket $bucket
fi

./r53-vpc.py > $script.py; zip -9m $script.zip $script.py

aws --profile $profile --region $region s3 \
    cp $temp s3://$bucket/$temp

aws --profile $profile --region $region cloudformation update-stack \
    --stack-name wexRouteFiftyThreeMacro \
    --template-body file://r53-vpc.json \
    --capabilities CAPABILITY_IAM   
