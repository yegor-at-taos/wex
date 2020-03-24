#!/bin/bash

. shell-utils.bash

root="$account_name-cloudformation-lambda-utils-functions"
json_source='json/lambda-utils-objects.json'

json=$(mktemp -u --suffix='.json')
remove_on_exit $json

bucket="$root-$short_region-bkt"

if [[ $(aws --profile wex-$profile --region $region s3api list-buckets \
    | jq "[.Buckets[] | select(.Name == \"$bucket\")] | length") -eq 0 ]]; then
    # this is workaround for the well-known bug in aws-cli
    if [[ $region = 'us-east-1' ]]; then
        aws --profile wex-$profile --region $region s3api create-bucket \
            --acl authenticated-read --bucket $bucket
    else
        aws --profile wex-$profile --region $region s3api create-bucket \
            --create-bucket-configuration \
            "{\"LocationConstraint\": \"$region\"}" \
            --acl authenticated-read --bucket $bucket
    fi
fi

stack_name="$account_name-lambda-utils-functions-$short_region-stk"

cp $json_source $json

for script in $(ls python); do  # note that 'noglob' is ON
    flake8 $script  # errexit takes care of exit code

    function=$(sed -e 's/.*\///;s/\.py$//' <<< $script)

    zipfile="/tmp/$function.zip"
    remove_on_exit $zipfile

    zip -9j $zipfile python/$script

    aws --profile wex-$profile --region $region s3 cp $zipfile s3://$bucket

    fragment=$(mktemp -u --suffix=.json)
    remove_on_exit $fragment

    combined=$(mktemp -u --suffix=.json)
    remove_on_exit $combined

    # Add Permissions object
    cat > $fragment <<EOF
{
    "Resources": {
        "${function}Permissions": {
            "Type": "AWS::Lambda::Permission",
            "Properties": {
                "Action": "lambda:InvokeFunction",
                "FunctionName": {
                    "Fn::GetAtt": [
                        "${function}",
                        "Arn"
                    ]
                },
                "Principal": "cloudformation.amazonaws.com"
            }
        }
    }
}
EOF
    jq -n 'reduce inputs as $i ({}; . * $i)' $json $fragment > $combined
    mv $combined $json

    # Add Function object
    cat > $fragment <<EOF
{
    "Resources": {
        "$function": {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "Code": {
                    "S3Bucket": "$bucket",
                    "S3Key": "$function.zip"
                },
                "FunctionName": "$function",
                "Handler": "$function.handler",
                "Runtime": "python3.7",
                "Timeout": "5",
                "Role":  {
                    "Fn::ImportValue": "LambdaUtilsRole"
                },
                "Tags": [
                    {
                        "Key": "LastUpdatedTime",
                        "Value": "$(date --iso-8601=minutes)"
                    }
                ]
            }
        }
    }
}
EOF
    jq -n 'reduce inputs as $i ({}; . * $i)' $json $fragment > $combined
    mv $combined $json

    if [[ $function =~ 'TemplateTransform' ]]; then
        # Add Transform object if FunctionName matches 'Transform'
        cat > $fragment <<EOF
{
    "Resources": {
        "${function}Macro": {
            "Type": "AWS::CloudFormation::Macro",
            "Properties": {
                "Name": "${function}Macro",
                "FunctionName": {
                    "Fn::GetAtt": [
                        "${function}",
                        "Arn"
                    ]
                }
            }
        }
    }
}
EOF
    else
        # Export Function name if it's not a transform Macro
        cat > $fragment <<EOF
{
    "Outputs": {
        "${function}": {
            "Description": "Auto-generated: $function",
            "Value": {
                "Fn::GetAtt": [
                    "${function}",
                    "Arn"
                ]
            },
            "Export": {
                "Name": "$function-Arn"
            }
        }
    }
}
EOF
    fi
    jq -n 'reduce inputs as $i ({}; . * $i)' $json $fragment > $combined
    mv $combined $json
done

# WORKAROUND: 'update' won't pull Python from S3; delete and create again
while true; do
    command=$(create_or_update $stack_name)
    [[ $command = 'create' ]] && break
    aws --profile wex-$profile --region $region \
        cloudformation delete-stack --stack-name $stack_name
done

aws --profile wex-$profile --region $region \
    cloudformation $command-stack \
    --stack-name $stack_name --template-body file://$json
