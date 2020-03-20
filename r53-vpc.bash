#!/bin/bash -ex

profile='eu'
region='us-west-2'
bucket='wex-scripts'
script='VpcTransformFunction'

temp=$(mktemp)

cleanup() {
    trap - EXIT
    rm -f $temp
}

trap cleanup EXIT

# Make bucket if it is not already there
if [[ $(aws --profile $profile --region $region s3api list-buckets \
    | jq ".Buckets[] | select(.Name | test(\"$bucket\"))" \
    | wc -l) -eq 0 ]]; then
    aws --profile $profile --region $region s3api create-bucket \
        --create-bucket-configuration '{"LocationConstraint": "us-west-2"}' \
        --acl authenticated-read --bucket $bucket
fi

./r53-vpc.py > $temp

aws --profile $profile --region $region s3 \
    cp $temp s3://$bucket/$script.py
