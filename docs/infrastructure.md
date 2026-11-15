# cascade infrastructure and deployment runbook

Everything is created in the AWS console (or CloudShell / the SageMaker notebook, which run inside AWS),
per `.kiro/steering/project.md`. Region **us-east-1**, account **339713040194**, bucket **cascade-s3-bucket**.
Do the steps in order; each one depends on the ones above it. "Paste" means copy the named file's contents.

```text
browser ──HTTP API (CORS)──▶ cascade-submit ──▶ DynamoDB cascade-jobs ◀── cascade-status ◀── browser polls
                                   │                     ▲
                                   ▼                     │
                             SQS agent-jobs ──▶ cascade-worker ──▶ AgentCore runtime (agent/agent.py)
                                   │ (3 tries)                         │            │
                                   ▼                                   ▼            ▼
                             agent-jobs-dlq                     cascade-tools   KB cascade-evidence
browser ──GET /research──▶ cascade-research ──┐                      │
                                               └──▶ Athena (workgroup cascade) ──▶ s3://…/processed/*.parquet
```

## 1. Data: re-run the statistics on the current code

The saved outputs in `compute/run_stats.ipynb` predate code changes (ZST now uses the 2-year Canadian yield,
the portfolio beta aggregates simple returns, integer columns are `bigint`). Re-run before creating tables.

1. SageMaker AI → the notebook instance → open `compute/run_stats.ipynb` from the current `main`.
2. Kernel → **Restart & Run All**. The last cell's asserts (XOM positive and significant, TLT negative…) must pass.
3. Confirm the run in S3: `processed/<table>/part-0.parquet` for the 10 stats tables, and
   `processed/_summary/summary.md` now includes the FX diagnostic (the notebook passes `data=data` since this change).

## 2. Evidence: extract from real documents

The document set is prepared locally in `data/manual_docs/` (git-ignored). Sources and hashes are in
[evidence_sources.md](evidence_sources.md).

1. S3 console → `cascade-s3-bucket` → create folder `raw/manual_docs/` if missing → **Upload** every file in
   `data/manual_docs/`, including `manifest_docs.csv`.
2. In the same SageMaker instance, open `compute/run_evidence.ipynb` → **Restart & Run All**.
   It calls Bedrock (`EVIDENCE_MODEL_ID`, default `global.anthropic.claude-sonnet-5-5`); the notebook role needs
   `bedrock:InvokeModel` on that profile. The final cell asserts every excerpt is verbatim.
3. Check: `processed/evidence/`, `processed/confidence/`, `processed/edges/` exist, and `evidence/` holds one
   `<id>.txt` plus `<id>.txt.metadata.json` per evidence row.

Warning: `write_evidence` deletes `evidence/` objects that are not in the new run. Never run Part A with an empty
or partial `raw/manual_docs/`.

## 3. Athena tables

1. Athena → Workgroups → create **cascade**: query result location `s3://cascade-s3-bucket/athena-results/`,
   **Override client-side settings** on, data scanned limit per query 1 GB.
2. Query editor (workgroup `cascade`) → run each statement of
   [`infra/athena/create_tables.sql`](../infra/athena/create_tables.sql) **one at a time**, top to bottom.
3. Check: `SELECT ticker, beta_simple, n_weeks FROM cascade.sensitivities WHERE universe = 'core'` returns 14 rows.
   A `HIVE_BAD_DATA` / type mismatch error means a Parquet file was written by old code: redo step 1 or 2.

The DDL is generated from the code (`python infra/athena/gen_ddl.py`); `infra/athena/test_ddl.py` fails if it drifts.

## 4. DynamoDB and SQS

**DynamoDB** → create table **cascade-jobs**: partition key `jobId` (String), capacity **on-demand**.
Then Additional settings → **Time to Live** → attribute `expiresAt` → enable. (Jobs expire after 24 h; rate-limit
counters, stored as `rate#…` items, after 2 min.)

**SQS** → create two **standard** queues:

| Queue | Setting | Value | Why |
|---|---|---|---|
| `agent-jobs-dlq` | Message retention | 14 days | Time to inspect failed jobs |
| `agent-jobs` | Visibility timeout | **1800 s** | ≥ 6 × the worker's 300 s timeout (AWS guidance for Lambda triggers) |
| | Message retention | 1 day | A job row expires after 24 h anyway |
| | Receive message wait time | 20 s | Long polling |
| | Dead-letter queue | `agent-jobs-dlq`, **maximum receives 3** | Throttled jobs retry; poison messages park |

## 5. IAM roles

Create one role per row of the table in [`iam/README.md`](../iam/README.md): paste `<role>.trust.json` as the
trust policy and `<role>.json` as an inline policy. Attach **AWSLambdaBasicExecutionRole** to the five Lambda roles.
Replace `KNOWLEDGE_BASE_ID` / `GUARDRAIL_ID` in `cascade-agentcore-runtime.json` after steps 6–7.

## 6. Knowledge base

Bedrock → Knowledge Bases → **Create** → *Knowledge base with vector store*:

- Name **cascade-evidence**; data source **S3** → `s3://cascade-s3-bucket/evidence/` (the `.metadata.json` sidecars
  supply the `ticker`, `channel`, `section`, `source_url` fields `search_evidence` filters and cites).
- Chunking: **No chunking** (each file is already one passage). Embeddings: Titan Text Embeddings V2.
  Vector store: quick-create.
- After creation → select the data source → **Sync**. Re-sync after every evidence run (step 2).
- Test in the console: query "oil price effect on yields" should return a Bank of Canada passage.

Note the KB ID for step 7. Optionally create guardrail **cascade-guardrail** and note its ID and version.

## 7. Agent runtime (AgentCore)

1. Upload `prompts/agent_instructions.md` to `s3://cascade-s3-bucket/prompts/agent_instructions.md`.
2. Host `agent/agent.py` (with `agent/requirements.txt`) as an AgentCore runtime named `cascade_agent`, using
   role **cascade-agentcore-runtime**: either the AgentCore console's *Host agent* flow, or from **CloudShell** with the
   starter toolkit (`pip install bedrock-agentcore-starter-toolkit`, then `agentcore configure` and `agentcore launch`;
   check the flags with `--help`).
3. Runtime environment variables:

| Variable | Value |
|---|---|
| `MODEL_ID` | `global.anthropic.claude-sonnet-5-5` (must match the role's `InvokeSonnet` resources) |
| `TOOLS_FUNCTION` | `cascade-tools` |
| `KB_ID` | the knowledge base ID from step 6 |
| `GUARDRAIL_ID`, `GUARDRAIL_VERSION` | optional, from step 6 |
| `BUCKET` | `cascade-s3-bucket` |

4. Copy the runtime ARN. If its ID differs from `agent-uciA60FqQs`, update `iam/cascade-worker-lambda.json`.
5. Test in the console with payload `{"question": "How exposed is my portfolio to oil?", "persona": "robert", "level": "beginner"}`.
   The response must have a non-empty `toolCalls`.

## 8. Lambda functions

All: runtime **Python 3.12**, architecture arm64 or x86_64, handler **`app.lambda_handler`**, code = the folder's
`app.py` (paste into the console editor). Each uses the matching `cascade-<name>-lambda` role.

| Function | Folder | Timeout | Memory | Environment variables |
|---|---|---|---|---|
| `cascade-tools` | `lambdas/tools` | 30 s | 256 MB | `ATHENA_DB=cascade`, `ATHENA_WORKGROUP=cascade`, `ATHENA_OUTPUT=s3://cascade-s3-bucket/athena-results/` |
| `cascade-research` | `lambdas/research` | 30 s | 256 MB | same three as tools, plus `ALLOWED_ORIGIN`, `CACHE_SECONDS=300` |
| `cascade-submit` | `lambdas/submit` | 10 s | 128 MB | `JOBS_TABLE=cascade-jobs`, `QUEUE_URL=<agent-jobs URL>`, `ALLOWED_ORIGIN`, `RATE_PER_OWNER_PER_MIN=5`, `RATE_PER_IP_PER_MIN=30` |
| `cascade-status` | `lambdas/status` | 5 s | 128 MB | `JOBS_TABLE=cascade-jobs`, `ALLOWED_ORIGIN` |
| `cascade-worker` | `lambdas/worker` | **300 s** | 256 MB | `JOBS_TABLE=cascade-jobs`, `AGENT_RUNTIME_ARN=<step 7>`, `BUCKET=cascade-s3-bucket`, `STALE_RUNNING_SECONDS=1200` |

`ALLOWED_ORIGIN` is the frontend's origin, e.g. `https://d111111abcdef8.cloudfront.net` (no trailing slash).
`STALE_RUNNING_SECONDS` must stay above the worker timeout.

**Worker trigger:** `cascade-worker` → Add trigger → SQS `agent-jobs`: batch size **1**,
**Report batch item failures** on (the worker returns `batchItemFailures` for throttled jobs),
maximum concurrency **5** (limits parallel Bedrock calls).

## 9. HTTP API (routes and CORS)

1. In [`infra/api/cascade-api.openapi.json`](../infra/api/cascade-api.openapi.json), replace
   `REPLACE_WITH_FRONTEND_ORIGIN` with the same origin as `ALLOWED_ORIGIN`.
2. API Gateway → Create API → **HTTP API → Import** → paste the file. Routes: `POST /jobs` → submit,
   `GET /jobs/{id}` → status, `GET /research` → research. CORS allows `content-type`, `x-cascade-session`,
   `authorization`.
3. For each of the three Lambdas, allow API Gateway to invoke it (the console offers this on the integration page,
   or add a resource-based permission for `apigateway.amazonaws.com`).
4. Stage `$default` (auto-deploy) → **Throttling**: default 20 req/s, burst 40; route `POST /jobs` 2 req/s, burst 5.
5. Note the invoke URL, e.g. `https://abc123.execute-api.us-east-1.amazonaws.com`.

## 10. Access control

- **Default (no sign-in):** the browser creates a random token once (`frontend/agent-api.js` `sessionToken`) and
  sends it as `X-Cascade-Session`. `submit` stores only its SHA-256 as the job's `ownerHash`; `status` returns a
  job only to the same token (anyone else gets 404). `submit` allows 5 questions per minute per token and 30 per
  IP, plus the API Gateway throttles above.
- **With sign-in (optional):** create a Cognito user pool, add a **JWT authorizer** to the `POST /jobs` and
  `GET /jobs/{id}` routes (issuer = the pool, audience = the app client ID). When a JWT is present, the Lambdas use
  its `sub` as the owner instead of the token; no code change is needed. The frontend would also need a sign-in
  flow that sends `Authorization: Bearer <id token>`, which is not built yet.

## 11. Verify end to end

From any machine (it only calls the public API):

```sh
python3 infra/smoke_test.py --api https://abc123.execute-api.us-east-1.amazonaws.com --origin <ALLOWED_ORIGIN>
```

It checks the Research endpoint, that submit rejects a missing token (401), that another browser gets 404, and
polls until the job is **DONE** with at least one tool call. It exits 0 only if every check passes. The same
script runs against the real handlers locally in `infra/test_local_e2e.py`.

Then score the agent: `python3 eval/run_eval.py --api <invoke URL> --out eval/last_run.json` (15 questions,
paced for the rate limit; read the answers too, the checks are coarse).

## 12. Point the frontend at the API

In `frontend/config.js` set:

```js
investigationUrl: 'https://abc123.execute-api.us-east-1.amazonaws.com/research',
submitUrl: 'https://abc123.execute-api.us-east-1.amazonaws.com/jobs',
statusUrl: 'https://abc123.execute-api.us-east-1.amazonaws.com/jobs/{id}',
jobTimeoutMs: 240000,
```

`jobTimeoutMs` should cover a full agent run (the worker may take up to 300 s).

## Troubleshooting

| Symptom | Where to look |
|---|---|
| Browser: CORS error | `ALLOWED_ORIGIN` and the API's CORS origin must both equal the page origin exactly |
| Job stays `PENDING` | Worker trigger disabled, or messages in `agent-jobs-dlq`; worker CloudWatch logs |
| Job `FAILED: AccessDeniedException` | Worker role vs `AGENT_RUNTIME_ARN`; runtime role vs `cascade-tools` / prompt / KB |
| Answer without tool calls | Runtime role missing `lambda:InvokeFunction`, or `TOOLS_FUNCTION` wrong |
| Research `502` | `sensitivities` unreadable: workgroup, DDL (step 3) or research role |
| Research `meta.missing` lists tables | Those Parquet files do not exist yet (e.g. evidence before step 2) |
| `429` from submit | Rate limit working; wait a minute |
