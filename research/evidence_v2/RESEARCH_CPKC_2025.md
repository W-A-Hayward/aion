# CPKC (CP.TO) — fuel and energy exposure in the 2025 Annual Report

Research only. Not integrated into AWS, the production pipeline or the frontend.
Candidates: [`candidates_cpkc_2025.csv`](candidates_cpkc_2025.csv) ·
verification, context and units: [`candidates_cpkc_2025.verification.json`](candidates_cpkc_2025.verification.json).

> **Provenance pending.** The PDF was retrieved from `s21.q4cdn.com`, an investor-relations CDN, not from a CPKC
> domain. The acquisition review flagged it `provenance_manual_review`: the exact hyperlink from
> investor.cpkcr.com to this CDN URL must be confirmed and archived before the source counts as official. Until then
> every CPKC candidate is marked `pending_issuer_to_cdn_link` in its sidecar, and `url_verified` is False. The content
> is internally consistent with a CPKC Form 10-K. The receipt also lists an SEC EDGAR alternative
> (`cp-20251231.htm`), which was neither downloaded nor compared.

## Source

| | |
|---|---|
| Issuer | Canadian Pacific Kansas City Limited |
| Title | CPKC 2025 Annual Report, containing the Form 10-K for the year ended December 31, 2025; 142 PDF pages |
| URL used | https://s21.q4cdn.com/736796105/files/doc_financials/2025/ar/v2/CPKC-Annual-Report-2025-Final-Web.pdf |
| SHA-256 | `452856be75e538134f6f4f96eea4743d67d1c14eac8df4fec312adaa3bca911f` (recomputed; matches the acquisition receipt) |
| Currency | Canadian dollars: "All references to currency amounts included in this Annual Report on Form 10-K are in Canadian dollars unless specifically noted otherwise." (printed p. 26) |
| Printed page | PDF pages 3–13 are two-page spreads. From PDF 14 onward, printed = PDF page + 9, confirmed against every footer. All candidates are on PDF pages 21 or later. |

## Strongest mechanisms (company-disclosed)

1. **Fuel surcharge pass-through, indexed to diesel.** Surcharges are "based primarily on the price of On-Highway
   Diesel" (PEMEX fuel in Mexico) and are "a function of freight volumes and fuel prices". They make up about **10% of
   freight revenues**, and fuel-price volatility "may adversely or positively impact revenues".
2. **Fuel as a significant cost, with incomplete mitigation.** Fuel expense is "a significant portion" of operating
   costs. The company "cannot be certain that it will always be able to fully mitigate rising or elevated fuel prices"
   through the program. "Worldwide oil demand" is listed among fuel-price drivers, alongside refinery capacity and
   others.
3. **Net 2025 effect of lower fuel prices: unfavourable.** Operating income −$46M. Revenues fell $205M (lower
   surcharges, the end of the carbon levy, recovery timing) and operating expenses fell $159M.
4. **Energy-related freight.** Energy, chemicals and plastics is about 20% of freight revenues (43% of merchandise):
   fuel oil, LPG, gasoline and other refined products.

## Candidates

| ID | PDF / printed | Section (Form 10-K) | Company-disclosed text (abridged) | Kind |
|---|---|---|---|---|
| CPKC-2025-01 | 23 / 32 | Part I, Item 1 — Fuel Cost Adjustment Program | "The short-term volatility in fuel prices may adversely or positively impact revenues…" | Mechanism |
| CPKC-2025-02 | 23 / 32 | Part I, Item 1 — Fuel Cost Adjustment Program | "Fuel surcharge revenues … are based primarily on the price of On-Highway Diesel…" | Mechanism |
| CPKC-2025-03 | 23 / 32 | Part I, Item 1 — Fuel Cost Adjustment Program | "Fuel surcharge revenues accounted for approximately 10% of the Company's Freight revenues in 2025." | Materiality |
| CPKC-2025-04 | 30 / 39 | Part I, Item 1A — Risk Factors | "The Company is affected by fluctuating fuel prices. Fuel expense constitutes a significant portion…" | Cost risk |
| CPKC-2025-05 | 30 / 39 | Part I, Item 1A — Risk Factors | "…cannot be certain that it will always be able to fully mitigate rising or elevated fuel prices…" | Mitigation limit |
| CPKC-2025-06 | 55 / 64 | Part II, Item 7 — Operating Expenses, Fuel | "…the impact of lower fuel price of $159 million, which includes lower carbon tax expense…" | Cost (C$M) |
| CPKC-2025-07 | 57 / 66 | Part II, Item 7 — Impact of Fuel Price on Earnings | "In 2025, the unfavourable impact of fuel prices on "Operating income" was $46 million…" | Net effect (C$M) |
| CPKC-2025-08 | 21 / 30 | Part I, Item 1 — Energy, Chemicals and Plastics | "…represented approximately 43% of merchandise revenues and 20% of total Freight revenues in 2025…" | Freight mix |

## Facts versus our interpretation

- **Fact:** the surcharge mechanism and its 10% share, the risk-factor language, the 2025 −$46M / −$205M / −$159M
  figures, and the 20% energy, chemicals and plastics share.
- **Ours:** that the link to crude runs crude → diesel → surcharge, with refining margins and lags in between; that
  the $159M saving mixes fuel price with the carbon-tax repeal; and that cheaper oil is not automatically good for the
  railway in a given year.
- **Not established:** any direction for CP.TO's share price. The 2025 data shows one sign for falling prices, driven
  partly by one-off carbon-levy and timing effects, and the risk factor shows the opposite sign for rising prices.
  The company itself describes the revenue effect as two-way.

## Statistical validation needed

CP.TO is **not in the data contract's universe**, so no beta exists. To test:

- add it to the universe and estimate its Brent beta, up/down asymmetry and lagged effects (surcharge recovery lags
  the fuel price);
- add a diesel or crack-spread control, since surcharges index to diesel, not crude;
- treat April 2025 (carbon-tax repeal) as a structural break.

## Verification

All 8 quotes occur exactly once on the stated page (PDFKit text layer), all after collapsing line breaks; mixed
straight and curly apostrophes are preserved exactly as printed. All anchors were found, and printed pages agree with
both footer and offset. pypdf agrees on all 8. Quote verification is independent of the provenance question above.
