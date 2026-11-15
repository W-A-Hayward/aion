# IAM policies

Region `us-east-1`, account `339713040194`, bucket `cascade-s3-bucket`.

For each role there are two files:

- `<role>.json`: the inline permissions policy (paste into IAM > Roles > role > Add permissions > Create inline policy > JSON).
- `<role>.trust.json`: the trust policy (paste into the role's Trust relationships tab).

Lambda roles trust `lambda.amazonaws.com`. `cascade-agent-role` trusts `bedrock.amazonaws.com`, restricted by `aws:SourceAccount`.

## Placeholders to replace

`cascade-agent-role.json` contains two IDs that do not exist yet. Replace them after creating the resources:

- `KNOWLEDGE_BASE_ID` (knowledge base ARN)
- `GUARDRAIL_ID` (guardrail ARN)

## Notes

- The Bedrock console can create the agent service role automatically. That is the recommended path; use `cascade-agent-role*.json` only if you create the role by hand.
- None of these policies grants CloudWatch Logs access. Attach the AWS managed policy `AWSLambdaBasicExecutionRole` to the four Lambda roles so they can write logs.

## Wildcard resources (JSON has no comments, so they are explained here)

No action contains a wildcard. These resources do:

- `arn:aws:glue:us-east-1:339713040194:table/cascade/*`: the tables in the `cascade` database. Glue evaluates `GetTables` and `GetPartitions` against table ARNs, and the tables are not known up front.
- `arn:aws:bedrock:us-east-1:339713040194:agent-alias/*`: the agent id and alias id are created later in the console and are not known yet.
- `arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-5-5*`: the region is `*` because the global inference profile routes requests to other regions. Foundation-model ARNs have no account id. The trailing `*` covers model version suffixes.
- `.../processed/*`, `.../athena-results/*`, `.../traces/*`: S3 key prefixes, scoped to one prefix each.
- `s3:ListBucket` condition `processed/*`, `athena-results/*`: limits listing to those prefixes.

## Deviations from the request

- `s3:GetBucketLocation` is a bucket-level action, so its resource is the bucket ARN, not `athena-results/*`.
- `s3:ListBucket` on the tools role also allows the `athena-results/` prefix, because Athena lists the results location.
