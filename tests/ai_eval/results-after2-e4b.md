# AI eval: after2-e4b (model gemma4:e4b)

| case | schema | tasks_found | decisions_found | open_found | facts_found | no_tasks_ok | halluc | hebrew | times_bad | times_empty | timeline_sorted | n_tasks | latency_s | error |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| lecture | True | 0/0 | 0/0 | 0/0 | 4/4 | False | 0 | 1.0 | 0 | 0 | True | 1 | 16.0 |  |
| meeting | True | 5/5 | 2/2 | 0/2 | 0/0 |  | 0 | 1.0 | 0 | 0 | True | 5 | 19.8 |  |
| messy | True | 2/3 | 2/2 | 1/1 | 0/0 |  | 0 | 1.0 | 0 | 0 | True | 3 | 14.4 |  |
| voice | True | 3/3 | 0/0 | 0/0 | 0/0 |  | 0 | 1.0 | 0 | 0 | True | 3 | 8.0 |  |

Totals: tasks 10/11, hallucinated owner/due 0, total latency 58 s

- messy: missed ['צילומי מסך/צילומי']; hallucinated []
