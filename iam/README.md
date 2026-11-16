# IAM policies

Region `us-east-1`, account `339713040194`, bucket `cascade-s3-bucket`. The full deployment order is in
[docs/infrastructure.md](../docs/infrastructure.md).

For each role there are two files:

- `<role>.json`: the inline permissions policy (paste into IAM > Roles > role > Add permissions > Create inline policy > JSON).
- `<role>.trust.json`: the trust policy (paste into the role's Trust relationships tab).

| Role | Files | Trusted by | Used by |
|---|---|---|---|
| `cascade-tools-lambda` | `cascade-tools-lambda*.json` | `lambda.amazonaws.com` | Lambda `cascade-tools` (Athena reads for the agent) |
| `cascade-research-lambda` | `cascade-research-lambda*.json` | `lambda.amazonaws.com` | Lambda `cascade-research` (`GET /research`, same read-only Athena access) |
| `cascade-submit-lambda` | `cascade-submit-lambda*.json` | `lambda.amazonaws.com` | Lambda `cascade-submit` (job rows, rate-limit counters, SQS send) |
| `cascade-status-lambda` | `cascade-status-lambda*.json` | `lambda.amazonaws.com` | Lambda `cascade-status` |
| `cascade-worker-lambda` | `cascade-worker-lambda*.json` | `lambda.amazonaws.com` | Lambda `cascade-worker` (SQS → AgentCore → DynamoDB + S3 trace) |
| `cascade-userdata-lambda` | `cascade-userdata-lambda*.json` | `lambda.amazonaws.com` | Lambda `cascade-userdata` (each signed-in user's profile, portfolio and conversations in `cascade-users`) |
| `cascade-presignup-lambda` | `cascade-presignup-lambda.trust.json` | `lambda.amazonaws.com` | Lambda `cascade-presignup` (Cognito pre sign-up trigger; needs no permissions beyond `AWSLambdaBasicExecutionRole` logs) |
| `cascade-agentcore-runtime` | `cascade-agentcore-runtime*.json` | `bedrock-agentcore.amazonaws.com` | The AgentCore runtime that hosts `agent/agent.py` |
| `cascade-agent-role` | `cascade-agent-role*.json` | `bedrock.amazonaws.com` | **Legacy, unused.** For the classic Bedrock Agent (`cascade-agent`, alias `live`). The worker calls AgentCore, not a Bedrock Agent alias. Keep only if you still run the classic agent. |

## Placeholders to replace

`cascade-agentcore-runtime.json` (and the legacy `cascade-agent-role.json`) contain IDs that do not exist until the
resources are created. Replace them afterwards:

- `KNOWLEDGE_BASE_ID`: the `cascade-evidence` knowledge base ID.
- `GUARDRAIL_ID`: the `cascade-guardrail` ID. Delete the `Guardrail` statement if you don't use one.

`cascade-worker-lambda.json` names one specific runtime (`runtime/agent-uciA60FqQs`). If you create a new runtime,
replace that ID with the new runtime's ID (the end of `AGENT_RUNTIME_ARN`).

## Notes

- The AgentCore console can create the runtime role automatically. If you use that, compare it with
  `cascade-agentcore-runtime.json` and add what it lacks: the agent needs `lambda:InvokeFunction` on `cascade-tools`,
  `s3:GetObject` on `prompts/agent_instructions.md` and `bedrock:Retrieve` on the knowledge base, which the
  default role does not include.
- The agent's model is `global.anthropic.claude-sonnet-5-5` (`agent/agent.py` `MODEL_ID`). If you change `MODEL_ID`,
  change the three `InvokeSonnet` resources to match.
- None of the Lambda policies grants CloudWatch Logs access. Attach the AWS managed policy
  `AWSLambdaBasicExecutionRole` to the five Lambda roles so they can write logs.
- `cascade-submit-lambda` needs `dynamodb:UpdateItem` for the per-minute rate-limit counters, which live in the
  jobs table under `rate#...` keys, and to mark a job FAILED when it cannot be queued.

## Wildcard resources (JSON has no comments, so they are explained here)

No action contains a wildcard. These resources do:

- `arn:aws:glue:us-east-1:339713040194:table/cascade/*`: the tables in the `cascade` database. Glue evaluates `GetTables` and `GetPartitions` against table ARNs, and the tables are not known up front.
- `arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-5-5*` and `arn:aws:bedrock:::foundation-model/...`: the global inference profile routes requests to other regions, so the region is `*` (and empty for global routing). Foundation-model ARNs have no account id. The trailing `*` covers model version suffixes.
- `arn:aws:ecr:us-east-1:339713040194:repository/*`: the agent's container repository is named when the runtime is created. Narrow it to that repository once known.
- `ecr:GetAuthorizationToken`, X-Ray and `cloudwatch:PutMetricData` (limited to the `bedrock-agentcore` namespace) only accept `*` as a resource.
- `.../workload-identity-directory/default/workload-identity/*`: AgentCore creates the runtime's workload identity at deploy time.
- `arn:aws:bedrock:us-east-1:339713040194:agent-alias/*` (legacy role only): the classic agent's IDs are created in the console.
- `.../processed/*`, `.../athena-results/*`, `.../traces/*`: S3 key prefixes, scoped to one prefix each.
- `s3:ListBucket` condition `processed/*`, `athena-results/*`: limits listing to those prefixes.

## Deviations from the request

- `s3:GetBucketLocation` is a bucket-level action, so its resource is the bucket ARN, not `athena-results/*`.
- `s3:ListBucket` on the tools and research roles also allows the `athena-results/` prefix, because Athena lists the results location.
