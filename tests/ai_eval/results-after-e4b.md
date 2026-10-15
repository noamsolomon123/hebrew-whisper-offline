# AI eval: after-e4b (model gemma4:e4b)

| case | schema | tasks_found | decisions_found | open_found | facts_found | no_tasks_ok | halluc | hebrew | times_bad | times_empty | timeline_sorted | n_tasks | latency_s | error |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| call | True | 2/2 | 1/1 | 0/0 | 0/0 |  | 0 | 1.0 | 0 | 0 | True | 2 | 32.2 |  |
| lecture | True | 0/0 | 0/0 | 0/0 | 4/4 | True | 0 | 1.0 | 0 | 0 | True | 0 | 23.1 |  |
| long | True | 4/4 | 2/2 | 1/1 | 0/0 |  | 0 | 1.0 | 0 | 0 | True | 4 | 354.2 |  |
| meeting | True | 5/5 | 2/2 | 2/2 | 0/0 |  | 0 | 1.0 | 0 | 0 | True | 5 | 48.1 |  |
| messy | True | 0/3 | 2/2 | 1/1 | 0/0 |  | 0 | 1.0 | 0 | 0 | True | 1 | 27.4 |  |
| voice | True | 0/3 | 0/0 | 0/0 | 0/0 |  | 0 | 1.0 | 0 | 0 | True | 0 | 7.3 |  |

Totals: tasks 11/17, hallucinated owner/due 0, total latency 492 s

- messy: missed ['התחברות/לוגין', 'צילומי מסך/צילומי', 'גלעד/מייל']; hallucinated []
- voice: missed ['ביטוח', 'אמא', 'מתנה']; hallucinated []
