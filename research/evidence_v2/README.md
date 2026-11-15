# Evidence v2 — isolated research proof of concept

This directory is a standalone design-and-test implementation. It does **not**
modify or import CASCADE's production pipeline. It uses Python's standard library
only. There is no boto3 dependency, network client, credential lookup, real S3
adapter, KB export, deployment, or automatic migration of existing data.

## Run locally

From the repository root:

```sh
python3 -B -m unittest discover -s research/evidence_v2 -p 'test_*.py' -v
python3 -B research/evidence_v2/demo.py
```

To examine the user-supplied original instead of the bundled fixture:

```sh
python3 -B research/evidence_v2/demo.py --csv /Users/leahemidj/Downloads/RIPPLE_ATD_2026_evidence_candidates.csv
```

`--show-catalog` prints the complete research catalog to stdout. Neither the demo
nor the tests writes files. `-B` disables bytecode cache files. Every simulated
object and publication disappears when the process exits. Do not redirect output
into a production input or invoke `compute/evidence.py` with this catalog.

## Files

| File | Purpose |
|---|---|
| `schema.py` | Frozen Document, EvidencePassage, EvidenceContext, Verification and Catalog structures; validation, deterministic IDs and lossless JSON serialization. |
| `import_candidates.py` | Reads the candidate CSV, including UTF-8 BOM/CRLF; preserves original quotes, input claims and research IDs; creates explicit holding contexts. |
| `memory_s3.py` | In-memory S3-shaped test double with conditional writes and failure injection. No delete method or AWS connection. |
| `catalog.py` | Non-destructive union, conflict detection, immutable version snapshots and activation via a conditional current-version pointer. Only accepts the exact in-memory test-double type. |
| `demo.py` | Reads ATD candidates and adds them to a synthetic existing catalog; reports preservation and verification states. |
| `test_evidence_v2.py` | Local integrity, compatibility-boundary, failure and partial-batch safety tests. |
| `fixtures/atd_candidates.csv` | Unmodified copy of the supplied research CSV, not a PDF or a production evidence table. |

## What is preserved, and what is NOT independently verified

The fixture was copied from
`/Users/leahemidj/Downloads/RIPPLE_ATD_2026_evidence_candidates.csv`.
It contains five ATD candidates from the French *Rapport annuel 2026*.

The source **PDF's declared** SHA-256 is:

```text
e5707264468a705945d2b7e078373ca12fedbbe51213e566f11c82a95f970e2b
```

The POC preserves this value; it has not opened or hashed the PDF. It separately
hashes the input **CSV** to identify the artifact containing the assertions.
These two hashes must never be confused.

For the supplied ATD rows:

- `quote_verified_claim=true` is preserved, with verification status
  `reported_verified` and method `candidate_csv_assertion`. This is the user's
  recorded local verification, not a new PDF comparison by this program.
- `source_url_verified_claim=false`, `source_url=null`, source verification
  `unverified`, and link status `not_supplied` remain explicit.
- Issuer verification is `unverified`; the issuer name is preserved as supplied.
- Hash verification is `reported_verified`; the file's declared hash is not proof
  that the official publisher serves those exact bytes.
- `publication_date=null`. The date in the filename is not a verified publication
  date. The separate fiscal year end `2026-04-26` is preserved.
- Quotes, apostrophes, accents, `%2` and `marge brute1` footnote markers, printed
  page labels, PDF page numbers and section strings are preserved without editing.
- Interpretations and `channel_candidate` values are preserved as research
  annotations. They are not independently validated operational findings. For
  example, `fuel_price_demand` does not establish the cause of the reported volume
  change; that interpretation still needs review.

A `verified` verification record requires a method, verifier and timezone-aware
timestamp. The schema only checks the completeness of that record; it cannot
authenticate a human assertion. The importer **never** promotes CSV flags to this
status. `reported_verified` is deliberately distinct from `verified`.

Link availability is separate from provenance verification: a previously verified
document can have a currently unavailable URL; an accessible URL is not necessarily
the correct official source. URLs are not fetched, and credential-bearing or
non-HTTP(S) URLs are rejected.

## Structures and identity

- **Document** identifies exact bytes by `doc:sha256:<PDF hash>`, independently of
  its filename. It holds issuer/title/language/fiscal dates/source URL and separate
  verification records. `s3_key` remains null until an authorized integration
  actually establishes a storage location.
- **EvidencePassage** identifies an exact original quote and physical PDF page in
  that document. Its ID hashes the canonical UTF-8 JSON tuple
  `[document_id, pdf_page, excerpt_original]`. Input order, category and research
  rank do not change it. A different quote, page or PDF produces a new ID.
  `research_id` preserves `ATD-2026-01` through `ATD-2026-05`.
- **EvidenceContext** references a passage and its investigation without rewriting
  the subject ticker. A holding association requires a dated holdings-source ID
  and row reference. Direct ETF evidence instead requires the passage's subject
  itself to be that ETF. Its ID hashes those association fields.

The demo associates ATD passages with XIU using the team's previously supplied
12 November 2026 holdings reference. It does not retrieve that source or verify
membership again, and it does not calculate weights or contributions. The
`team-reported:` source prefix makes this boundary visible.

For operational passages the POC requires
`stock_return_direction="unknown"`. Positive, negative or mixed stock-return
claims on an operational record are rejected, not substituted. Statistical Brent
betas, confidence intervals, model controls and causal claims are **not** stored or
computed by this POC. No old `direction="mixed"` compatibility alias is fabricated.

## Non-destructive publication simulation

“Publish” here means activating a **research catalog in MemoryS3**, not publishing
evidence to users, Athena or a Bedrock Knowledge Base. The catalog envelope is
always `schema_version=2, catalog_kind="research_only"`.

1. Load the current pointer and its complete snapshot. A missing, malformed,
   unreadable or digest-mismatched catalog is fatal. There is no empty-catalog
   fallback.
2. Validate the complete incoming batch before any write. A batch with no passages
   is rejected, including a document-only batch.
3. Merge documents, passages and contexts by stable ID. Identical records are
   idempotent. Different metadata under an existing ID is a conflict requiring
   explicit review; no record is silently overwritten or downgraded.
4. Stage the full merged catalog under a content-addressed snapshot key. Existing
   snapshot bytes cannot be overwritten by the publication function.
5. Read back and validate the snapshot, then conditionally advance `current.json`
   using the previously read pointer token. The old snapshot remains untouched.
6. A stale plan cannot replace another partial batch. Re-read and merge again;
   do not retry blindly. Repeating an identical nonempty import performs no writes.

The fake implements atomic compare-and-swap under an in-process lock. Its ETag is
an opaque test token, **not an assertion about real S3 ETag semantics**. Real AWS
conditional writes, permissions and failure modes have not been tested.

An interruption before pointer activation may leave an unreferenced staged
snapshot; readers still see the previous complete catalog. No cleanup runs.
If a process loses its response after activation, the caller must re-read the
pointer to determine the outcome; a timeout alone cannot prove a rollback.

`seed_demo_store` is explicit fixture setup and requires a completely empty fake
store plus a nonempty catalog. It is not called by the publisher to recover a
missing catalog. The existing “ENB.TO” fixture is labelled synthetic throughout:
its text is **not an Enbridge quotation, report, source or investment fact**.

## Deliberate integration boundaries

- JSON only, no Parquet/Glue catalog registration or source-file publication.
- No production KB eligibility gate or KB export exists: all data stays in a
  research-only catalog. ATD's official URL is still unverified.
- Unknown/legacy schema envelopes are rejected, not silently migrated. Production
  v1 fields and IDs are untouched. A backward-compatible projection and explicit
  legacy-ID migration must be agreed before connecting this POC to CASCADE.
- The candidate importer is specifically for the supplied operational company CSV;
  it does not infer arbitrary document types, company identities or stock effects.
- Same-ID metadata changes, verification upgrades, subject corrections and CSV
  provenance revisions are intentionally conflicts. A reviewed revision workflow
  is future work, not a last-writer-wins update.
- The POC does not parse the PDF, verify quote locations, inspect footnotes, check
  publisher identity, fetch URLs, recompute portfolio statistics, or alter the
  current cache/selection logic in `compute/evidence.py`.

## Teammate approval required before integration

1. **Data/research:** match the exact official PDF URL to the declared hash;
   verify issuer, publication date, pages, quotes and footnote context; decide who
   can sign verification records and approve interpretations.
2. **Backend/contract:** approve field names, statuses, ID encoding, v1 projection,
   reviewed metadata revisions and migration of existing IDs without renumbering.
3. **Pipeline owner:** replace the current destructive partial-batch behavior and
   cache-as-authority logic; preserve the full existing catalog. This POC has not
   changed `compute/evidence.py` and therefore has not made that pipeline safe yet.
4. **AWS owner:** approve real storage paths, writer/concurrency controls,
   conditional activation, version retention, migration, rollback and IAM. Keep
   staging outside Athena/KB scans and agree how a complete active version becomes
   visible to each reader. No such AWS changes are included here.
5. **Lambda/agent/frontend owners:** approve enriched citations and holding-vs-ETF
   context, preserve exact quotes, distinguish unverified links, and prevent
   operational passages from validating a statistical beta's sign.
6. **Release owner:** approve a separate, explicit integration/publication step
   only after local contract tests and the source-validation requirements pass.

## Validation coverage

Tests exercise the real supplied CSV as a read-only fixture, quote/page/hash and
claim preservation, ID determinism, malformed input, unknown direction, holding
vs ETF identity, catalog round trips, partial merges, zero writes on empty batches
and conflicts, missing/unreadable/corrupt catalogs, idempotent reimports, staged
write and activation failures, stale plans, conditional-write rejection, immutable
previous snapshots, and rejection of any non-memory client.
