#!/bin/bash

. shell-utils.bash

root="$account_name-cloudformation-lambda-utils-functions"
stack_name="$root-$short_region-stk"

json_source='json/lambda-utils-objects.json'

json=$(remove_on_exit --suffix='.json')

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

cp $json_source $json

# MAGIC: Pull the default Tags from the template
default_tags=$(jq ".Mappings.Wex.Tags | . + [{
    \"Key\": \"LastUpdatedTime\",
    \"Value\": \"$(date --iso-8601=minutes)\"
}]" $json_template)

for script in $(ls python); do  # note that 'noglob' is ON
    python=$(remove_on_exit --suffix='.py')

    if [[ ! $script =~ '.py' ]]; then
        continue
    elif [[ $script =~ 'CloudFormationTemplateTransform' ]]; then
        ed -s <<EOF
r python/$script
/^def handler/-1r python/python.include
w $python
EOF
    else
        cp python/$script $python
    fi

    flake8 $python

    function=${script%.py}

    zipfile=$(remove_on_exit --suffix='.zip')

    # file inside the container must be named after the function name + .py
    mv $python /tmp/$script; zip -9jm $zipfile /tmp/$script

    # the container could be named anything; see S3Key in Resources
    aws --profile wex-$profile --region $region \
        s3 cp $zipfile s3://$bucket/$function.zip

    fragment=$(remove_on_exit --suffix=.json)
    combined=$(remove_on_exit --suffix=.json)

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
                "Tags": $default_tags
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
                "Name": {
                    "Fn::Join": [
                        ":", [ "$function", "Arn" ]
                    ]
                }
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
