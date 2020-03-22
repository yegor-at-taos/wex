#!/bin/bash

create_or_update() {
    # sleep until '..._IN_PROGRESS' status is gone
    while true; do
        status=$(aws --profile $profile --region $region \
            cloudformation list-stacks \
            | jq "[.StackSummaries[] |
                select(.StackName == \"$1\")][0].StackStatus")
            [[ ! $status =~ '_IN_PROGRESS' ]] && break
    done
    status=$(aws --profile $profile --region $region cloudformation list-stacks \
        | jq "[.StackSummaries[] | select(.StackName == \"$1\")][0].DeletionTime")
    if [[ $status = 'null' ]]; then
        echo 'update'
    else
        echo 'create'
    fi
}
