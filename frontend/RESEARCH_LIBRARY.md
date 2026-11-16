# AION — local research data integration

## What is connected

The library reads the complete audited acquisition inventory from
`research/source_pipeline/artifacts/runs/2026-11-15T171032535399+0000_8ccfcb/inventory.json`.
This includes the recovery batch and two local document-identity reviews. The browser does not make a
new acquisition, call AWS or replace the existing statistical tables.

| Register availability | Entries | Meaning |
|---|---:|---|
| Usable for intended research | 24 | Acquisition/extraction supports the registered research purpose; not blanket citation approval |
| Context only | 12 | Some content is available, but the intended dataset/report is incomplete or requires further mapping |
| Needs attention | 16 | Blocked, inaccessible, missing or otherwise unsuitable for the intended purpose |
| Total | 52 | Every register entry is visible, including duplicates and entries without files |

37 entries have some extracted content. They reference **66 unique source objects**, with **64 readable
extractions**: 27 PDFs, 30 HTML texts and 7 structured/metadata files. Two objects have no usable extraction.
These counts have different denominators: 52 references are not 52 verified documents. Three PDFs remain
quarantined (CPKC provenance, the Enbridge cover/filing-period conflict, and a BNS proxy circular).
Neither the inventory's `usable` flag nor a hash approves an investment claim.

The recovery panel adds 21 candidates under their 18 existing register entries. Two sources (BMO Q3 2026
HTML and Fortis Q4/FY2025 PDF) were acquired and their identity reviewed locally. Fifteen download candidates
remain blocked at access-policy checks; two aliases, one optional reference and one deferred API task are
not counted as acquired documents. Details and per-file changes:
[recovery integration report](../research/source_pipeline/RECOVERY_INTEGRATION_2026-11-15.md).

## User flow

1. Click **Explore all 52 sources** beside the question suggestions, or open **Research Library** beneath
   the Evidence Desk. Filter by register title/ticker, source group, availability and format.
2. Select a source and a local file. Reports open as extracted text with physical PDF-page navigation;
   web pages have no invented PDF references. Expand verification to see issuer, dates, source URLs,
   SHA-256, prior review and the scope of automated checks.
3. Search an exact phrase inside the filtered documents. Results preserve the source text and physical
   page, link back to its complete page, and paginate through every matching page. Quarantined files are
   excluded. Read failures remain explicit; partial searches report their missing files.
4. In the first question form, choose **Search local documents (exact phrase)** and enter e.g. `diesel`.
   It searches the whole acquired library, independently of the selected ticker. This is a lexical search,
   not natural-language reasoning or an AI answer. The first eight matches link to the reader; the library
   exposes all matches. A research-register ticker is never treated as proof of ETF membership.
5. Existing Evidence Desk passages link by their **original document SHA-256 and PDF page** to this reader.
   The 35 reviewed candidates retain their existing company identities, printed pages and verification
   metadata. CPKC remains gated for manual review in the general library.

## Structured data

| Data | What the browser exposes | Limitation retained |
|---|---|---|
| XIU holdings | Separate 12 and 13 November 2026 snapshots, 65 positions each, original asset classes, sectors, currencies and weights; totals 100.02% and 100.04% | No renormalization; the evidence case file stays on 12 November. No inferred historical attribution |
| IVV holdings | 509 positions, 12 November 2026, four missing weights | Unknown weights stay null; known sum 100.10% is not a verified complete total; not a SPY sleeve |
| SPY workbook | All source cells with coordinates, values and styles | Date/weight/unit mapping remains pending; not automatically treated as a validated holdings table |
| Bank of Canada | 3,736 dated observations; filter series and date | CAD per USD and percent remain distinct; no inversion/resampling or beta recomputation |
| Statistics Canada fuel prices | All 46,262 rows; geography/fuel/month filters, original cents/litre, scalar factors, STATUS and SYMBOL fields | Monthly observations are not weekly; suppressed/missing values are not filled |
| Statistics Canada API response | Download/navigation metadata | Clearly not financial observations |
| XESG/other extraction failures | Original reference, receipt and unavailable extraction state | No synthetic dataset or preview substitute |

Tables paginate 50 rows at a time. Complete extracted JSON exports preserve all fields, including raw
holdings columns not shown in the compact table. Documents also provide local JSON export. Original PDFs
remain in the research workspace; the frontend does not copy or automatically fetch their remote bytes.
Full visual verification of a PDF table, printed-page mapping and new citation approval are still separate work.

## Files created

| File | Purpose |
|---|---|
| `research/source_pipeline/build_frontend_catalog.py` | Offline exporter; checks original-object hashes, reuses immutable extraction bundles, atomically activates only a complete catalog |
| `research/source_pipeline/test_frontend_catalog.py` | Lossless/idempotent export, conflict, missing/empty catalog, hash and path-containment tests |
| `frontend/library-catalog.json` | Active portable metadata index of all 52 sources and 64 objects; no workstation paths or credentials |
| `frontend/research-data/.gitignore` | Keeps generated extraction content untracked |
| `frontend/research-data/<inventory-sha>/*.json` | 64 lazy-loaded extracted payloads plus immutable catalog snapshots; original downloaded documents are not copied |
| `frontend/library-data.js` | Local read adapter, catalog validation, extraction SHA-256 verification, exact text search, dataset/filter adapters |
| `frontend/library-render.js` | Escaped source metadata, statuses, text matches and tables; safe HTTP(S) links |
| `frontend/library.js` | Library interactions, source/file selection, physical pages, filters, pagination, errors/retry and quarantine review gate |
| `frontend/library.css` | Scoped responsive library/reader/table styling and keyboard focus |
| `frontend/library.test.mjs` | Actual-corpus integration tests, integrity failures, exact text offsets, dated holdings, units and safe rendering |
| `frontend/RESEARCH_LIBRARY.md` | This integration record and handoff |

## Existing files changed in this step

| File | Change |
|---|---|
| `frontend/index.html` | Early library entry, document-search choice, complete library panel, module/style links |
| `frontend/app.js` | Explicit local-document search in the existing question form; no agent/API configuration changes |
| `frontend/evidence-desk.js` | Link a reviewed passage to its exact local source hash/page |
| `frontend/evidence-browser-check.mjs` | Browser coverage for 52 sources, snapshot dates, documents, datasets, local chat search, quarantine, mobile and catalog errors |
| `frontend/README.md` | Link to this data-integration guide |

Existing changes elsewhere in Git predate this integration and were not reset. No production compute,
Lambda, agent, IAM or documentation files were changed by this step. Existing source inventory, downloads,
evidence catalogs and statistical preview data are unchanged.

## Build and verification

From the repository root, with the already-acquired research files present:

```sh
python3 -B research/source_pipeline/build_frontend_catalog.py --activate
python3 -m http.server 4173 --bind 127.0.0.1 --directory frontend
```

Open `http://127.0.0.1:4173`. Native module loading and SHA-256 verification require HTTP on localhost
or HTTPS; opening `index.html` via `file://` is not supported. There are no new dependencies.
The builder requires all 52 entries and a matching offline audit. `--activate` changes only the local
catalog pointer after successful checks. Without it, the active pointer stays unchanged. Conflicting
immutable files are rejected; older files/catalogs are never deleted. A future acquisition run creates
a separate version directory. Metadata-only export changes create a separate catalog snapshot while
reusing identical payloads. Research content is ignored in Git and must be built on each teammate's
machine from the local acquisition files. A Git checkout alone cannot provide the downloaded corpus.

```sh
python3 -B -m unittest discover -s research/source_pipeline -p 'test_frontend_catalog.py' -v
node --test frontend/frontend.test.mjs frontend/investigation-guide.test.mjs frontend/evidence-desk.test.mjs frontend/library.test.mjs
node frontend/evidence-browser-check.mjs
```

The Chrome check uses an installed browser, a temporary profile and a loopback server. External page
requests are blocked and counted. It checks browser exceptions, desktop/mobile widths, navigation,
both XIU dates, an exact CNR page link, fuel/FX filters, local chat search, CPKC quarantine and catalog retry.

## Still required before AWS / model integration

- Approve company-document identity, source provenance and new exact quotations in evidence_v2. Do not
  promote entire extracted pages to verified passages. Preserve `stock_return_direction = unknown`.
- Agree with the backend teammate on versioned source/document/dataset endpoints preserving these
  identities, verification fields and errors. Backend retrieval must join company evidence to dated
  constituent contexts; it must not reassign company passages directly to XIU.
- Validate structured mappings/units and refresh policies; resolve blocked/missing Brent/WTI and other
  required sources. Compute comparable constituent regressions, coverage and uncertainty before using
  the new data in attribution. The local research library does not calculate those results.
- Separately authorize S3 publication, Knowledge Base ingestion and live integration checks. All URLs in
  `frontend/config.js` remain unconfigured. No AWS availability is asserted by this local integration.
