#!/bin/bash
set -o errexit -o pipefail -o nounset -o noglob

remove_on_exit() {
    local file

    if [[ $(uname -s) = "Linux" ]]; then
        file=$(mktemp -u "$@")
    else
        file=$(mktemp -u) # decoration is optional
    fi
    echo "$file" >> "$remove_on_exit_file"
    echo "$file"
}

cleanup() {
    trap - EXIT
    # shellcheck disable=SC2046
    rm -f $(cat "$remove_on_exit_file")
}

create_or_update() {
    # sleep until '..._IN_PROGRESS' status is gone
    local temp_region=$region \
        && [[ $region = 'global' ]] && temp_region="us-east-1"
    while true; do
        local temp count status
        temp=$(remove_on_exit --suffix=".json")

        aws --profile "wex-$profile" --region "$temp_region" \
            cloudformation list-stacks > "$temp"

        count=$(jq "[.StackSummaries[]
            | select(.StackName == \"$1\")]
            | length" "$temp")

        if [[ $count -eq 0 ]]; then
            echo 'create'
            return  # object never existed, no record found
        fi

        status=$(jq "[.StackSummaries[]
            | select(.StackName == \"$1\")][0].StackStatus" "$temp")

        [[ ! $status =~ '_IN_PROGRESS' ]] && break  # object is stable

        sleep 3  # give AWS some time
    done

    status=$(jq "[.StackSummaries[] |
            select(.StackName == \"$1\")][0].DeletionTime" "$temp")

    if [[ $status = 'null' ]]; then
        echo 'update'  # no 'DeletionTime'; update an existing object
    else
        echo 'create'  # 'DeletionTime' present; create a new one
    fi
}

account_name() {
    if [[ $1 = '672442290193' ]]; then  # Taos test AWS account
        echo 'mock-prod'
    elif [[ $1 = '265468622424' ]]; then  # Yegor's test AWS account
        echo 'mock-stage'
    else
        local name
        name=$(jq ".[\"$1\"]" shell-utils.json)
        if [[ $name = 'null' ]]; then
            echo "Account not found: $1"  # no name in Okta
            exit 1
        else
            echo "${name//\"/}"
        fi
    fi
}

retrieve_tags() {
    jq "[ .Mappings.Wex.Tags[] |
        select(.Key == \"Lob\").Value = \"$wex_lob\" |
        select(.Key == \"Environment\").Value = \"$wex_environment\"
            ]" "$json_template"
}

fn_join() {
    # Fn::Join $2, $3, etc with $1 as a separator
    local separator=$1
    shift

    local fn_join_text=""

    local component
    for component in "$@"; do
        fn_join_text="$fn_join_text,\"$component\""
    done

    echo "{\"Fn::Join\":[\"$separator\",[${fn_join_text#,}]]}"
}

##### Execution starts here
if [[ $(uname -s) = "Linux" ]]; then
    readonly remove_on_exit_file=$(mktemp -u --suffix='.text')
else
    readonly remove_on_exit_file=$(mktemp -u) # decoration is optional
fi
echo "$remove_on_exit_file" >> "$remove_on_exit_file"

trap cleanup EXIT

while (( $# )); do
    case "$1" in
        -a|--aws-account)
            readonly profile="$2"
            shift 2
            ;;
        -r|--region)
            readonly region="$2"
            shift 2
            ;;
        -l|--lambda-version)
            readonly lambda_version="$2"
            shift 2
            ;;
        *)
            echo "Usage: $0 -a|--aws-account account"
            echo "          -r|--region region"
            echo "          -l|--lambda-version version"
            exit 1
            ;;
    esac
done

if [[ $region == 'global' ]]; then
    readonly short_region='glb'
    readonly upper_region='GLB'
else
    # shellcheck disable=SC2001
    readonly short_region=$(sed -e 's/\(.\)[^-]*-/\1/g' <<< "$region")
    readonly upper_region=$(tr '[:lower:]' '[:upper:]' <<< "$short_region")
fi
readonly account_name=$(account_name "$profile")
readonly json_template='json/cloudformation-template.json'
readonly role_utilities=$(jq -r '.LambdaUtilitiesRole' static_parameters.json)
readonly role_satellite=$(jq -r '.LambdaSatelliteRole' static_parameters.json)

readonly wex_lob=${account_name%-?*}
readonly wex_environment=${account_name#?*-}

# shellcheck disable=SC2034
readonly \
    account_name \
    role_utilities \
    role_satellite \
    lambda_version \
    json_template \
    short_region \
    upper_region \
    remove_on_exit_file
