# RBC (RY.TO) — oil-related exposure in the 2025 Annual Report

Research only. Not integrated into AWS, the production pipeline or the frontend.
Candidates: [`candidates_rbc_2025.csv`](candidates_rbc_2025.csv) (evidence_v2 importer format) ·
verification, context, tables and footnotes: [`candidates_rbc_2025.verification.json`](candidates_rbc_2025.verification.json).

## Source

| | |
|---|---|
| Issuer | Royal Bank of Canada |
| Title | Royal Bank of Canada Annual Report 2025 (fiscal year ended October 31, 2025), 246 PDF pages |
| Official URL | https://www.rbc.com/investor-relations/_assets-custom/pdf/ar_2025_e.pdf |
| SHA-256 | `a0e79381aea04b357ced6ed112c524ef102516631f62fe8860e2e6d0fbcfaecc` (recomputed; matches the acquisition receipt) |
| Provenance | Official issuer domain; href read from RBC's financial-information page at acquisition (receipt). Not re-fetched in this batch. |
| Printed page | PDF page − 2 for every page used (checked against each page footer) |

## Strongest mechanisms (company-disclosed)

1. **Direct credit exposure to the oil-and-gas sector, measured and small.** EAD $18,880M at October 31, 2025
   (2024: $19,107M) in Table 41; drawn loans and acceptances $6,352M (Table 72). Our arithmetic: about 0.8% of total
   EAD, 0.6% of total loans.
2. **Credit quality of that exposure: benign in FY2025.** Gross impaired oil-and-gas loans $28M (2024: $9M); PCL on
   impaired oil-and-gas loans $6M after a $51M net recovery in 2024 (Tables 73 and 74).
3. **Commodity prices feed the allowance models.** Commodity prices are a named input to expected-credit-loss models
   (Note 2), so oil shocks can move allowances through forward-looking scenarios.
4. **The energy downside scenario was retired in Q2 2025**, replaced by a trade-disruption scenario (Note 5).

Concentration framework (RBC-2025-01) is the lens, not an oil fact: RBC defines concentration risk as correlated
default within industry sectors.

## Candidates

| ID | PDF / printed | Section | Company-disclosed text (abridged; full text in CSV) | Kind |
|---|---|---|---|---|
| RBC-2025-01 | 78 / 76 | MD&A — Credit risk limits | "Concentration risk is defined as the risk arising from an overexposure in particular industry sectors…" | Framework |
| RBC-2025-02 | 79 / 77 | MD&A — Table 41 | "Oil and gas 6,377 8,671 1,520 – 2,312 18,880 6,365 … 19,107" | Table row (EAD, $M) |
| RBC-2025-03 | 130 / 128 | MD&A — Table 72 | "Oil and gas 6,352 6,362" | Table row ($M) |
| RBC-2025-04 | 131 / 129 | MD&A — Table 73 | "Consumer staples 115 138 Oil and gas 28 9 Financial services 213 120" | Table row ($M) |
| RBC-2025-05 | 132 / 130 | MD&A — Table 74 | "Oil and gas 6 (51)" | Table row ($M) |
| RBC-2025-06 | 156 / 154 | Note 2 — Use of forward-looking information | "…include, but are not limited to, unemployment rates, … commodity prices and Canadian housing prices." | Mechanism |
| RBC-2025-07 | 185 / 183 | Note 5 — Scenario design and weightings | "…we designed a trade disruption scenario to replace our energy sector scenario." | Mechanism |

Table units, column headings and footnotes are preserved in the sidecar. Table 41 is in millions of Canadian dollars
of exposure at default (Basel classes; undrawn amounts after credit conversion factors, footnote 3). Table 74's "(51)"
is a 2024 net recovery. The column order of Tables 41 and 74 was checked visually on rendered pages, because the
PDF text layer jumbles multi-level headers.

## Facts versus our interpretation

- **Fact:** the sector rows above, the ECL input list, and the scenario replacement.
- **Ours:** the percentages of total exposure, "benign" credit quality, and the reading that management judged trade
  disruption more relevant than an energy shock. None of these is an RBC statement.
- **Not supported here:** any claim that RBC's share price moves with oil. The documented direct channel is small.
  Indirect channels (Alberta consumers and businesses, energy-dependent commercial real estate, capital markets
  revenue) are plausible but not disclosed by sector in these pages.

## Statistical validation needed

Saved notebook output (legacy, not re-run): RY.TO weekly oil beta −0.020, 95% range −0.060 to +0.019, p = 0.31.
That is consistent with a small direct channel, but it is a historical association, not proof of the mechanism.
Next: re-run on current code; check stability across an oil downturn (2015-16 is outside the sample); test
asymmetry (beta_up / beta_down).

## Verification

All 7 quotes occur exactly once on the stated PDF page (PDFKit text layer, the team's `pdf_metadata.js`). 3 match
byte-for-byte; 4 match after collapsing line breaks. Every table title, unit line and footnote anchor was found on
the same page, and printed pages agree with both footer and offset. pypdf, an independent second extractor, agrees
on all 7. Reproduce with `python3 -B research/evidence_v2/build_oil_batch.py`.
