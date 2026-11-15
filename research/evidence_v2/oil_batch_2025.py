"""Research batch: oil-exposure evidence candidates from the RBC, CNQ and CPKC 2025 annual reports.

Single source of truth for the batch. Each candidate separates:
  - `excerpt`: the company's own words, copied from the PDF text layer with line breaks collapsed to single spaces;
  - `interpretation`: OUR reading, never attributed to the issuer;
  - `anchors`: table titles, units, column headings and footnotes that must appear on the same PDF page,
    so a table row is never quoted without the headings that give its numbers meaning.

Research only. Nothing here infers a stock-return direction; every candidate is operational evidence with
stock_return_direction "unknown". build_oil_batch.py verifies every excerpt and anchor against the PDFs.
"""

RUN_DIR = "../source_documents/runs/20261115T131702Z_d4fbb4fa"

# Acquisition receipt id -> subject ticker, printed-page rule, provenance note.
SOURCES = {
    "RBC_2025_EN": {
        "ticker": "RY.TO",
        "printed_page_offset": -2,  # printed = PDF page - 2 throughout the MD&A and statements used here
        "footer_patterns": [r"(\d{1,3}) Royal Bank of Canada: Annual Report 2025",
                            r"Royal Bank of Canada: Annual Report 2025 (\d{1,3})"],
        "provenance_status": "official_issuer_url_retrieved",
        "provenance_note": "PDF retrieved from www.rbc.com, the issuer's own domain; exact href read from the "
                           "issuer's financial-information page (acquisition receipt). Not re-fetched in this batch.",
    },
    "CNQ_2025_EN": {
        "ticker": "CNQ.TO",
        "printed_page_offset": -1,
        "footer_patterns": [r"(\d{1,3}) Canadian Natural 2025 Annual Report",
                            r"Canadian Natural 2025 Annual Report (\d{1,3})"],
        "provenance_status": "official_issuer_url_retrieved",
        "provenance_note": "PDF retrieved from www.cnrl.com, the issuer's own domain; exact path read from the "
                           "issuer's financials page (acquisition receipt). Not re-fetched in this batch.",
    },
    "CPKC_2025_EN": {
        "ticker": "CP.TO",
        "printed_page_offset": 9,  # PDF pages 14+ hold one printed page each; 3-13 are two-page spreads
        "spread_pdf_pages": list(range(3, 14)),
        "footer_patterns": [r"(\d{1,3}) / CPKC 2025 ANNUAL REPORT", r"CPKC 2025 ANNUAL REPORT / (\d{1,3})"],
        "provenance_status": "pending_issuer_to_cdn_link",
        "provenance_note": "PROVENANCE PENDING. The PDF was retrieved from s21.q4cdn.com (an investor-relations CDN), "
                           "not from a CPKC domain. The acquisition review (metadata_review.json, status "
                           "provenance_manual_review) requires confirming and archiving the exact hyperlink from "
                           "investor.cpkcr.com to this CDN URL. Until then, treat the issuer-to-file link as "
                           "unestablished. Content is internally consistent with a CPKC Form 10-K. A regulatory "
                           "alternative is listed on the receipt (SEC EDGAR cp-20251231.htm) but was not "
                           "downloaded or compared.",
    },
}

CANDIDATES = [
    # ------------------------------------------------------------------ RBC: credit exposure to oil and gas
    {
        "id": "RBC-2025-01", "source": "RBC_2025_EN", "pdf_page": 78, "printed_page": "76",
        "section": "Management's Discussion and Analysis — Credit risk — Credit risk limits",
        "channel": "credit_concentration_policy", "form": "narrative",
        "excerpt": "Concentration risk is defined as the risk arising from an overexposure in particular industry "
                   "sectors, countries, or credit products within the portfolio, reflecting the potential for "
                   "credit deterioration and default to be relatively highly correlated.",
        "anchors": ["Credit risk limits",
                    "Credit concentration limits are reviewed on a regular basis after considering business, "
                    "economic, financial and regulatory environments."],
        "interpretation": "Framework, not oil-specific: RBC treats industry-sector overexposure as a correlated-default "
                          "risk. It is the lens for reading the oil-and-gas rows in Tables 41 and 72-74.",
    },
    {
        "id": "RBC-2025-02", "source": "RBC_2025_EN", "pdf_page": 79, "printed_page": "77",
        "section": "Management's Discussion and Analysis — Credit risk exposure by portfolio, sector and geography (Table 41)",
        "channel": "oil_gas_credit_exposure", "form": "table_row",
        "excerpt": "Oil and gas 6,377 8,671 1,520 – 2,312 18,880 6,365 8,688 2,002 – 2,052 19,107",
        "anchors": ["Credit risk exposure by portfolio, sector and geography Table 41",
                    "(Millions of Canadian dollars)", "Undrawn", "Derivatives",
                    "Total wholesale $ 832,621 $ 206,334 $ 36,246 $ 195,795 $ 133,972 $ 1,404,968",
                    "Total exposure (1) $ 1,440,654 $ 465,727 $ 36,410 $ 195,795 $ 133,972 $ 2,272,558",
                    "EAD for undrawn credit commitments and other off-balance sheet amounts are reported after "
                    "the application of credit conversion factors."],
        "table": {
            "title": "Credit risk exposure by portfolio, sector and geography (Table 41)",
            "units": "Millions of Canadian dollars; exposure at default (EAD) under Basel regulatory classes",
            "as_at": "October 31, 2025 and October 31, 2024",
            "columns": ["2025 on-balance sheet amount", "2025 undrawn", "2025 other off-balance sheet (4)",
                        "2025 repo-style transactions", "2025 derivatives", "2025 total exposure",
                        "2024 on-balance sheet amount", "2024 undrawn", "2024 other off-balance sheet (4)",
                        "2024 repo-style transactions", "2024 derivatives", "2024 total exposure"],
            "values": ["6,377", "8,671", "1,520", "–", "2,312", "18,880",
                       "6,365", "8,688", "2,002", "–", "2,052", "19,107"],
            "footnotes": ["(1) Excludes securitization, banking book equities and other assets not subject to the "
                          "standardized or IRB approach.",
                          "(3) EAD for undrawn credit commitments and other off-balance sheet amounts are reported "
                          "after the application of credit conversion factors.",
                          "(4) Includes other off-balance sheet exposures such as letters of credit and guarantees.",
                          "(5) Counterparty credit risk EAD reflects exposure amounts after netting."],
            "column_mapping_check": "Visual check of the rendered page confirms the column order above.",
        },
        "interpretation": "Disclosed fact: oil-and-gas EAD of $18,880 million at October 31, 2025 (2024: $19,107 "
                          "million). Our arithmetic, not RBC's: about 0.83% of total EAD ($2,272,558 million) and "
                          "1.34% of total wholesale EAD. Almost half (8,671) is undrawn commitments, which could be "
                          "drawn under stress.",
    },
    {
        "id": "RBC-2025-03", "source": "RBC_2025_EN", "pdf_page": 130, "printed_page": "128",
        "section": "Management's Discussion and Analysis — Supplementary information — Loans and acceptances by portfolio and sector (Table 72)",
        "channel": "oil_gas_credit_exposure", "form": "table_row",
        "excerpt": "Oil and gas 6,352 6,362",
        "anchors": ["Loans and acceptances by portfolio and sector As at October 31 (Millions of Canadian dollars) 2025 Table 72",
                    "Wholesale $ 397,190 $ 360,474", "Total loans and acceptances $ 1,049,534 $ 987,452"],
        "table": {
            "title": "Loans and acceptances by portfolio and sector (Table 72)",
            "units": "Millions of Canadian dollars", "as_at": "October 31",
            "columns": ["2025", "2024"], "values": ["6,352", "6,362"], "footnotes": [],
        },
        "interpretation": "Disclosed fact: drawn oil-and-gas loans and acceptances of $6,352 million (2024: $6,362 "
                          "million). Our arithmetic: about 0.61% of total loans and acceptances and 1.6% of "
                          "wholesale loans. Flat year over year while total loans grew about 6%.",
    },
    {
        "id": "RBC-2025-04", "source": "RBC_2025_EN", "pdf_page": 131, "printed_page": "129",
        "section": "Management's Discussion and Analysis — Supplementary information — Gross impaired loans by portfolio and geography (Table 73)",
        "channel": "oil_gas_credit_quality", "form": "table_row",
        "excerpt": "Consumer staples 115 138 Oil and gas 28 9 Financial services 213 120",
        "anchors": ["Gross impaired loans by portfolio and geography As at October 31 (Millions of Canadian dollars, "
                    "except for percentage amounts) 2025 Table 73",
                    "Total GIL (2) $ 8,682 $ 5,867"],
        "table": {
            "title": "Gross impaired loans by portfolio and geography (Table 73), total-bank section",
            "units": "Millions of Canadian dollars", "as_at": "October 31",
            "columns": ["2025", "2024"], "values": ["28", "9"],
            "footnotes": ["The Oil and gas row appears twice on the page (total bank, then Canada, both 28 / 9); "
                          "the excerpt includes neighbouring rows to pin the total-bank occurrence."],
        },
        "interpretation": "Disclosed fact: gross impaired oil-and-gas loans rose from $9 million to $28 million. Our "
                          "reading: small in absolute terms (0.3% of total GIL of $8,682 million) and not a sign of "
                          "sector stress at fiscal year-end.",
    },
    {
        "id": "RBC-2025-05", "source": "RBC_2025_EN", "pdf_page": 132, "printed_page": "130",
        "section": "Management's Discussion and Analysis — Supplementary information — Provision for credit losses by portfolio and geography (Table 74)",
        "channel": "oil_gas_credit_quality", "form": "table_row",
        "excerpt": "Oil and gas 6 (51)",
        "anchors": ["Provision for credit losses by portfolio and geography For the year ended October 31 "
                    "(Millions of Canadian dollars, except for percentage amounts) 2025 Table 74",
                    "Total PCL on impaired loans $ 3,734 $ 2,620"],
        "table": {
            "title": "Provision for credit losses by portfolio and geography (Table 74)",
            "units": "Millions of Canadian dollars", "period": "For the year ended October 31",
            "columns": ["2025", "2024"], "values": ["6", "(51)"],
            "footnotes": ["(51) is in parentheses: a net recovery (negative provision) in fiscal 2024.",
                          "Visual check of the rendered page confirms 2025 is the left (shaded) column."],
        },
        "interpretation": "Disclosed fact: PCL on impaired oil-and-gas loans of $6 million in fiscal 2025 after a "
                          "$51 million net recovery in 2024. Oil-and-gas credit costs were negligible in both years.",
    },
    {
        "id": "RBC-2025-06", "source": "RBC_2025_EN", "pdf_page": 156, "printed_page": "154",
        "section": "Note 2 Summary of material accounting policies, estimates and judgments — Allowance for credit losses — Use of forward-looking information",
        "channel": "ecl_commodity_price_input", "form": "narrative",
        "excerpt": "Macroeconomic variables used in our expected credit loss models include, but are not limited to, "
                   "unemployment rates, gross domestic product growth rates, equity return indices, commodity "
                   "prices and Canadian housing prices.",
        "anchors": ["Use of forward-looking information",
                    "Note 2 Summary of material accounting policies, estimates and judgments"],
        "interpretation": "Mechanism: commodity prices are an input to RBC's expected-credit-loss models, so an oil "
                          "price shock can change allowances through forward-looking scenarios. RBC does not say "
                          "how large that effect is or which commodities are used.",
    },
    {
        "id": "RBC-2025-07", "source": "RBC_2025_EN", "pdf_page": 185, "printed_page": "183",
        "section": "Note 5 Loans and allowance for credit losses — Key inputs and assumptions — Scenario design and weightings",
        "channel": "ecl_scenario_design", "form": "narrative",
        "excerpt": "During Q2 2025, in response to U.S. international trade policy, we designed a trade disruption "
                   "scenario to replace our energy sector scenario.",
        "anchors": ["Key inputs and assumptions", "Scenario design and weightings"],
        "interpretation": "Disclosed fact: RBC had an energy-sector downside scenario and replaced it in Q2 2025. "
                          "Our reading: management judged trade disruption a more relevant downside than an energy "
                          "shock for fiscal 2025 allowances. This is not evidence that energy risk disappeared.",
    },
    # ------------------------------------------------------------------ CNQ: benchmark prices and sensitivity
    {
        "id": "CNQ-2025-01", "source": "CNQ_2025_EN", "pdf_page": 19, "printed_page": "18",
        "section": "Management's Discussion and Analysis — Product Prices",
        "channel": "realized_price_benchmark_linkage", "form": "narrative",
        "excerpt": "The Company's realized product pricing is reflective of the prevailing benchmark pricing.",
        "anchors": ["PRODUCT PRICES"],
        "interpretation": "Management statement that realized prices follow benchmarks. It establishes the "
                          "transmission from WTI/Brent to revenue, not its size.",
    },
    {
        "id": "CNQ-2025-02", "source": "CNQ_2025_EN", "pdf_page": 19, "printed_page": "18",
        "section": "Management's Discussion and Analysis — Summary of Quarterly Financial Results",
        "channel": "earnings_volatility_drivers", "form": "narrative",
        "excerpt": "Crude oil pricing – Fluctuations in global supply/demand including crude oil production levels "
                   "from OPEC+ and its impact on world supply, the impact of geopolitical and market uncertainties "
                   "(including those due to the conflicts in the Middle East, Ukraine and Venezuela, and the impacts "
                   "of ongoing tariff and trade uncertainty) on worldwide benchmark pricing, the impact of shale oil "
                   "production in North America, the impact of the start-up of the Trans Mountain Expansion "
                   "(\"TMX\") pipeline in 2024, the impact of the WCS Heavy Differential from WTI in North America, "
                   "and the impact of the differential between WTI and Brent benchmark pricing in the "
                   "International segments.",
        "anchors": ["Volatility in the quarterly net earnings over the eight most recently completed quarters was "
                    "primarily due to:"],
        "interpretation": "Management attributes quarterly net-earnings volatility first to crude oil pricing, "
                          "naming both the WCS-WTI and WTI-Brent differentials. This is about earnings volatility, "
                          "not share-price behaviour.",
    },
    {
        "id": "CNQ-2025-03", "source": "CNQ_2025_EN", "pdf_page": 21, "printed_page": "20",
        "section": "Management's Discussion and Analysis — Business Environment — Benchmark Commodity Prices",
        "channel": "benchmark_price_linkage", "form": "narrative",
        "excerpt": "Substantially all of the Company's production is sold based on US dollar benchmark pricing, with "
                   "crude oil marketed based on WTI and Brent indices, and natural gas marketed using a diversified "
                   "mix of AECO- and NYMEX-based pricing.",
        "anchors": ["BENCHMARK COMMODITY PRICES",
                    "The Company's realized prices are directly impacted by fluctuations in foreign exchange rates"],
        "interpretation": "Direct price channel: crude revenue is indexed to WTI and Brent in US dollars, so "
                          "realized prices in C$ also depend on USD/CAD (the next sentence on the page says so).",
    },
    {
        "id": "CNQ-2025-04", "source": "CNQ_2025_EN", "pdf_page": 21, "printed_page": "20",
        "section": "Management's Discussion and Analysis — Business Environment — Benchmark Commodity Prices (table)",
        "channel": "benchmark_prices_and_differentials", "form": "table_row",
        "excerpt": "WTI benchmark price (US$/bbl) $ 64.77 $ 75.72 $ 77.61 Dated Brent benchmark price (US$/bbl) "
                   "$ 69.02 $ 80.75 $ 82.61 WCS Heavy Differential from WTI (US$/bbl) $ 11.10 $ 14.73 $ 18.62",
        "anchors": ["BENCHMARK COMMODITY PRICES", "(Yearly average) 2025 2024 2023"],
        "table": {
            "title": "Benchmark Commodity Prices", "units": "US$ per barrel, yearly average",
            "columns": ["2025", "2024", "2023"],
            "values": {"WTI": ["64.77", "75.72", "77.61"], "Dated Brent": ["69.02", "80.75", "82.61"],
                       "WCS Heavy Differential from WTI": ["11.10", "14.73", "18.62"]},
            "footnotes": [],
        },
        "interpretation": "Disclosed benchmark levels. Our arithmetic: WTI fell US$10.95 (-14%) while the WCS "
                          "discount narrowed US$3.63, so heavy-oil realizations fell less than WTI.",
    },
    {
        "id": "CNQ-2025-05", "source": "CNQ_2025_EN", "pdf_page": 21, "printed_page": "20",
        "section": "Management's Discussion and Analysis — Business Environment — Benchmark Commodity Prices",
        "channel": "wcs_differential", "form": "narrative",
        "excerpt": "The WCS Heavy Differential averaged US$11.10 per bbl for 2025 compared with US$14.73 per bbl for "
                   "2024 (2023 – US$18.62 per bbl). The narrowing of the WCS Heavy Differential for 2025 from 2024 "
                   "primarily reflected full year takeaway capacity on the TMX pipeline and strong US Gulf Coast "
                   "heavy oil pricing.",
        "anchors": ["BENCHMARK COMMODITY PRICES"],
        "interpretation": "Company-stated cause of the narrower differential: TMX pipeline capacity and US Gulf "
                          "Coast heavy-oil demand. Infrastructure, not just the WTI level, drives Canadian "
                          "heavy-oil realizations.",
    },
    {
        "id": "CNQ-2025-06", "source": "CNQ_2025_EN", "pdf_page": 26, "printed_page": "25",
        "section": "Management's Discussion and Analysis — Realized Product Prices – Exploration and Production — North America",
        "channel": "realized_price", "form": "narrative",
        "excerpt": "North America realized crude oil and NGLs prices decreased 7% to average $70.90 per bbl for 2025 "
                   "from $76.37 per bbl for 2024 (2023 – $70.51 per bbl), primarily reflecting lower WTI benchmark "
                   "pricing, partially offset by a narrowing of the WCS Heavy Differential.",
        "anchors": ["REALIZED PRODUCT PRICES – EXPLORATION AND PRODUCTION", "North America"],
        "interpretation": "Both channels at work in one sentence: realized C$ prices fell 7% versus a 14% fall in "
                          "US$ WTI, with the narrower WCS discount (and FX) cushioning the decline.",
    },
    {
        "id": "CNQ-2025-07", "source": "CNQ_2025_EN", "pdf_page": 54, "printed_page": "53",
        "section": "Management's Discussion and Analysis — Other — Sensitivity Analysis",
        "channel": "price_sensitivity", "form": "table_row",
        "excerpt": "Crude oil – WTI US$1.00/bbl $ 409 $ 0.20 $ 409 $ 0.20",
        "anchors": ["SENSITIVITY ANALYSIS",
                    "The following table is indicative of the annualized sensitivities of cash flows from operating "
                    "activities and net earnings due to changes in certain key variables.",
                    "The analysis is based on business conditions and sales volumes during the fourth quarter of "
                    "2025, excluding mark-to-market gains (losses) on risk management activities and is not "
                    "necessarily indicative of future results.",
                    "Each separate line item in the sensitivity analysis shows the effect of a change in that "
                    "variable only with all other variables being held constant.",
                    "($ millions)", "Price changes"],
        "table": {
            "title": "Sensitivity Analysis",
            "units": "Annualized; $ millions and $ per common share (basic)",
            "basis": "Fourth-quarter 2025 business conditions and sales volumes; excludes mark-to-market on risk "
                     "management; one variable at a time",
            "columns": ["Cash flows from operating activities ($ millions)",
                        "Cash flows from operating activities (per common share, basic)",
                        "Net earnings ($ millions)", "Net earnings (per common share, basic)"],
            "values": ["409", "0.20", "409", "0.20"],
            "footnotes": ["(1) on other rows: For details of financial instruments in place, refer to note 18."],
            "column_mapping_check": "Visual check of the rendered page confirms the column order above.",
        },
        "interpretation": "Strongest quantitative disclosure in the batch: a US$1.00/bbl change in WTI changes "
                          "annualized operating cash flow and net earnings by about $409 million each. This is "
                          "operating sensitivity on Q4 2025 volumes, not a share-price beta.",
    },
    {
        "id": "CNQ-2025-08", "source": "CNQ_2025_EN", "pdf_page": 96, "printed_page": "95",
        "section": "Note 18 Financial Instruments — Financial Risk Factors — a) Market risk — Commodity price risk management",
        "channel": "hedging_policy", "form": "narrative",
        "excerpt": "The Company periodically uses commodity derivative financial instruments to manage its exposure to "
                   "commodity price risk associated with the sale of its future crude oil and natural gas "
                   "production, and with natural gas purchases.",
        "anchors": ["COMMODITY PRICE RISK MANAGEMENT",
                    "These financial instruments are entered into solely for hedging purposes and are not used for "
                    "speculative purposes."],
        "interpretation": "Possible mitigant. 'Periodically' and the absence of crude-oil contract volumes on this "
                          "page mean we cannot assume the WTI sensitivity is hedged. The $409M figure excludes "
                          "mark-to-market on risk management by construction.",
    },
    # ------------------------------------------------------------------ CPKC: fuel cost and surcharge pass-through
    {
        "id": "CPKC-2025-01", "source": "CPKC_2025_EN", "pdf_page": 23, "printed_page": "32",
        "section": "Form 10-K Part I, Item 1. Business — Fuel Cost Adjustment Program",
        "channel": "fuel_surcharge_pass_through", "form": "narrative",
        "excerpt": "The short-term volatility in fuel prices may adversely or positively impact revenues. The Company "
                   "employs a fuel cost adjustment program designed to respond to fluctuations in fuel prices and "
                   "help reduce volatility to changing fuel prices.",
        "anchors": ["Fuel Cost Adjustment Program"],
        "interpretation": "Two-way revenue effect stated by the company: fuel-price volatility can raise or lower "
                          "revenues; the surcharge program is the mechanism, not a guarantee of full pass-through.",
    },
    {
        "id": "CPKC-2025-02", "source": "CPKC_2025_EN", "pdf_page": 23, "printed_page": "32",
        "section": "Form 10-K Part I, Item 1. Business — Fuel Cost Adjustment Program",
        "channel": "fuel_surcharge_pass_through", "form": "narrative",
        "excerpt": "Fuel surcharge revenues are earned on individual shipments and are based primarily on the price "
                   "of On-Highway Diesel in Canada and the U.S. and the public fuel price for Petróleos Mexicanos "
                   "(\"PEMEX\") TAR Irapuato in Mexico. As such, fuel surcharge revenues are a function of freight "
                   "volumes and fuel prices.",
        "anchors": ["Fuel Cost Adjustment Program"],
        "interpretation": "Surcharges are indexed to diesel (and PEMEX fuel in Mexico), not to crude directly. Any "
                          "link to Brent runs crude -> refined diesel -> surcharge, with refining margins and lags "
                          "in between.",
    },
    {
        "id": "CPKC-2025-03", "source": "CPKC_2025_EN", "pdf_page": 23, "printed_page": "32",
        "section": "Form 10-K Part I, Item 1. Business — Fuel Cost Adjustment Program",
        "channel": "fuel_surcharge_materiality", "form": "narrative",
        "excerpt": "Fuel surcharge revenues accounted for approximately 10% of the Company's Freight revenues in 2025.",
        "anchors": ["Fuel Cost Adjustment Program"],
        "interpretation": "Materiality: about a tenth of freight revenue moves with fuel prices through the "
                          "surcharge.",
    },
    {
        "id": "CPKC-2025-04", "source": "CPKC_2025_EN", "pdf_page": 30, "printed_page": "39",
        "section": "Form 10-K Part I, Item 1A. Risk Factors — The Company is affected by fluctuating fuel prices",
        "channel": "fuel_cost", "form": "narrative",
        "excerpt": "The Company is affected by fluctuating fuel prices. Fuel expense constitutes a significant portion "
                   "of the Company’s operating costs. Fuel prices can be subject to dramatic fluctuations and "
                   "significant price increases could have a material adverse effect on the Company's results of "
                   "operations.",
        "anchors": [],
        "interpretation": "Cost channel stated as a risk factor: higher fuel prices are an adverse risk to results.",
    },
    {
        "id": "CPKC-2025-05", "source": "CPKC_2025_EN", "pdf_page": 30, "printed_page": "39",
        "section": "Form 10-K Part I, Item 1A. Risk Factors — The Company is affected by fluctuating fuel prices",
        "channel": "fuel_surcharge_limits", "form": "narrative",
        "excerpt": "The Company currently employs a fuel cost adjustment program to help reduce volatility in changing "
                   "fuel prices, but the Company cannot be certain that it will always be able to fully mitigate "
                   "rising or elevated fuel prices through this program. Factors affecting fuel prices include "
                   "worldwide oil demand, international geopolitics, weather, refinery capacity, supplier and "
                   "upstream outages, unplanned infrastructure failures, environmental and sustainability policies, "
                   "and labour and political instability.",
        "anchors": ["The Company is affected by fluctuating fuel prices."],
        "interpretation": "Pass-through is incomplete by the company's own account, and fuel prices depend on "
                          "refinery capacity and other factors besides crude. This is why a CP.TO oil beta could be "
                          "near zero or unstable.",
    },
    {
        "id": "CPKC-2025-06", "source": "CPKC_2025_EN", "pdf_page": 55, "printed_page": "64",
        "section": "Form 10-K Part II, Item 7. Management's Discussion and Analysis — Operating Expenses — Fuel",
        "channel": "fuel_cost", "form": "narrative",
        "excerpt": "Fuel expense consists primarily of fuel used by locomotives and includes provincial, state, and "
                   "federal fuel taxes. The decrease in Fuel expense was primarily due to the impact of lower fuel "
                   "price of $159 million, which includes lower carbon tax expense due to the elimination of the "
                   "Canadian federal carbon tax program effective April 1, 2025.",
        "anchors": [],
        "unit_basis": "Canadian dollars: Form 10-K p. 26 (PDF 17) states 'All references to currency amounts "
                      "included in this Annual Report on Form 10-K are in Canadian dollars unless specifically "
                      "noted otherwise.' Fuel expense was $1,731 million in 2025 (Operating Expenses table, PDF 54).",
        "interpretation": "The $159 million cost saving mixes the commodity effect with the end of the Canadian "
                          "federal carbon tax, so it overstates a pure fuel-price effect.",
    },
    {
        "id": "CPKC-2025-07", "source": "CPKC_2025_EN", "pdf_page": 57, "printed_page": "66",
        "section": "Form 10-K Part II, Item 7. Management's Discussion and Analysis — Impact of Fuel Price on Earnings",
        "channel": "fuel_price_net_impact", "form": "narrative",
        "excerpt": "In 2025, the unfavourable impact of fuel prices on \"Operating income\" was $46 million. Lower fuel "
                   "prices, which includes lower carbon levy surcharge revenue due to the elimination of the "
                   "Canadian federal carbon tax program effective April 1, 2025, and the unfavourable impact of the "
                   "timing of recoveries under the Company's fuel cost adjustment program, resulted in a decrease in "
                   "\"Total revenues\" of $205 million from 2024. Lower fuel prices resulted in a decrease in Total "
                   "operating expenses of $159 million from 2024.",
        "anchors": ["Impact of Fuel Price on Earnings",
                    "As fuel prices fluctuate, there will be an impact on earnings due to the timing of recoveries "
                    "from the Company's fuel cost adjustment program"],
        "unit_basis": "Canadian dollars (Form 10-K p. 26 currency statement).",
        "interpretation": "The key nuance: in 2025, LOWER fuel prices were net UNFAVOURABLE to operating income "
                          "(-$46M) because surcharge revenue fell faster than fuel cost ($205M vs $159M), partly "
                          "from recovery timing and the carbon-levy change. Cheaper oil is not automatically good "
                          "for this railway in a given year.",
    },
    {
        "id": "CPKC-2025-08", "source": "CPKC_2025_EN", "pdf_page": 21, "printed_page": "30",
        "section": "Form 10-K Part I, Item 1. Business — Energy, Chemicals and Plastics",
        "channel": "energy_freight_mix", "form": "narrative",
        "excerpt": "The Company’s Energy, chemicals and plastics business represented approximately 43% of merchandise "
                   "revenues and 20% of total Freight revenues in 2025. The Company moves energy products consisting "
                   "of commodities such as fuel oil, liquefied petroleum gas (\"L.P.G.\"), gasoline, and other "
                   "refined energy products.",
        "anchors": ["Energy, Chemicals and Plastics"],
        "interpretation": "Volume channel: about a fifth of freight revenue is energy, chemicals and plastics, mostly "
                          "refined products and LPG. Whether those volumes rise or fall with oil prices is not "
                          "stated; the 2025 segment discussion (PDF 53) cites lower crude, diluent and fuel-oil "
                          "volumes offset by LPG.",
    },
]

# Mechanisms that are OUR hypotheses (no direct statement in these reports), and the statistics that would test them.
HYPOTHESES = {
    "RY.TO": [
        ("Oil-price declines raise RBC's credit losses through oil-and-gas borrowers.",
         "Not supported by FY2025 data: oil-and-gas PCL was $6M (2024: -$51M) and EAD is about 0.8% of total. "
         "Indirect channels (Alberta consumer and commercial credit, ECL scenarios) are undisclosed by sector.",
         "Regress RY.TO weekly returns on Brent with a market control; event-study around large oil moves; compare "
         "with sector PCL history across a full oil cycle (2015-16, 2020)."),
    ],
    "CNQ.TO": [
        ("CNQ.TO share returns rise with WTI.",
         "Operationally strongly supported (US$1/bbl WTI = $409M annualized cash flow), but a share-price direction "
         "is a market outcome and is not established by this disclosure.",
         "Estimate CNQ.TO's beta to Brent and to WTI (already computed in compute/stats.py for the extra universe); "
         "test whether the WCS differential adds explanatory power beyond WTI."),
        ("A wider WCS discount lowers CNQ's realized prices independently of WTI.",
         "Directly documented for 2025 (narrowing partially offset lower WTI).",
         "Needs a WCS series, which is not in the data contract; add it before testing."),
    ],
    "CP.TO": [
        ("Higher oil prices hurt CPKC through fuel costs.",
         "Partly documented as a risk factor, but the surcharge offsets most of the cost with lags, and 2025 shows "
         "the opposite sign for falling prices (-$46M operating income).",
         "CP.TO is not in the data contract universe; add it, then estimate its Brent beta, up/down asymmetry and "
         "lagged effects. A diesel crack-spread control may be needed."),
    ],
}
