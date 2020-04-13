#!/bin/bash

. shell-utils.bash

if [[ $region = 'global' ]]; then
    echo "This stack is regional; can't use pseudo-region 'global'"
    exit 1
fi

cat <<EOF
Stack name: Lambda Macro stack [stack name will change during execution in prod]
Input Parameters:
    Lambda Role Name (not stack name)
    Lambda Version
Output parameters: 
    Export lambda Arn for route53 resolvers and Transform resource name
    Export lambda Arn for Onprem zones and Transform resource name
    Export lambda Arn for Hosted zones and Transform resource name
EOF

stack_name="$account_name-$short_region-cfn-lambda-utilities-stk"
bucket="$(jq -r '.S3BucketName' static_parameters.json)"

json=$(remove_on_exit --suffix='.json')

fragment=$(remove_on_exit --suffix=.json)
combined=$(remove_on_exit --suffix=.json)

# IAM Role fragment
fragment_iam_role() {
cat <<EOF
{
  "Fn::Join": [
    ":",
    [
      "arn",
      "aws",
      "iam",
      "",
      {
        "Ref": "AWS::AccountId"
      },
      {
        "Fn::Join": [
          "/",
          [
            "role",
            {
              "Ref": "RoleName"
            }
          ]
        ]
      }
    ]
  ]
}
EOF
}

fragment_log_group_name() {
cat <<EOF
{
  "Fn::Join": [
    "-",
    [
      {
        "Ref": "AWS::StackName"
      },
      "$1"
    ]
  ]
}
EOF
}

cat > "$json" <<EOF
{
    "AWSTemplateFormatVersion": "2010-09-09",
    "Description": "WEX Inc., AWS Lambda tools (Functions, etc.)"
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
        s3 cp "$zipfile" "s3://$bucket-$region/$function.$lambda_version.zip"

    aws --profile "wex-$profile" --region "$region" \
        s3api put-object-tagging \
        --bucket "$bucket-$region" --key "$function.$lambda_version.zip" \
        --tagging "{\"TagSet\": $(retrieve_tags)}"

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
          "S3Bucket": {
            "Fn::Join": [
              "-",
              [
                {
                  "Ref": "S3BucketName"
                },
                {
                  "Ref": "AWS::Region"
                }
              ]
            ]
          },
          "S3Key": {
            "Fn::Join": [
              ".",
              [
                "$function",
                {
                  "Ref": "LambdaVersion"
                },
                "zip"
              ]
            ]
          }
        },
        "FunctionName": "$function",
        "Handler": "$function.handler",
        "Runtime": "python3.7",
        "Timeout": "5",
        "Role": $(fragment_iam_role),
        "Tags": $(retrieve_tags)
      }
    },
    "${function}Logs": {
      "Type": "AWS::Logs::LogGroup",
      "Properties": {
        "LogGroupName": $(fragment_log_group_name "$function"),
        "RetentionInDays": 7
      }
    }
  }
}
EOF
    jq -n 'reduce inputs as $i ({}; . * $i)' "$json" "$fragment" > "$combined"
    mv "$combined" "$json"

    # Add Macro if FunctionName matches 'Transform'
    if [[ $function =~ 'Transform' ]]; then
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
        },
        "LogGroupName": $(fragment_log_group_name "$function")
      }
    }
  }
}
EOF
    fi
    jq -n 'reduce inputs as $i ({}; . * $i)' "$json" "$fragment" > "$combined"
    mv "$combined" "$json"

    # Export Function name
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
          "Fn::Join": [
            "-",
            [
              {
                "Ref": "AWS::StackName"
              },
              "$(tr '[:upper:]' '[:lower:]' <<< "$function")",
              "arn"
            ]
          ]
        }
      }
    }
  }
}
EOF
    jq -n 'reduce inputs as $i ({}; . * $i)' "$json" "$fragment" > "$combined"
    mv "$combined" "$json"
done

# Append Parameters
cat > "$fragment" <<EOF
{
  "Parameters": {
    "RoleName": {
      "Type": "String",
      "Description": "AWS IAM Role name; this is global and can't be derived"
    },
    "LambdaVersion": {
      "Type": "String",
      "Description": "AWS Lambda Utilities Version"
    },
    "Lob": {
      "Type": "String",
      "Description": "WEX Inc., Line of business; eg. 'coreservices'"
    },
    "Environment": {
      "Type": "String",
      "Description": "WEX Inc., environment; eg. 'prod'"
    },
    "S3BucketName": {
      "Type": "String",
      "Description": "AWS S3BucketName"
    }
  }
}
EOF
jq -n 'reduce inputs as $i ({}; . * $i)' "$json" "$fragment" > "$combined"
mv "$combined" "$json"

# WORKAROUND: 'update' won't pull Python from S3; delete and create again
while true; do
    command=$(create_or_update "$stack_name")
    [[ $command = 'create' ]] && break
    aws --profile "wex-$profile" --region "$region" \
        cloudformation delete-stack --stack-name "$stack_name"
done

aws --profile "wex-$profile" --region "$region" \
    cloudformation "$command-stack" \
    --tags "$(retrieve_tags)" \
    --stack-name "$stack_name" --template-body "file://$json" \
    --parameters "[
        {
            \"ParameterKey\": \"Lob\",
            \"ParameterValue\": \"$wex_lob\"
        },
        {
            \"ParameterKey\": \"Environment\",
            \"ParameterValue\": \"$wex_environment\"
        },
        {
            \"ParameterKey\": \"RoleName\",
            \"ParameterValue\": $(jq '.LambdaUtilitiesRole' static_parameters.json)
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
