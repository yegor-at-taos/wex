#!/bin/bash -ex

aws --profile eu cloudformation create-stack \
    --stack-name transform \
    --template-body file://r53-rule.json \
    --parameters file://r53-data.json \
    --capabilities CAPABILITY_AUTO_EXPAND CAPABILITY_NAMED_IAM CAPABILITY_IAM
