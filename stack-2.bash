#!/bin/bash

. shell-utils.bash

json_template=$(remove_on_exit --suffix='.json')

if [[ -f 'mock/infra-mock.json' ]]; then
     jq . 'mock/infra-mock.json' > $json_template
else
    ./csv-audit.py --generate > $json_template
fi

root="$account_name-cloudformation-endpoints-sgs"
stack_name="$root-$short_region-stk"

json=$(remove_on_exit --suffix='.json')
jq ".Transform = [\"CloudFormationTemplateTransformEndpointsMacro\"]
    | .Description = \"WEX Inc., AWS Route 53 Resolver Endpoints and SGs\"" \
    $json_template > $json

cp $json foo.json

aws --profile wex-$profile --region $region \
    cloudformation $(create_or_update $stack_name)-stack \
    --stack-name $stack_name --template-body file://$json \
    --capabilities CAPABILITY_AUTO_EXPAND
