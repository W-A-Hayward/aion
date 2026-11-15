# API contract — cascade-api

HTTP API `cascade-api` (see `docs/data_contract.md` for names and tables). Ownership: header `X-Cascade-Session`
or a JWT `sub`; `GET /jobs/{id}` answers 404 to anyone but the owner.

## Request: POST /jobs

```json
{ "persona": "robert", "question": "Est-ce que mes obligations m'ont protégé ?",
  "level": "beginner", "experiment_id": "bonds_protect" }
```

## Response: GET /jobs/{id}

```json
{
  "job_id": "…", "stage": "done",
  "stages": [{"stage":"queued","t":"…"},{"stage":"agent_started","t":"…"},
             {"stage":"tool:get_portfolio_facts","t":"…"},{"stage":"guardrail","t":"…"},{"stage":"done","t":"…"}],
  "answer": { "verdict": "MYTH", "headline": "Tes obligations n'ont pas protégé…",
              "text": "…avec marqueurs [1] [2]…", "refusal": false,
              "caveat": "2021–2026 · passé · simulation · pas un conseil" },
  "trace": [{"step":1,"tool":"get_portfolio_facts","input_summary":"persona=robert",
             "output_summary":"bonds avg -0.17% in 27 worst weeks","tag":"measured","ms":2100}],
  "data": { "risk_share": {}, "shields": [], "cushion": [], "betas": [],
            "twin_series": [], "stock_bond_series": [], "scenario": null },
  "citations": [{"n":1,"evidence_id":"…","excerpt":"…","publisher":"BIS","date":"2023-12",
                 "doc_type":"research","trust":"Central bank","url":"…"}]
}
```

## Field notes

The block above is the agreed schema. The notes below describe how the sample fixtures in `eval/fixtures/`
(`robert.json`, `amira.json`, `mateo.json`) fill the `data` object. Tickers and table names come from
`docs/data_contract.md`.

| Field | Content |
|---|---|
| `stage` | `queued`, `agent_started`, `tool:<name>`, `guardrail`, `done` (or a failure stage). `stages` has one `tool:<name>` entry per trace step. |
| `answer.verdict` | `CONFIRMED`, `MYTH`, `PARTIAL` or `UNKNOWN`. |
| `answer.refusal` | `true` when the guardrail refuses (advice or prediction request). |
| `trace[].tag` | `measured` (computed from the data), `documented` (issuer or research document), `simulated` (scenario). |
| `data.risk_share` | Object `{rates, stocks, oil}`, each the r2 of a separate single-factor regression (`risk_share` table). The three values overlap and do not add up. |
| `data.shields` | List of alternatives compared (`alternatives` table rows). Empty when not used. |
| `data.cushion` | List of `{asset, avg_return_pct, hit_weeks, n_weeks}`: average weekly return of each asset in the worst weeks of the stock side. `hit_weeks` is the number of those weeks with a positive return, `null` when not computed. |
| `data.betas` | List of `{subject, beta, lo, hi, p, n_weeks}` (`portfolio_beta` rows, oil factor). |
| `data.twin_series` | List of `{week, own, twin, own_dd_pct, twin_dd_pct}`: wealth (start 1.0) of the persona and of its alternative twin, with the drawdown from the running peak in percent. |
| `data.stock_bond_series` | List of `stock_bond` rows `{pair, measure, week, correlation, n_weeks}`. `measure` is `rolling_52w`, `cpi_ge_3` or `cpi_lt_3` (`week` null for the two CPI rows). |
| `data.scenario` | `null` or a `scenarios` row `{subject, subject_type, shock_pct, impact_pct, lo_pct, hi_pct}`. |
| `citations[].n` | Matches the `[n]` markers in `answer.text`. |
