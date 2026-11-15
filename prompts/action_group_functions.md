# Action group functions (cascade-tools)

Paste each function into the console "Action group function" form. Action group type: function details. All parameters are type string, required yes.

Tickers allowed (35): XIU.TO ENB.TO XOM TLT XBB.TO ZST.TO QQQ SHOP.TO SPY VFV.TO XSP.TO XESG.TO ATD.TO RY.TO CNQ.TO CNR.TO FTS.TO TD.TO MFC.TO CSU.TO NVDA AAPL MSFT GOOGL AMZN TSLA JPM JNJ PG GLD AGG ESGV XRB.TO XLB.TO XEG.TO

## 1. get_portfolio_exposure

| Field | Value |
|---|---|
| Function name | get_portfolio_exposure |
| Description | Call first on every question. Returns the persona's holdings, weights, oil beta with 95% range, contributions and the portfolio-level beta. |

| Parameter | Type | Required | Description |
|---|---|---|---|
| persona | string | yes | Persona name. Allowed values: robert, amira, mateo |

## 2. get_asset_sensitivity

| Field | Value |
|---|---|
| Function name | get_asset_sensitivity |
| Description | Call to get one ticker's oil beta (simple and market-controlled), 95% range, p-values and recent 52-week rolling beta. Use for a holding or an asset the user names. |

| Parameter | Type | Required | Description |
|---|---|---|---|
| ticker | string | yes | Ticker symbol. Allowed values: XIU.TO, ENB.TO, XOM, TLT, XBB.TO, ZST.TO, QQQ, SHOP.TO, SPY, VFV.TO, XSP.TO, XESG.TO, ATD.TO, RY.TO, CNQ.TO, CNR.TO, FTS.TO, TD.TO, MFC.TO, CSU.TO, NVDA, AAPL, MSFT, GOOGL, AMZN, TSLA, JPM, JNJ, PG, GLD, AGG, ESGV, XRB.TO, XLB.TO, XEG.TO |

## 3. explain_channel

| Field | Value |
|---|---|
| Function name | explain_channel |
| Description | Call for a holding that matters to explain how oil reaches it (direct, rates, currency). Returns confidence label, chain steps, duration check and cited evidence with section. |

| Parameter | Type | Required | Description |
|---|---|---|---|
| ticker | string | yes | Ticker symbol. Allowed values: XIU.TO, ENB.TO, XOM, TLT, XBB.TO, ZST.TO, QQQ, SHOP.TO, SPY, VFV.TO, XSP.TO, XESG.TO, ATD.TO, RY.TO, CNQ.TO, CNR.TO, FTS.TO, TD.TO, MFC.TO, CSU.TO, NVDA, AAPL, MSFT, GOOGL, AMZN, TSLA, JPM, JNJ, PG, GLD, AGG, ESGV, XRB.TO, XLB.TO, XEG.TO |

## 4. run_scenario

| Field | Value |
|---|---|
| Function name | run_scenario |
| Description | Call when the user asks "what if oil moves X%". Returns estimated impact with 95% range for the persona's portfolio and each holding. Only the four listed shocks are supported. |

| Parameter | Type | Required | Description |
|---|---|---|---|
| persona | string | yes | Persona name. Allowed values: robert, amira, mateo |
| oil_shock_pct | string | yes | Brent oil move in percent. Allowed values: -30, -15, 15, 30 |

## 5. compare_alternative

| Field | Value |
|---|---|
| Function name | compare_alternative |
| Description | Call when the user asks "what instead" about swapping a holding. Returns both betas and the portfolio impact of a +30% oil move before and after. Only the listed swaps are supported. |

| Parameter | Type | Required | Description |
|---|---|---|---|
| persona | string | yes | Persona name. Allowed values: robert, amira, mateo |
| holding | string | yes | Current holding. Allowed values by persona: robert: TLT or XBB.TO; mateo: XIU.TO or VFV.TO; amira: QQQ |
| alternative | string | yes | Replacement ticker. Allowed pairs (persona holding to alternative): robert TLT to ZST.TO; robert XBB.TO to ZST.TO; mateo XIU.TO to XESG.TO; mateo VFV.TO to XSP.TO; amira QQQ to XIU.TO |

## 6. get_validation

| Field | Value |
|---|---|
| Function name | get_validation |
| Description | Call for a holding that matters to check robustness. Returns ex-2022 beta with range, out-of-sample hit rate, beta in oil-up and oil-down weeks, and the green/yellow/grey label. |

| Parameter | Type | Required | Description |
|---|---|---|---|
| ticker | string | yes | Ticker symbol. Allowed values: XIU.TO, ENB.TO, XOM, TLT, XBB.TO, ZST.TO, QQQ, SHOP.TO, SPY, VFV.TO, XSP.TO, XESG.TO, ATD.TO, RY.TO, CNQ.TO, CNR.TO, FTS.TO, TD.TO, MFC.TO, CSU.TO, NVDA, AAPL, MSFT, GOOGL, AMZN, TSLA, JPM, JNJ, PG, GLD, AGG, ESGV, XRB.TO, XLB.TO, XEG.TO |
