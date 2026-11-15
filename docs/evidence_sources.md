# Evidence document set

The documents for `compute/run_evidence.ipynb`. The files live in `data/manual_docs/` (git-ignored) and are
uploaded to `s3://cascade-s3-bucket/raw/manual_docs/` with `manifest_docs.csv`. Retrieved 2026-11-15 from the
issuers' own sites. The hashes identify the exact bytes processed; a re-download may differ (fact sheets are
updated quarterly).

| File | Ticker | Issuer / document | Source URL | Size | SHA-256 |
|---|---|---|---|---|---|
| `xom_10k_2025.pdf` | XOM | Exxon Mobil Corporation, Form 10-K for fiscal 2025 (SEC accession 0000034088-26-000045), 153 pages | [investor.exxonmobil.com](https://investor.exxonmobil.com/sec-filings/annual-reports/content/0000034088-26-000045/0000034088-26-000045.pdf) | 12.8 MB | `2dde67635a39370b66c4a6e6f4d6ee0e940d4a9f161b2089f1812353083d078b` |
| `tlt_fact_sheet.pdf` | TLT | BlackRock iShares, TLT fact sheet as of 2026-09-30 | [blackrock.com](https://www.blackrock.com/us/individual/literature/fact-sheet/tlt-ishares-20-year-treasury-bond-etf-fund-fact-sheet-en-us.pdf) | 123 KB | `9b724c5bb10d1159321f0f8bdda2bf0f20928a0441b608830caea34592cf34c6` |
| `boc_mpr_2026_07.pdf` | macro | Bank of Canada, Monetary Policy Report, July 2026 | [bankofcanada.ca](https://www.bankofcanada.ca/wp-content/uploads/2026/06/mpr-2026-07-15.pdf) | 1.9 MB | `18e2cd1e5e182b4a179453f6a5ba168a6f05b9a44c6f5d2444e7711769557fa9` |
| `boc_mpr_2026_04_in_focus_oil.html` | macro | Bank of Canada, MPR April 2026, "In focus: The war in the Middle East—Transmission channels and risks to inflation" | [bankofcanada.ca](https://www.bankofcanada.ca/publications/mpr/mpr-2026-04-29/in-focus-1/) | 160 KB | `86999ae0416c02d72e526a1492faa701edc5f49109037103e1e482b94d57060c` |

## Checks already done locally (no AWS, no model)

Run through the pipeline's own `extract_pages`, `passages_for_pages` and `prefilter`:

| File | Pages | Passages | Sent to the model | "oil" mentions |
|---|---|---|---|---|
| `xom_10k_2025.pdf` | 153 | 418 | 25 (per-document cap) | 319 |
| `tlt_fact_sheet.pdf` | 3 | 9 | 6 | 0 (rates channel: "Effective Duration: 14.63 yrs") |
| `boc_mpr_2026_07.pdf` | 47 | 61 | 25 | 57 |
| `boc_mpr_2026_04_in_focus_oil.html` | 1 | 13 | 11 | 15 |

The TLT fact sheet's effective duration (14.63 years, as of 2026-09-30) matches `compute/stats.py` `DURATION_YEARS`
and the data contract exactly.

## Not included, and why

- **Enbridge (ENB.TO):** Enbridge's investor-relations file host (`enbridge.gcs-web.com`) returned HTTP 403 to an
  automated download. Download the 2025 annual report or 10-K manually from enbridge.com, add it to the folder
  and add a row `file,ENB.TO,annual report,<url>` to `manifest_docs.csv`.
- **XIU constituents, Couche-Tard, XBB.TO, ZST.TO:** not in this first small set. XBB/ZST duration sources are
  cited in the data contract; add their issuer pages the same way.

The 40-word verbatim-excerpt check runs inside the evidence notebook (it needs the model's answers). Only
the excerpt's presence in the text is verified; the documents themselves were not otherwise audited.
