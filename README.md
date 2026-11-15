# cascade

cascade is a hackathon MVP: an AWS Bedrock agent that explains how oil-price moves reach three demo investor portfolios. Deployment steps are in `docs/infrastructure.md`.

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

## Disclaimer

Simulation only, not advice.
