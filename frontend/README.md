# Cascade — local frontend

Buildless HTML, CSS and native JavaScript modules. No dependencies, credentials, external requests,
analytics or AWS calls. Serve over HTTP rather than opening `file://`.

This README documents what should survive a redesign: how to run it, where the data comes from, and the
backend contract. Layout and styling are deliberately not described here; read `index.html` and `styles.css`.

The transmission graph has been replaced in the application by the **Evidence Desk**, an independent local XIU
document reader. See [EVIDENCE_DESK.md](EVIDENCE_DESK.md) for the research source, file inventory, verification
limits and browser checks. It works without the statistics API. Research candidates are not production evidence.

The **Research Library** connects all 52 official-register entries to the acquired local source texts and
datasets, with verification statuses, exact-page navigation and document search from the first question form.
See [RESEARCH_LIBRARY.md](RESEARCH_LIBRARY.md) for availability counts, bundle setup, changed files and
the remaining backend/model integration. Generated source content stays untracked and must be built locally.

From the repository root:

```sh
python3 -m http.server 4173 --bind 127.0.0.1 --directory frontend
```

Open http://127.0.0.1:4173. Stop with Ctrl+C. This serves only the frontend directory.

## Files

- `index.html`: accessible page shell, controls, and methodology dialog.
- `styles.css`: base application styles; the guide and Evidence Desk have scoped stylesheets.
- `app.js`: state, events, cancellation, loading/error/unavailable states.
- `api.js`: local JSON loader and optional table API adapter; no direct AWS access.
- `agent-api.js`: implemented submit/status contract, polling, validation, timeout and cancellation.
- `agent-render.js`: escaped agent answers, citations and inspectable tool outputs.
- `config.js`: intentionally unset backend endpoints; the 14 supported tickers (`CORE_TICKERS`) with display names; shocks.
- `formatters.js`: null-safe formatting, escaping, URL validation, estimate checks.
- `graph.js`: retained legacy graph model and tests; no longer imported by the application.
- `render.js`: ticker summary, ticker picker, intervals, scenarios, evidence, duration check, diagnostics and the local (non-AI) explanation.
- `workspace.js` / `workspace-render.js` / `workspace-store.js`: the local workspace (profile, sample and custom portfolios, watchlist, saved research, export/import).
- `preview-data.json`: the statistics snapshot described below (research lab and workspace).
- `evidence-preview.json`: a separate, sanitized documentary snapshot; see EVIDENCE_DESK.md.
- `frontend.test.mjs`: dependency-free local safety, data-integrity and simulated chat-transport tests.

## Provenance and deliberate gaps

`preview-data.json` extracts all 14 core tickers (the data contract's MVP list: nine
ETFs and five stocks) from the **saved outputs** of `compute/run_stats.ipynb`, cell 9;
links come from cell 13, chain reconciliation from cell 15, `duration_check` from cell 17,
`portfolio_beta` from cell 19, persona scenarios from cell 21 and `alternatives` from
cell 23 (zero-based notebook cell indices). `persona_holdings` is the contract's table. Values retain notebook display precision.
This is an unverified historical snapshot, not a current AWS response. The saved weekly
panel reports 2021-11-19 through 2026-11-13 and 261 weeks. This is the sample period,
not a date of independent verification. The page always says "Last verified: Not verified".

The notebook truncates some columns. Omitted fields, including `beta_ex2022` and
`r2_incremental`, remain absent. They are not inferred from rounded interval bounds.

The **56 ticker scenario rows** (14 tickers × 4 shocks) are precomputed locally from the saved
coefficients with the same method as `compute/stats.py` `scenarios()`, only at contract shocks -30, -15, +15, +30. Formula:
`100 * (exp(beta * log(1 + shock / 100)) - 1)`. The low/high estimates transform
both beta bounds and reorder for negative shocks. These rows are explicitly NOT
downloaded from `processed/scenarios`. Labels in the UI distinguish them from
saved notebook statistics. Live mode only displays supplied scenario rows.

No documentary citations, confidence-table labels, holdings, or rolling history are
invented. Empty arrays in the statistics snapshot are intentional; the Evidence Desk reads a separate local file.
The retained legacy graph model uses the simple sensitivity as a
total measured oil–ETF association, `links` as macro relationships, and actual
`edges`/`evidence` rows for documentary pathways. Company membership and sector
contributions cannot be inferred from the contract and are not drawn.

The optional dotted hypothesis is a user-created research question, never a backend
finding. It is cleared when the investigation changes. No company links are invented.
Chain/direct ratios are cross-checks, not causal contribution percentages.

## Supported tickers and the workspace

Only the 14 core tickers can be researched, watched, saved or put in a mock portfolio.
Pickers list only those tickers, with names, and `validateHoldings` / `sanitizeWorkspace`
reject anything else, including imported files. Other universe tickers (the 21 "extra")
have no saved rows in the snapshot.

Robert, Amira and Mateo are the contract's fictional personas. Their saved notebook
betas and scenarios **predate the latest portfolio return formula** and are labeled
legacy previews throughout the workspace. The current `portfolio_beta()` regresses
`log(1 + sum(weight * (exp(asset_log_return) - 1)))` on Brent. Summing individual log-return
betas is not equivalent. Custom mixes and saved alternative comparisons use a
weighted-beta **proxy approximation**, with no fabricated portfolio confidence interval.
Fresh outputs are needed for the updated portfolio model.

The snapshot also predates the ZST Canada 2Y pathway. Its old `ca10y>ZST.TO` link,
ZST chain and duration cross-check have been removed rather than relabeled with incorrect
numbers. The invalid XRB nominal-yield chain has also been removed. `graph.js` supports
`ca2y` when actual coefficients arrive. ZST's direct sensitivity remains available.

There are no accounts. The profile, custom mix, watchlist and notes live in
`localStorage` (`cascade.workspace.v1`), validated on every read. Export and Import move
them between browsers. The backend accepts a Cognito JWT in place of the session token (see Backend contract),
but the frontend has no sign-in flow yet.

ETF decomposition is explicitly unavailable: `persona_holdings` and
`portfolio_exposure` describe investor portfolios, not ETF constituent weights.
The current contract cannot support validated ETF holdings attribution. Neither sector
weight subtraction nor XEG-as-XIU-sleeve substitution is performed.

## Backend contract

The backend is implemented but not deployed; all three URLs in `config.js` stay `null` until it is.
Deployment steps: [docs/infrastructure.md](../docs/infrastructure.md). Never put AWS credentials or AWS SDK calls
in the browser.

| `config.js` key | Endpoint | Lambda |
|---|---|---|
| `investigationUrl` | `GET …/research` (the adapter appends `?ticker=XIU.TO`) | `lambdas/research/app.py` |
| `submitUrl` | `POST …/jobs` | `lambdas/submit/app.py` |
| `statusUrl` | `GET …/jobs/{id}` (must contain `{id}`) | `lambdas/status/app.py` |

### Research tables: `GET /research?ticker=`

Returns one JSON array per table in `api.js` `TABLES`, filtered to the ticker, plus a `meta` object
(`ticker`, `as_of`, `generated_at`, `source`, `missing`). Only the 14 core tickers are accepted (400 otherwise).
`sensitivities` is required (502 if unreadable); any other table that fails is returned empty and listed in
`meta.missing`. Missing numbers are `null`, never NaN or numeric strings; zero is a valid value. No silent
preview fallback is permitted on API errors.

Responses are labelled "Backend response", not "Live AWS verified": network success does not verify the data,
and the preview's coverage dates are never reused for a backend response. `evidence` rows carry no original
title, issuer, publication date or verification status; the UI marks these missing and shows supplied HTTP(S)
links as **unverified**. Nothing is inferred from a ticker or filename.

### Chat: `POST /jobs`, then poll `GET /jobs/{id}`

- Request `{question, persona, level, sessionId?}`: question 1–1000 characters, persona `robert` | `amira` |
  `mateo`, level `beginner` | `expert`. Custom portfolios are not accepted. There is no ticker field, so the
  selected ticker goes in the question text. Response: HTTP 202 `{jobId, sessionId}`.
- Every request must send header **`X-Cascade-Session`**: a random 32–128 character token that
  `agent-api.js` `sessionToken()` creates once per browser (stored as `cascade.session-token`). Only the
  browser that submitted a job can read it; others get 404. Missing token → 401. More than 5 questions per
  minute per browser, or 30 per IP → 429 with `Retry-After`. With a Cognito sign-in in front, the JWT replaces
  the token (no frontend flow exists for that yet).
- Status response: `{jobId, status, answer?, toolCalls?, citations?, error?, durationMs?}`, status `PENDING` |
  `RUNNING` | `DONE` | `FAILED`. Tool calls are `{name, input, output}` (output may be truncated text); citations are
  `{text, source_url, section, ticker, channel}`.
- The client submits once (never retries a POST), then polls until DONE/FAILED or `jobTimeoutMs`. Stopping
  polling does not cancel the server job.
- The agent has **no conversation memory**: it starts fresh on every question even when `sessionId` is reused,
  so questions must be self-contained. Guardrail results are not exposed by the status API.
- Chat answers never overwrite the Research tables, and chat citations are kept separate from the `evidence`
  table. The tools Lambda serves the agent only; it is not a browser endpoint.

## Local checks

```sh
node --test frontend/frontend.test.mjs
node --check frontend/app.js
```

The Node tests cover snapshot consistency, legacy/proxy labelling, workspace validation and imports, unsafe
markup and URLs, and the chat submit/status lifecycle with a simulated transport. They do not exercise AWS.
The backend side of this contract is tested in `lambdas/*/test_app.py` and, end to end with the real handlers
behind a local API stand-in, in `infra/test_local_e2e.py`.
