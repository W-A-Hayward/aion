# AION : Autonomous Intelligence & Observation Network

AION is a hackathon MVP: an AWS Bedrock agent that explains how oil-price moves reach three demo investor portfolios. Deployment steps are in `docs/infrastructure.md`.

## Folder map

| Path | Purpose |
|------|---------|
| `docs/` | Documentation, including `data_contract.md` |
| `ingest/` | Data fetching and upload to S3 (`fetch_to_s3.py`) |
| `compute/` | Python package for analytics and portfolio computations |
| `lambdas/tools/` | Bedrock action-group Lambda (tools the agent calls) |
| `lambdas/submit/` | Lambda that accepts a question request |
| `lambdas/worker/` | Lambda that processes a request asynchronously |
| `lambdas/status/` | Lambda that reports request status/results |
| `lambdas/research/` | Lambda behind `GET /research`: the Research page's tables for one ticker |
| `agent/` | Strands agent hosted on Bedrock AgentCore |
| `infra/` | Athena DDL (generated), HTTP API definition, smoke test and local end-to-end test |
| `frontend/` | Static web app (research, workspace, chat); see `frontend/README.md` |
| `eval/` | Agent evaluation questions (`questions.json`) and scorer (`run_eval.py`) |
| `prompts/` | Agent prompts |
| `iam/` | IAM policy documents |
| `data/` | Local data, git-ignored |

Configuration (bucket, table, queue, agent id) is read from environment variables; nothing is hard-coded.

## Installation for judging teams

AION is deployed by hand in the AWS console (no SAM, CDK or other frameworks). Region `us-east-1`, bucket `cascade-s3-bucket`, every AWS resource prefixed `cascade-`.

### Option A: look at it locally (no AWS needed)

Requires Python 3.12 and, optionally, Node.js for the frontend tests.

1. Serve the static frontend, which ships with saved snapshot data:

   ```sh
   python3 -m http.server 4173 --bind 127.0.0.1 --directory frontend
   ```

   Open <http://127.0.0.1:4173/>. Without API URLs in `frontend/config.js` the chat is not live; research and evidence views use the bundled snapshots. See `frontend/README.md`.

2. Run the backend tests on synthetic data (they never call AWS):

   ```sh
   python3 -m venv .venv && source .venv/bin/activate
   pip install pytest boto3
   python3 -m pytest
   node --test frontend/frontend.test.mjs
   ```

### Option B: install in the team's AWS account

Use this to rebuild cascade in the AWS account the team has been given access to. Everything is done in the AWS console (or CloudShell); there is no SAM, CDK or other tooling to install. Sign in with the credentials the team provided and switch the console region to **us-east-1**. `docs/infrastructure.md` has the full detail for each step; this is the short path. Do the steps in order, because each one depends on the ones above it.

**Conventions:** region `us-east-1`, bucket `cascade-s3-bucket`, every resource name starts with `cascade-` (except the two SQS queues and the Athena database, which are named below).

**Before you start**
- Check that the signed-in role can create IAM roles, Lambda, API Gateway, DynamoDB, SQS, Athena, SageMaker, Bedrock and AgentCore resources.
- In Bedrock → Model access, enable the Claude Sonnet model named in `docs/infrastructure.md` (`MODEL_ID`) and **Titan Text Embeddings V2**.
- Create the S3 bucket `cascade-s3-bucket` if it does not exist.
- Download or clone this repository so you can copy file contents into the console.

**1. Load the data and run the analytics**
1. Fetch the raw data and upload it to `s3://cascade-s3-bucket/raw/`. In CloudShell (or a SageMaker terminal) with this repository copied in: `pip install pandas yfinance requests`, `export BUCKET=cascade-s3-bucket`, then `python3 ingest/fetch_to_s3.py --starter-dir data/alphaforge_starter`. See the script's docstring for options. The expected table layout is in `docs/data_contract.md`.
2. Upload the evidence documents to `s3://cascade-s3-bucket/raw/manual_docs/` (sources in `docs/evidence_sources.md`).
3. In SageMaker AI, create a notebook instance, upload the `compute/` folder, and run `compute/run_stats.ipynb`, then `compute/run_evidence.ipynb`, with **Restart & Run All**. Both end with assertions that must pass.
4. Confirm that `processed/` and `evidence/` now contain files in the bucket.

**2. Athena**
1. Create workgroup `cascade`: query results in `s3://cascade-s3-bucket/athena-results/`, override client-side settings on, 1 GB scan limit.
2. In the query editor (workgroup `cascade`), run each statement of `infra/athena/create_tables.sql` one at a time.
3. Check: `SELECT ticker, beta_simple, n_weeks FROM cascade.sensitivities WHERE universe = 'core'` returns 14 rows.

**3. DynamoDB and SQS**
- DynamoDB table `cascade-jobs`: partition key `jobId` (String), on-demand capacity, Time to Live on attribute `expiresAt`.
- SQS standard queue `agent-jobs-dlq` (14 day retention).
- SQS standard queue `agent-jobs`: visibility timeout 1800 s, retention 1 day, long polling 20 s, dead-letter queue `agent-jobs-dlq` with 3 maximum receives. Note its URL.

**4. IAM roles**
The files in `iam/` and `infra/api/cascade-api.openapi.json` contain the placeholder `ACCOUNT_ID`. Replace it with the 12-digit account ID shown in the console's top-right menu before pasting (also `RUNTIME_ID` in `cascade-worker-lambda.json`, after step 6). For each role listed in `iam/README.md`, create a role with the matching `iam/<role>.trust.json` as trust policy and `iam/<role>.json` as an inline policy. Attach `AWSLambdaBasicExecutionRole` to the five Lambda roles. The placeholders `KNOWLEDGE_BASE_ID` and `GUARDRAIL_ID` in `cascade-agentcore-runtime.json` are filled in after steps 5 and 6.

**5. Knowledge base**
Bedrock → Knowledge Bases → create `cascade-evidence` with an S3 data source at `s3://cascade-s3-bucket/evidence/`, **No chunking**, Titan Text Embeddings V2 and a quick-create vector store. Click **Sync**, and sync again after any later evidence run. Note the knowledge base ID.

**6. Agent runtime**
1. Upload `prompts/agent_instructions.md` to `s3://cascade-s3-bucket/prompts/agent_instructions.md`.
2. Host `agent/agent.py` (dependencies in `agent/requirements.txt`) as an AgentCore runtime named `cascade_agent` with role `cascade-agentcore-runtime`. Use the AgentCore console's *Host agent* flow, or CloudShell with `pip install bedrock-agentcore-starter-toolkit`, then `agentcore configure` and `agentcore launch`.
3. Set the runtime environment variables `MODEL_ID`, `TOOLS_FUNCTION=cascade-tools`, `KB_ID`, `BUCKET=cascade-s3-bucket` (and optionally `GUARDRAIL_ID`, `GUARDRAIL_VERSION`).
4. Copy the runtime ARN. If the runtime ID differs from the one in `iam/cascade-worker-lambda.json`, update that policy.

**7. Lambda functions**
Create five functions with runtime **Python 3.12**, handler `app.lambda_handler`, and paste the matching `lambdas/<name>/app.py` into the console code editor. Each uses its `cascade-<name>-lambda` role.

| Function | Source | Timeout | Memory |
|---|---|---|---|
| `cascade-tools` | `lambdas/tools` | 30 s | 256 MB |
| `cascade-research` | `lambdas/research` | 30 s | 256 MB |
| `cascade-submit` | `lambdas/submit` | 10 s | 128 MB |
| `cascade-status` | `lambdas/status` | 5 s | 128 MB |
| `cascade-worker` | `lambdas/worker` | 300 s | 256 MB |

Environment variables per function are listed in `docs/infrastructure.md` §8. They use the queue URL, runtime ARN and frontend origin from the other steps. Then add an SQS trigger on `cascade-worker` for `agent-jobs`: batch size 1, **Report batch item failures** on, maximum concurrency 5.

**8. HTTP API**
1. In `infra/api/cascade-api.openapi.json`, replace `REPLACE_WITH_FRONTEND_ORIGIN` with the origin where the frontend will be served (no trailing slash). Use the same value for `ALLOWED_ORIGIN` on the Lambdas.
2. API Gateway → create an **HTTP API → Import** and paste the file. It defines `POST /jobs`, `GET /jobs/{id}` and `GET /research`.
3. Allow API Gateway to invoke `cascade-submit`, `cascade-status` and `cascade-research`.
4. Keep the `$default` stage with auto-deploy. Set throttling to 20 req/s (burst 40), and 2 req/s (burst 5) on `POST /jobs`. Note the invoke URL.

**9. Frontend**
Edit `frontend/config.js` so `investigationUrl` is `<invoke URL>/research`, `submitUrl` is `<invoke URL>/jobs`, `statusUrl` is `<invoke URL>/jobs/{id}`, and `jobTimeoutMs` is `240000`. Host the `frontend/` folder as a static site (for example S3 with CloudFront) at the origin you used in step 8. For a quick check you can instead serve it locally as in Option A, using `http://127.0.0.1:4173` as the origin.

**10. Verify**

```sh
python3 infra/smoke_test.py --api <invoke URL> --origin <frontend origin>
python3 eval/run_eval.py --api <invoke URL> --out eval/last_run.json
```

The smoke test must exit 0. The evaluation sends 15 questions and takes several minutes.

If something fails, see the troubleshooting table at the end of `docs/infrastructure.md`.

## Disclaimer

Simulation only, not advice.
