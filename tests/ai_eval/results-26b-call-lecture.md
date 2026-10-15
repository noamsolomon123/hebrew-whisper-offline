# AI eval: before vs after on gemma4:26b, call+lecture (partial; run was cut by GPU contention)

```
BEFORE (old ai.py):
call {"schema": true, "tasks_found": "2/2", "_tasks_hit": 2, "_tasks_n": 2, "decisions_found": "1/1", "open_found": "0/0", "facts_found": "0/0", "halluc": 0, "halluc_list": [], "hebrew": 0.996, "times_bad": 0, "times_empty": 0, "timeline_sorted": true, "n_tasks": 3, "miss": [], "latency_s": 201.6, "error": "", "progress_msgs": 685}
lecture {"schema": true, "tasks_found": "0/0", "_tasks_hit": 0, "_tasks_n": 0, "decisions_found": "0/0", "open_found": "0/0", "facts_found": "4/4", "halluc": 0, "halluc_list": [], "no_tasks_ok": true, "hebrew": 0.983, "times_bad": 0, "times_empty": 0, "timeline_sorted": true, "n_tasks": 0, "miss": [], "latency_s": 349.6, "error": "", "progress_msgs": 798}

AFTER (new ai.py):
call {"schema": true, "tasks_found": "2/2", "_tasks_hit": 2, "_tasks_n": 2, "decisions_found": "1/1", "open_found": "0/0", "facts_found": "0/0", "halluc": 0, "halluc_list": [], "hebrew": 1.0, "times_bad": 0, "times_empty": 0, "timeline_sorted": true, "n_tasks": 3, "miss": [], "latency_s": 194.9, "error": "", "progress_msgs": 30}
lecture {"schema": true, "tasks_found": "0/0", "_tasks_hit": 0, "_tasks_n": 0, "decisions_found": "0/0", "open_found": "0/0", "facts_found": "4/4", "halluc": 0, "halluc_list": [], "no_tasks_ok": true, "hebrew": 1.0, "times_bad": 0, "times_empty": 0, "timeline_sorted": true, "n_tasks": 0, "miss": [], "latency_s": 179.9, "error": "", "progress_msgs": 23}
```
