# Oil-exposure research batch 2025: RBC, CNQ, CPKC — comparative summary

23 evidence candidates from three 2025 annual reports, in the existing evidence_v2 schema, each linked to its own
company ticker. Every quote was re-verified on its original PDF page. Research only: no AWS, no production pipeline,
no frontend, no new downloads, nothing committed.

| Company | Ticker (universe) | Candidates | Source provenance | Saved oil beta (legacy, not re-run) |
|---|---|---|---|---|
| Royal Bank of Canada | RY.TO (core) | 7 | Official issuer domain | −0.020, 95% range [−0.060, +0.019], p = 0.31 |
| Canadian Natural Resources | CNQ.TO (extra) | 8 | Official issuer domain | +0.445, [0.347, 0.543], p ≈ 4×10⁻¹⁹ |
| CPKC | CP.TO (**not in universe**) | 8 | **Pending**: IR CDN, issuer link not yet established | none |

Reports: [RBC](RESEARCH_RBC_2025.md) · [CNQ](RESEARCH_CNQ_2025.md) · [CPKC](RESEARCH_CPKC_2025.md).

## Which mechanisms are documented, which are hypotheses

| Mechanism | RBC | CNQ | CPKC |
|---|---|---|---|
| Revenue indexed to oil benchmarks | — | **Documented** (WTI/Brent, US$) | **Documented, indirect** (diesel-indexed surcharge, ~10% of freight revenue) |
| Quantified price sensitivity | — | **Documented**: US$1/bbl WTI = $409M annual operating cash flow and net earnings | Partial: 2025 realized effect only (−$46M operating income) |
| Heavy-oil differential (WCS–WTI) | — | **Documented** (US$11.10; TMX narrowed it) | — |
| Fuel / energy as a cost | — | — | **Documented** ("significant portion" of operating costs; mitigation incomplete) |
| Energy-related volumes | — | — | **Documented**: 20% of freight revenue is energy, chemicals and plastics; volume direction not stated |
| Credit exposure to oil and gas | **Documented and measured**: EAD $18.9B (~0.8%), loans $6.4B; PCL $6M | — | — |
| Commodity prices in credit-loss models | **Documented** (ECL input; energy scenario retired Q2 2025) | — | — |
| Hedging / mitigation | — | Documented as periodic; no crude volumes on the cited page | Documented surcharge program, explicitly not complete |
| Share price rises/falls with oil | **Hypothesis only** | **Hypothesis only** (strongly suggested by operations) | **Hypothesis only** (sign ambiguous) |
| Indirect channels (regional economy, CRE, capital markets) | **Hypothesis**: not disclosed by sector | — | — |

## Where statistical validation is still needed

1. **Re-run** `compute/run_stats.ipynb` on current code. The betas above are legacy saved outputs, and the
   portfolio-return formula has since changed.
2. **CNQ:** test whether a WCS–WTI differential series adds explanatory power beyond Brent/WTI, and USD/CAD jointly.
   WCS is not in the data contract.
3. **RBC:** a small, insignificant beta is consistent with a small documented exposure. Test stability across a full
   oil downturn and asymmetry (beta_up / beta_down); indirect channels need evidence before any attribution.
4. **CPKC:** add CP.TO to the universe. Estimate Brent beta, asymmetry and lags, with a diesel/crack-spread control
   and an April 2025 break (carbon-tax repeal).
5. None of these regressions would turn operating evidence into a share-price direction. Keep the two separate in
   the catalog: operational passages stay `stock_return_direction = "unknown"`.

## How the evidence was verified

- SHA-256 of each PDF was recomputed and matched to its acquisition receipt.
- Every excerpt occurs **exactly once** on its stated PDF page in the macOS PDFKit text layer (the team's
  `source_documents/pdf_metadata.js`): 5 byte-exact, 18 after collapsing line breaks only.
- Table rows were checked against their table title, unit line, column headings and footnotes on the same page.
  Column order was confirmed visually on rendered pages for RBC Tables 41 and 74 and CNQ's sensitivity table.
- Printed page numbers agree with both the page footer and a per-document offset. CPKC's two-page spreads
  (PDF 3–13) were excluded.
- pypdf, an independent extractor, agrees on 22 of 23. The exception is a kerning artifact ("U S$11.10") in pypdf,
  not in the PDF.
- Each candidate's interpretation is prefixed "OUR INTERPRETATION (not issuer text)" and kept in a separate field
  from the company's words.

## Files (all new; no existing file modified)

| File | Purpose |
|---|---|
| `oil_batch_2025.py` | Single source of truth: 23 candidates, anchors, table metadata, our interpretations, hypotheses |
| `build_oil_batch.py` | Re-verifies everything against the PDFs; writes the CSVs and sidecars (exclusive create unless `--overwrite`) |
| `candidates_{rbc,cnq,cpkc}_2025.csv` | Candidates in the exact `import_candidates.FIELDS` format |
| `candidates_*_2025.verification.json` | Context before/after, tables, units, footnotes, provenance, verification record |
| `test_oil_batch.py` | 11 tests; the PDF re-check runs with `OIL_BATCH_PDF=1` |
| `RESEARCH_*_2025.md`, this file | Reports |

## Test results

`python3 -B -m unittest discover -s research/evidence_v2 -p 'test_*.py'`: **60 tests, all pass** (the 49 existing
plus 11 new); the PDF re-check is skipped by default.
`OIL_BATCH_PDF=1 python3 -B -m unittest research/evidence_v2/test_oil_batch.py`: **11 pass**, including
re-verification of all 23 quotes against the PDFs.
