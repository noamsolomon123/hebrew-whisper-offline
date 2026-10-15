# AI eval: before-e4b (model gemma4:e4b)

| case | schema | tasks_found | decisions_found | open_found | facts_found | no_tasks_ok | halluc | hebrew | times_bad | times_empty | timeline_sorted | n_tasks | latency_s | error |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| call | True | 2/2 | 1/1 | 0/0 | 0/0 |  | 0 | 1.0 | 0 | 0 | True | 2 | 264.7 |  |
| lecture | True | 0/0 | 0/0 | 0/0 | 4/4 | False | 0 | 0.978 | 0 | 0 | True | 1 | 126.4 |  |
| long | True | 4/4 | 2/2 | 1/1 | 0/0 |  | 0 | 1.0 | 0 | 0 | True | 5 | 546.9 |  |
| meeting | True | 5/5 | 2/2 | 2/2 | 0/0 |  | 0 | 1.0 | 0 | 0 | True | 5 | 44.9 |  |
| messy | True | 1/3 | 2/2 | 1/1 | 0/0 |  | 1 | 1.0 | 0 | 0 | True | 3 | 37.9 |  |
| voice | True | 0/3 | 0/0 | 0/0 | 0/0 |  | 0 | 1.0 | 0 | 0 | True | 0 | 122.9 |  |

Totals: tasks 12/17, hallucinated owner/due 1, total latency 1144 s

- messy: missed ['צילומי מסך/צילומי', 'גלעד/מייל']; hallucinated ['הדובר']
- voice: missed ['ביטוח', 'אמא', 'מתנה']; hallucinated []
