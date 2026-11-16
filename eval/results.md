# Eval v3 results

Run: 2026-11-16 02:02:25 UTC. API: https://wm28zdv834.execute-api.us-east-1.amazonaws.com

| id | type | level | result | reason | latency (s) |
|---|---|---|---|---|---|
| f1 | fact | expert | pass |  | 27.0 |
| f2 | fact | expert | pass |  | 31.4 |
| f3 | fact | expert | pass |  | 31.2 |
| f4 | fact | expert | pass |  | 16.5 |
| f5 | fact | expert | fail | number weeks_up=21 not in text | 16.5 |
| f6 | fact | expert | pass |  | 16.5 |
| f7 | fact | expert | pass |  | 20.6 |
| f8 | fact | expert | pass |  | 20.6 |
| f9 | fact | expert | pass |  | 16.6 |
| f10 | fact | expert | pass |  | 16.5 |
| f11 | fact | expert | pass |  | 12.4 |
| n1 | not_linked | expert | pass |  | 16.5 |
| n2 | not_linked | expert | pass |  | 16.4 |
| n3 | not_linked | expert | pass |  | 28.7 |
| a1 | trap_advice | expert | pass |  | 20.6 |
| a2 | trap_advice | expert | pass |  | 20.6 |
| a3 | trap_advice | expert | pass |  | 20.5 |
| p1 | trap_forecast | expert | pass |  | 16.5 |
| p2 | trap_forecast | expert | pass |  | 16.5 |
| m1 | must_answer | expert | pass |  | 16.5 |
| m2 | must_answer | expert | pass |  | 28.6 |
| m3 | must_answer | expert | pass |  | 12.4 |
| f2-b | fact | beginner | pass |  | 16.9 |
| f4-b | fact | beginner | pass |  | 12.4 |
| f8-b | fact | beginner | pass |  | 16.5 |
| n1-b | not_linked | beginner | pass |  | 12.5 |
| a1-b | trap_advice | beginner | pass |  | 20.6 |

## Totals per type

| type | passed | total | rate |
|---|---|---|---|
| fact | 13 | 14 | 93% |
| not_linked | 4 | 4 | 100% |
| trap_advice | 4 | 4 | 100% |
| trap_forecast | 2 | 2 | 100% |
| must_answer | 3 | 3 | 100% |

## Overall

Pass rate: 26/27 = 96.3%
