# wex

Prerequisite:
    - jq: Please install jq with `apt`. Under Ubuntu installing with `snap`
      gives some unexpected errors ("File not found" intermittently)
        # apt install jq

    - aws cli: Either `apt` or `snap` is OK.
        # apt install awscli
            or
        # snap install aws-cli

    - AWS credentials. Scripts assume that access credentials are in the form
      'wex-N' where N is AWS account id.
      E.g. `wex-544308222195` for "custodian-prod".

    - Hosted zones and their rescpective accounts exported from the XLS
      files. Each sheet should be exported to an individual file under
      the `infra/` named WEX-AWS-0.csv, WEX-AWS-1.csv, etc.

    - Unbound configurations dumped under the `infra/unbound`

    - Python3 installed; virtual environment is optional but recommended

    - Python3 requirements satidfied. `pip install -r requirements.txt`

[Optional] Generate and examine infrastructure template with the `csv-audit.py`
    ./csv-audit.py --generate | jq . > sample.json
    This gives you an opportunity to see if CloudFormation templates will
    contain correct data.
    For the testing purposes you can edit this file as `mock/infra-mock.json`.
    If present, it will be used instead of the generated one.

[Optional] Generate the list of accounts participated.
    `./csv-audit.py --accounts`
    Use this list to auto-generate ~/.aws/credentials with Okta AWS client.
    See `aws.bat` as an example.

Stack 0: Lambda functions IAM permissions.

        ./stack-0.bash <account> <stage> <region-name>

    Example ("custodian-prod"):
        ./stack-0.bash 544308222195 us-east-1

Stack 1: Lambda functions and macros.

        ./stack-1.bash <account> <region-name>

    Example ("custodian-prod"):
        ./stack-1.bash 544308222195 us-east-1

Stack 2: Endpoints and security groups (TBD)

        ./stack-2.bash <account> <region-name>

    Example ("custodian-prod"):
        ./stack-2.bash 544308222195 us-east-1
