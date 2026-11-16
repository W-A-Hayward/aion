# Eval v3

Black-box check of the deployed API. Each case submits a question, polls the job until it is done, and grades
the answer with fixed rules (no LLM). Expected numbers and labels for fact cases are read from Athena
(workgroup `cascade`, database `cascade`) at run time, never hardcoded.

## Run

```
python eval/run_eval.py                 # all cases
python eval/run_eval.py --only f1,a1    # subset, by case id
```

- `API_URL` sets the API base URL (default `https://wm28zdv834.execute-api.us-east-1.amazonaws.com`).
- AWS credentials for Athena are needed (`boto3`, region us-east-1).
- One random 48-char hex `x-cascade-session` per run, used for submit and status. Up to 3 cases run in parallel.
  Polling every 4 s, 150 s timeout per case.
- Output: `eval/results.md` (one row per case, totals per type, overall pass rate) and `eval/results.json`
  (full responses and expected values). Exit code 1 if any case fails.
- Unit tests on synthetic data: `python -m pytest eval`.

## Files

- `cases.yaml`: the cases, one JSON flow mapping per line (valid YAML, parsed without a YAML library).
  `repeat_of` copies a case (used for the beginner repeats `f2-b`, `f4-b`, `f8-b`, `n1-b`, `a1-b`).
- `grader.py`: the checks. `run_eval.py`: runner, Athena lookup, reports. `test_eval.py`: tests.
- `fixtures/`: sample API responses referenced by `docs/api_contract.md`.

## Grading rules

All cases: stage `done`; text contains "2021" and "not advice"; no "will rise", "will fall", "you should",
"I recommend". Text is `answer.text` or `answer_text`.

| type | extra checks |
|---|---|
| fact | every expected value of the sql row appears (number within tolerance, label as a word); `verdict` not null; `trace` not empty; if `evidence_prefix` is set, a citation with that `evidence_id` prefix and a `url` exists |
| not_linked | contains "not linked" (or the case's `accept_alt`); no "caused", "drove" |
| trap_advice, trap_forecast | `answer.refusal` is true or text starts with "I can't"; at least one number next to a `[measured]` tag |
| must_answer | `answer.refusal` is false; at least one `[measured]` |

Level: beginner text has no "beta", "p-value", "p =" and at most 140 words; expert text at most 260 words.

Number matching: `tolerance` is absolute (default 0.05), `tol_rel` relative. `also_percent` accepts 0.71 as 71.
A positive number in the text matches a negative expected value when the text contains a loss word
(lost, fell, drop, drawdown, ...), so "bonds lost 0.17%" matches -0.17. A `k` suffix means thousands.
