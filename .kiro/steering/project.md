# cascade
- Python 3.12. Lambdas: standard library + boto3 only, entry point app.lambda_handler.
- Always follow docs/data_contract.md (names, tables, tickers). Never invent names.
- Region us-east-1, bucket cascade-s3-bucket, prefix cascade- for every AWS resource.
- Deployed by pasting in the AWS console: no SAM, CDK, Serverless or frameworks.
- Don't run notebooks or call AWS from this machine; only run pytest on synthetic data.
- Edit only the files the prompt names.