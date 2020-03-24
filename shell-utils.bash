#!/bin/bash -ex

create_or_update() {
    # sleep until '..._IN_PROGRESS' status is gone
    while true; do
        aws --profile wex-$profile --region $region \
            cloudformation list-stacks > $json.swap

        count=$(cat $json.swap | jq "[.StackSummaries[] |
                select(.StackName == \"$1\")] | length")
        if [[ $count -eq 0 ]]; then
            echo 'create'
            return
        fi
        status=$(cat $json.swap | jq "[.StackSummaries[] |
                select(.StackName == \"$1\")][0].StackStatus")
        [[ ! $status =~ '_IN_PROGRESS' ]] && break
    done
    status=$(cat $json.swap | jq "[.StackSummaries[] |
            select(.StackName == \"$1\")][0].DeletionTime")
    if [[ $status = 'null' ]]; then
        echo 'update'
    else
        echo 'create'
    fi
}

account_name() {
    if [[ $1 = 'taos' ]]; then
        echo 'coreservices-mock'
        return
    fi
    data=$(cat shell-utils.text | sed \
        -e 's/\s*:\s*\w*$//' \
        -e 's/.*:[[:space:]]*//' \
        -e 's/^\([^[:space:]]*\)[[:space:]]*-[[:space:]]*/\1,/' \
        -e "/^$1/!d" \
        -e 's/[[:space:]]/-/g' | tr A-Z a-z)
    if [[ -z $data ]]; then
        echo Account not found: $1 1>&2
        exit 1
    fi
    name=$(sed -e 's/.*,//' <<< $data)
    if [[ -z $name ]]; then
        echo $1  # no name in Okta
    else
        echo $name
    fi
}

short_region() {
    sed -e 's/\(.\)\w*-/\1/g' <<< $1
}

if [[ $# = 2 ]]; then  # profile and region provided
    profile=$1
    region=$2
elif [[ $# = 1 && $1 = 'wex' ]]; then  # 'wex' shortcut
    profile='544308222195'
    region='us-east-1'
elif [[ $# = 1 && $1 = 'taos' ]]; then  # 'taos' shortcut
    profile='taos'
    region='us-west-2'
else
    echo "*  Usage error."
    echo "You should provide one of the following:"
    echo "   * account and region (544308222195 us-east-1)"
    echo "   * shortcut, ['wex'|'taos']"
    exit 1
fi

short_region=$(short_region $region)
account_name=$(account_name $profile)
if [[ $account_name = $profile ]]; then
    echo "No human-readable name for ($profile) found, using 'aws-' prefix" 1>&2
    account_name="aws-$account_name"
fi
