#!/bin/bash
set -o errexit -o pipefail -o nounset -o noglob

if [[ $(uname -s) = "Linux" ]]; then
    remove_on_exit_file=$(mktemp -u --suffix='.text')
else
    remove_on_exit_file=$(mktemp -u) # decoration is optional
fi

remove_on_exit() {
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
trap cleanup EXIT

create_or_update() {
    # sleep until '..._IN_PROGRESS' status is gone
    while true; do
        local temp

        temp=$(remove_on_exit --suffix=".json")

        aws --profile "wex-$profile" --region "$region" \
            cloudformation list-stacks > "$temp"

        count=$(jq "[.StackSummaries[] | select(.StackName == \"$1\")]
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
    if [[ $1 = 'taos' ]]; then
        echo 'coreservices-mock'
    elif [[ $1 = 'taos-satellite' ]]; then
        echo 'coreservices-mock-satellite'
    else
        name=$(jq ".[\"$1\"]" shell-utils.json)
        if [[ $name = 'null' ]]; then
            echo "Account not found: $1"  # no name in Okta
            exit 1
        else
            echo "${name//\"/}"
        fi
    fi
}

short_region() {
    # shellcheck disable=SC2001
    sed -e 's/\(.\)[^-]*-/\1/g' <<< "$1"
}

if [[ $# = 2 ]]; then  # profile and region provided
    profile=$1
    region=$2
elif [[ $# = 1 && $1 = 'wex' ]]; then
    profile='544308222195'
    region='us-east-1'
elif [[ $# = 1 && $1 = 'taos' ]]; then
    profile=$1
    region='us-east-1'
elif [[ $# = 1 && $1 = 'taos-satellite' ]]; then
    profile=$1
    region='us-east-1'
else
    echo "*  Usage error."
    echo "You should provide one of the following:"
    echo "   * account and region (544308222195 us-east-1)"
    echo "   * shortcut, ['wex'|'taos']"
    exit 1
fi

short_region=$(short_region $region)
# shellcheck disable=SC2034
upper_region=$(tr '[:lower:]' '[:upper:]' <<< "$short_region")

account_name=$(account_name "$profile")
if [[ $account_name = "$profile" ]]; then
    echo "No human-readable name for ($profile) found, using 'aws-' prefix" 1>&2
    account_name="aws-$account_name"
fi

json_template=$(remove_on_exit --suffix='.json')

if [[ -f 'mock/infra-mock.json' ]]; then
     jq . 'mock/infra-mock.json' > "$json_template"
else
    ./csv-audit.py --generate > "$json_template"
fi
