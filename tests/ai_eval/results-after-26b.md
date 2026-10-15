# AI eval: after-26b (model gemma4:26b)

| case | schema | tasks_found | decisions_found | open_found | facts_found | no_tasks_ok | halluc | hebrew | times_bad | times_empty | timeline_sorted | n_tasks | latency_s | error |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| lecture | True | 0/0 | 0/0 | 0/0 | 4/4 | True | 0 | 1.0 | 0 | 0 | True | 0 | 54.5 |  |
| meeting | True | 5/5 | 2/2 | 2/2 | 0/0 |  | 0 | 1.0 | 0 | 0 | True | 5 | 44.7 |  |
| messy | True | 2/3 | 2/2 | 0/1 | 0/0 |  | 0 | 0.988 | 0 | 1 | True | 4 | 26.0 |  |
| voice | True | 3/3 | 0/0 | 0/0 | 0/0 |  | 0 | 1.0 | 0 | 0 | True | 3 | 26.9 |  |

Totals: tasks 10/11, hallucinated owner/due 0, total latency 152 s

- messy: missed ['גלעד/מייל']; hallucinated []
