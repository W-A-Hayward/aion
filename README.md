# cascade

cascade is a hackathon MVP: an AWS Bedrock agent that explains how oil-price moves reach three demo investor portfolios. This repository currently holds structure, stubs and docs only; no business logic is implemented yet.

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
| `frontend/` | Static placeholder page |
| `eval/` | Evaluation questions (`questions.json`) |
| `prompts/` | Agent prompts |
| `iam/` | IAM policy documents |
| `data/` | Local data, git-ignored |

Configuration (bucket, table, queue, agent id) is read from environment variables; nothing is hard-coded.

## Disclaimer

Simulation only, not advice.
