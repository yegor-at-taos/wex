#!/bin/bash

. shell-utils.bash

stack_name="$account_name-$short_region-cfn-lambda-utilities-stk"
bucket="wex-account-default-scripts-$region"

json=$(remove_on_exit --suffix='.json')

cat > "$json" <<EOF
{
    "AWSTemplateFormatVersion": "2010-09-09",
    "Description": "WEX Inc., AWS Lambda tools (Functions, etc.)",
    "Resources": {
    },
    "Outputs": {
    }
}
EOF

# NOTE: Construct ARN for the IAM Role
# shellcheck disable=SC2045
for script in $(ls python); do  # note that 'noglob' is ON
    [[ ! $script =~ \.py$ || $script = 'utilities.py' ]] && continue

    function=${script%.py}

    zipfile=$(remove_on_exit --suffix='.zip')

    flake8 "python/$script" python/utilities.py

    zip -9jq "$zipfile" "python/$script" python/utilities.py

    aws --profile "wex-$profile" --region "$region" \
        s3 cp "$zipfile" "s3://$bucket/$function-$lambda_version.zip"

    aws --profile "wex-$profile" --region "$region" \
        s3api put-object-tagging \
        --bucket "$bucket" --key "$function-$lambda_version.zip" \
        --tagging "{ \"TagSet\": $(jq .Mappings.Wex.Tags "$json_template") }"

    fragment=$(remove_on_exit --suffix=.json)
    combined=$(remove_on_exit --suffix=.json)

    # Add Permissions object
    cat > "$fragment" <<EOF
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
        },
        "$function": {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "Code": {
                    "S3Bucket": { "Ref": "S3BucketName" },
                    "S3Key": ""
                },
                "FunctionName": "$function",
                "Handler": "$function.handler",
                "Runtime": "python3.7",
                "Timeout": "5",
                "Role": "arn:aws:iam::$profile:role/WexCloudFormationLambdaUtilitiesRole",
                "Role": {
                  "Fn::Join": [ ":", [
                    "arn", "aws", "iam", "",
                    { "Ref": "AWS::AccountId" },
                    {
                      "Fn::Join": [ "/", [
                          "role",
                          {
                            "Ref": $(jq .LambdaUtilitiesRole static_parameters.json)
                          }
                        ]
                      ]
                    }
                  ]
                }
              },
              "Tags": $(jq .Mappings.Wex.Tags "$json_template")
            }
        },
        "${function}Logs": {
            "Type" : "AWS::Logs::LogGroup",
            "Properties" : {
                "LogGroupName": {
                    "Fn::Join": [ "-", [ { "Ref": "AWS::StackName" }, "$function" ] ]
                },
                "RetentionInDays" : 7
            }
        }
    }
}
EOF
    jq -n 'reduce inputs as $i ({}; . * $i)' "$json" "$fragment" > "$combined"
    mv "$combined" "$json"

    if [[ $function =~ 'TemplateTransform' ]]; then
        # Add Transform object if FunctionName matches 'Transform'
        cat > "$fragment" <<EOF
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
        cat > "$fragment" <<EOF
{
    "Outputs": {
        "${function}": {
            "Description": "CFN: $function",
            "Value": {
                "Fn::GetAtt": [
                    "${function}",
                    "Arn"
                ]
            },
            "Export": {
                "Name": {
                    "Fn::Join": [ "-", [
                            { "Ref": "NamePrefix" },
                            "$(tr '[:upper:]' '[:lower:]' <<< "$function")",
                            "arn"
                        ]
                    ]
                }
            }
        }
    },
    "Parameters": {
        "LambdaVersion": {
          "Type": "String",
          "Description": "AWS Lambda Utilities Version"
        },
        "NamePrefix": {
          "Type": "String",
          "Description": "Stack prefix, eg. 'coreservices-prod-ue1'"
        }
    }
}
EOF
    fi
    jq -n 'reduce inputs as $i ({}; . * $i)' "$json" "$fragment" > "$combined"
    mv "$combined" "$json"
done

# WORKAROUND: 'update' won't pull Python from S3; delete and create again
while true; do
    command=$(create_or_update "$stack_name")
    [[ $command = 'create' ]] && break
    aws --profile "wex-$profile" --region "$region" \
        cloudformation delete-stack --stack-name "$stack_name"
done

aws --profile "wex-$profile" --region "$region" \
    cloudformation "$command-stack" \
    --tags "$(jq .Mappings.Wex.Tags "$json_template")" \
    --stack-name "$stack_name" --template-body "file://$json" \
    --parameters "[
        {
            \"ParameterKey\": \"StackPrefix\",
            \"ParameterValue\": \"$account_name-$short_region\"
        },
        {
            \"ParameterKey\": \"S3BucketName\",
            \"ParameterValue\": \"$bucket\"
        },
        {
            \"ParameterKey\": \"LambdaVersion\",
            \"ParameterValue\": \"$lambda_version\"
        }
    ]"

