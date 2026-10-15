# AI eval: before-26b (model gemma4:26b)

| case | schema | tasks_found | decisions_found | open_found | facts_found | no_tasks_ok | halluc | hebrew | times_bad | times_empty | timeline_sorted | n_tasks | latency_s | error |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| lecture | True | 0/0 | 0/0 | 0/0 | 4/4 | True | 0 | 0.982 | 0 | 0 | True | 0 | 60.4 |  |
| meeting | True | 5/5 | 2/2 | 2/2 | 0/0 |  | 0 | 1.0 | 0 | 0 | True | 5 | 39.3 |  |
| messy | True | 1/3 | 2/2 | 1/1 | 0/0 |  | 0 | 0.992 | 0 | 0 | True | 3 | 32.7 |  |
| voice | True | 3/3 | 0/0 | 0/0 | 0/0 |  | 0 | 1.0 | 0 | 0 | True | 3 | 20.6 |  |

Totals: tasks 9/11, hallucinated owner/due 0, total latency 153 s

- messy: missed ['צילומי מסך/צילומי', 'גלעד/מייל']; hallucinated []
