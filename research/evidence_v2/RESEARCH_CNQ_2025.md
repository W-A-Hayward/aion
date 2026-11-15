# Canadian Natural Resources (CNQ.TO) — oil price exposure in the 2025 Annual Report

Research only. Not integrated into AWS, the production pipeline or the frontend.
Candidates: [`candidates_cnq_2025.csv`](candidates_cnq_2025.csv) ·
verification, context, tables and footnotes: [`candidates_cnq_2025.verification.json`](candidates_cnq_2025.verification.json).

## Source

| | |
|---|---|
| Issuer | Canadian Natural Resources Limited |
| Title | Canadian Natural 2025 Annual Report (year ended December 31, 2025), 118 PDF pages |
| Official URL | https://www.cnrl.com/content/uploads/2026/04/CNQ_2025-Annual-Report.pdf |
| SHA-256 | `497adbc4c8be70021f2974cfec6876fe058f3ea2dc384196f3c424f450e7dfe8` (recomputed; matches the acquisition receipt) |
| Provenance | Official issuer domain; path read from CNQ's financials page at acquisition (receipt). Not re-fetched in this batch. |
| Printed page | PDF page − 1 for every page used (checked against each page footer) |

## Strongest mechanisms (company-disclosed)

1. **Quantified price sensitivity.** A US$1.00/bbl change in WTI changes annualized cash flows from operating
   activities and net earnings by **$409 million each ($0.20 per basic share)**. Basis: Q4 2025 conditions and
   volumes, excluding mark-to-market on risk management, one variable at a time (Sensitivity Analysis, printed p. 53).
2. **Revenue indexed to benchmarks.** "Substantially all" production is sold on US-dollar benchmarks, crude on WTI
   and Brent; realized pricing "is reflective of the prevailing benchmark pricing".
3. **WCS heavy differential as a second price channel.** It narrowed from US$14.73 to US$11.10/bbl, which the company
   attributes to full-year TMX pipeline capacity and strong US Gulf Coast heavy-oil pricing. North America realized
   prices fell 7% versus WTI's 14%, "partially offset by a narrowing of the WCS Heavy Differential".
4. **Earnings volatility drivers.** Crude oil pricing is listed first, naming the WCS–WTI and WTI–Brent differentials.
5. **Hedging is periodic, not standing.** Commodity derivatives are used "periodically"; this page gives no crude
   volumes.

## Candidates

| ID | PDF / printed | Section | Company-disclosed text (abridged) | Kind |
|---|---|---|---|---|
| CNQ-2025-01 | 19 / 18 | MD&A — Product Prices | "The Company's realized product pricing is reflective of the prevailing benchmark pricing." | Mechanism |
| CNQ-2025-02 | 19 / 18 | MD&A — Summary of Quarterly Financial Results | "Crude oil pricing – … the impact of the WCS Heavy Differential from WTI … and … WTI and Brent…" | Earnings driver |
| CNQ-2025-03 | 21 / 20 | MD&A — Benchmark Commodity Prices | "Substantially all of the Company's production is sold based on US dollar benchmark pricing…" | Mechanism |
| CNQ-2025-04 | 21 / 20 | MD&A — Benchmark Commodity Prices table | "WTI … $ 64.77 $ 75.72 $ 77.61 Dated Brent … $ 69.02 … WCS Heavy Differential … $ 11.10 $ 14.73 $ 18.62" | Table rows (US$/bbl) |
| CNQ-2025-05 | 21 / 20 | MD&A — Benchmark Commodity Prices | "The narrowing of the WCS Heavy Differential … reflected full year takeaway capacity on the TMX pipeline…" | Differential cause |
| CNQ-2025-06 | 26 / 25 | MD&A — Realized Product Prices, North America | "…decreased 7% … primarily reflecting lower WTI benchmark pricing, partially offset by a narrowing of the WCS Heavy Differential." | Realized price |
| CNQ-2025-07 | 54 / 53 | MD&A — Sensitivity Analysis | "Crude oil – WTI US$1.00/bbl $ 409 $ 0.20 $ 409 $ 0.20" | Table row ($M; $/share) |
| CNQ-2025-08 | 96 / 95 | Note 18 — Commodity price risk management | "The Company periodically uses commodity derivative financial instruments…" | Mitigant |

The sensitivity table's four column headings, its basis paragraph and footnote (1), which refers to Note 18, are
preserved as anchors. The column order was checked visually on the rendered page.

## Facts versus our interpretation

- **Fact:** the $409M sensitivity and its stated basis, the benchmark and differential levels, the company's stated
  causes (TMX, Gulf Coast pricing) and its description of hedging.
- **Ours:** "strongest quantitative disclosure in the batch"; that the narrower WCS discount and FX cushioned realized
  prices; that the sensitivity is unhedged by default (only that this page shows no crude volumes).
- **Not established:** that CNQ's share price rises with oil. The disclosure is about operating cash flow on Q4 2025
  volumes, which is a different quantity from a stock return.

## Statistical validation needed

Saved notebook output (legacy, not re-run): CNQ.TO weekly oil beta 0.445, 95% range 0.347 to 0.543,
p ≈ 4×10⁻¹⁹; 0.435 with a market control. Strong association, consistent with the documented operating mechanism.
Still needed:

- re-run on current code;
- test whether the WCS–WTI differential adds explanatory power beyond WTI or Brent. WCS is not in the data contract,
  so a WCS series must be added first;
- test USD/CAD as a joint factor, since realized C$ prices depend on it.

## Verification

All 8 quotes occur exactly once on the stated page (PDFKit text layer). 2 match byte-for-byte; 6 match after
collapsing line breaks. All anchors were found on the page, and printed pages agree with both footer and offset.
pypdf agrees on 7 of 8. On CNQ-2025-05, pypdf reads "U S$11.10" (a kerning artifact, an inserted space); PDFKit and
the rendered page both read "US$11.10". This is recorded, not counted as a mismatch.
