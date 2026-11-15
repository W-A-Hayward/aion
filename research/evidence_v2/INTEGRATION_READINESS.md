# evidence_v2 → production: integration readiness (Phase 5)

Planning only. Nothing here has been executed. No S3 upload, evidence publishing, KB sync or deployment was done.
Inputs read: [`docs/infrastructure.md`](../../docs/infrastructure.md) (present), `compute/evidence.py`,
`lambdas/tools/app.py`, `lambdas/research/app.py`, `agent/agent.py`, `docs/data_contract.md`.

## What the current production pipeline does (and why v2 must not reuse it)

| Behaviour | Where | Risk for v2 |
|---|---|---|
| Lists every object under `evidence/` and **deletes all not in the current batch, before writing** | `compute/evidence.py` `write_evidence` | A partial or empty run wipes the KB corpus. A v2 publish through it would delete the production evidence. |
| `processed/evidence/part-0.parquet` overwritten in place (likewise `confidence`, `edges` via `run_part_b`) | `write_parquet_s3` | No versions, no run ID, no rollback except S3 object versioning (if enabled). |
| No Knowledge Base ingestion call anywhere | — | Sync is manual; nothing records which corpus version the KB holds. |
| Evidence IDs like `XOM-direct-1`; columns lack PDF page, printed page, document hash, research ID and verification statuses | `EVIDENCE_COLUMNS` | v2 rows do not fit the production table without losing provenance. |
| Tools and research Lambdas filter evidence by exact `ticker`; the tools Lambda rejects tickers outside its 35-ticker `UNIVERSE` | `lambdas/tools/app.py` `norm_ticker` | CP.TO evidence would be unreachable through the agent until CP.TO is added. |

**Strategy in one line:** publish v2 to its own versioned prefixes and tables, beside the production evidence. Never
call `write_evidence` or `run_part_b` for it, and switch versions with a pointer and a KB metadata filter, not by
deleting.

## 1. Required S3 objects and metadata

All under `s3://cascade-s3-bucket/`. `<run>` = `evidence_v2_YYYYMMDDTHHMMSSZ_<8-hex>`, immutable once written.

| Object | Content | Object metadata (`x-amz-meta-*`) |
|---|---|---|
| `raw/evidence_v2/documents/sha256=<hash>.pdf` (×5) | The five annual-report PDFs, content-addressed | `sha256`, `issuer`, `source-url`, `provenance-status` (CPKC: `pending_issuer_to_cdn_link`) |
| `raw/evidence_v2/holdings/XIU/as_of=2026-11-12/xiu_holdings.csv` | The reviewed holdings snapshot (SHA-256 `9caae3aa…7527`) | `sha256`, `as-of`, `source-url` |
| `processed/evidence_v2/run=<run>/documents.parquet` | One row per document: id, sha256, issuer, title, fiscal period, source URL, provenance status, verification records | — |
| `processed/evidence_v2/run=<run>/passages.parquet` | 35 rows: evidence_id, research_id, subject_ticker, pdf_page, printed_page, section, excerpt_original, operational_channel, stock_return_direction (`unknown`), interpretation, quote verification | — |
| `processed/evidence_v2/run=<run>/contexts.parquet` | 35 holding contexts: investigation XIU.TO, subject ticker, holdings_as_of, holding_row_id, displayed weight | — |
| `processed/evidence_v2/run=<run>/manifest.json` | Run ID, input hashes (CSVs, register, holdings, PDFs), code revision, counts, provenance statuses, "weight ≠ beta coverage" note | — |
| `processed/evidence_v2/current.json` | Pointer `{run, generation, previous_run}`; written only with a conditional put | — |
| `kb/evidence_v2/run=<run>/<evidence-hex>.txt` + `.metadata.json` (×35) | KB document per passage (quote, section, page, issuer, source) | Metadata attributes: `run_id`, `subject_ticker`, `research_id`, `document_sha256`, `pdf_page`, `printed_page`, `section`, `operational_channel`, `provenance_status`, `quote_verification_status`; plus `investigation_ticker` = XIU.TO and `holdings_as_of` |

Use a KB prefix separate from the production `evidence/`, so the production deletion logic can never touch it.
Keep metadata values short and within the Bedrock Knowledge Base metadata-file limits; long text stays in the
document body.

## 2. Safe, non-destructive publication strategy

1. **Build locally**, from the verified CSVs and `xiu_resolution_5_companies.json`, into a staging folder whose
   layout matches the keys above. Validate with the existing schema (`Catalog.validate`) before anything leaves the
   machine.
2. **Refuse empty or shrinking runs:** passage count must be ≥ the previous run's unless a reviewer approves a removal
   list. This is the opposite of `write_evidence`'s delete-first behaviour.
3. **Upload write-once:** new `run=<run>` prefix only, with `If-None-Match: *` on every put, so existing objects can
   never be overwritten. No delete calls in the publisher at all.
4. **Verify after upload:** re-list the run prefix and re-hash every object against the local manifest.
5. **Activate** by writing `current.json` with a conditional put (`If-Match` on the previous ETag), mirroring
   `research/evidence_v2/catalog.py`'s pointer model, which is already tested against an in-memory store.
6. **KB:** one data source over `kb/evidence_v2/` that holds all runs. Retrieval filters on `run_id` equal to the
   active run, so switching versions is a filter change, not a deletion. This needs a small agent change (below).
7. **Production evidence is untouched:** `processed/evidence`, `evidence/`, `confidence` and `edges` keep working
   exactly as today.

## 3. Required data contract / API changes (all need approval)

| Area | Change |
|---|---|
| `docs/data_contract.md` | Add the tables `evidence_v2_documents`, `evidence_v2_passages`, `evidence_contexts` (and, if holdings are exposed, `etf_holdings`) with the columns above; add the `kb/evidence_v2/` prefix and its metadata attributes; state that context weight is not beta coverage. |
| Glue/Athena | Tables over `processed/evidence_v2/run=<run>/…`, generated like `infra/athena/gen_ddl.py`. Point them at the active run (re-create on activation, or use a view). |
| `lambdas/research/app.py` + `frontend/api.js` `TABLES` | Add `evidence_v2_passages` and `evidence_contexts` to the envelope, so XIU can show "evidence from its holdings" with the weight and the provenance status. The frontend must label weight as composition, not coverage, and show CPKC as provenance pending. |
| `lambdas/tools/app.py` | A new read-only function (for example `get_constituent_evidence(etf_ticker)`) returning passages by holding, with weight and provenance. Add CP.TO to `UNIVERSE` only after the Phase 3 approval. |
| `agent/agent.py` `search_evidence` | Add a `run_id` filter (and optionally `subject_ticker`) for the `kb/evidence_v2/` data source; cite `research_id`, page and section. |
| Prompt | Rule: operational passages never imply a share-price direction; say "provenance pending" for CPKC. |

## 4. Rollback plan

| Failure | Rollback | Data loss |
|---|---|---|
| Bad run detected before activation | Do nothing: `current.json` still points at the previous run | None |
| Bad run after activation | Conditional put of `current.json` back to `previous_run`; set the KB retrieval filter back to that run ID; re-point the Glue tables or view | None (runs are immutable) |
| KB sync ingested something wrong | Filter excludes the bad `run_id` immediately; re-sync after fixing | None |
| Production evidence affected | It isn't touched by this design. If S3 versioning is enabled, previous object versions remain restorable for production keys. | — |

Prerequisite to confirm (owner): **S3 versioning on `cascade-s3-bucket`**. It is not described anywhere in the repo.

## 5. Deployment and KB sync checklist

- [ ] Backend owner approves this plan and the contract changes (section 3).
- [ ] CPKC: either a browser-archived issuer link (see `provenance/CPKC_2025_EN/provenance_check.json`), or publish it explicitly marked `pending_issuer_to_cdn_link`.
- [ ] Brent betas recomputed on current code (`research/stats_repro/`) before any beta is shown beside this evidence.
- [ ] Local build: `Catalog.validate` passes; counts (5 documents, 35 passages, 5 holdings); all test suites green.
- [ ] Confirm S3 versioning; confirm the publisher has no `DeleteObject` permission (IAM policy scoped to `PutObject` on the new prefixes only).
- [ ] Upload the run write-once; re-list and re-hash against the manifest.
- [ ] Create Glue tables for the run; run sample Athena queries (35 passages, 5 tickers).
- [ ] Create KB data source `kb/evidence_v2/` (no chunking, as for `evidence/`); **Sync**; record the ingestion job ID and document count (expect 35) in the run manifest.
- [ ] Test retrieval with `run_id` filter: a CNQ query returns CNQ-2025-07; a CPKC result carries `provenance_status=pending_issuer_to_cdn_link`.
- [ ] Activate `current.json`; deploy the Lambda and agent changes; run `infra/smoke_test.py` and `eval/run_eval.py`.
- [ ] Record the activation (run ID, generation, ingestion job) and keep the previous run ID for rollback.

## 6. Actions requiring backend-owner approval

1. Any write to `cascade-s3-bucket`, including new prefixes.
2. Creating the KB data source and running any ingestion/sync job.
3. Changes to `docs/data_contract.md`, `compute/stats.py`, `compute/evidence.py`, `ingest/fetch_to_s3.py`.
4. Adding CP.TO to the universe (and recomputing all q-values and labels).
5. Glue/Athena table creation; IAM policy for the publisher.
6. Changes to `lambdas/tools`, `lambdas/research`, `agent/agent.py`, the prompt and the frontend contract.
7. Treating CPKC's PDF as official before the issuer link is archived.
8. Running the SageMaker beta reproduction (read-only, but it uses the production role).
