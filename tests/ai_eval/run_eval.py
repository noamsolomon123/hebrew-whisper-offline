# Eval for app/ai.py ("Organize with AI").
#   set HW_OLLAMA_URL=http://127.0.0.1:11499
#   python tests/ai_eval/run_eval.py --model gemma4:26b --label after [--cases meeting,call]
# Scores each case in tests/ai_eval/*.json and writes tests/ai_eval/results-<label>.md
# (plus results-<label>.json with the raw outputs).
import argparse
import glob
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def norm(s):
    return re.sub(r"[\"'׳״`.,:;!?()\-]", "", str(s or "")).replace(" ", "")


def has(text, kws):
    t = norm(text)
    return any(norm(k) in t for k in kws)


def all_text(r):
    out = [r.get("title", ""), r.get("summary", "")] + r.get("key_points", []) + r.get("decisions", [])
    out += r.get("open_questions", [])
    for t in r.get("topics", []):
        out += [t.get("title", "")] + t.get("points", [])
    for t in r.get("tasks", []):
        out += [t.get("task", ""), t.get("owner", ""), t.get("due", "")]
    out += [t.get("event", "") for t in r.get("timeline", [])]
    return "\n".join(str(x) for x in out)


def secs(t):
    p = [int(x) for x in t.split(":")]
    return p[0] * 60 + p[1] if len(p) == 2 else p[0] * 3600 + p[1] * 60 + p[2]


def score(case, r, dur):
    e = case["expect"]
    s = {}
    req = {"title": str, "summary": str, "key_points": list, "topics": list, "tasks": list,
           "decisions": list, "timeline": list, "open_questions": list}
    s["schema"] = all(isinstance(r.get(k), t) for k, t in req.items())
    tasks = r.get("tasks", [])
    hit = 0
    miss = []
    for exp in e.get("tasks", []):
        ok = False
        for t in tasks:
            if not has(t["task"] + " " + t.get("due", ""), exp["kw"]):
                continue
            if exp.get("owner") and not has(t.get("owner", ""), [exp["owner"]]):
                continue
            if exp.get("due") and not has(t.get("due", "") + t["task"], [exp["due"]]):
                continue
            ok = True
            break
        hit += ok
        if not ok:
            miss.append("/".join(exp["kw"][:2]))
    s["tasks_found"] = "%d/%d" % (hit, len(e.get("tasks", [])))
    s["_tasks_hit"], s["_tasks_n"] = hit, len(e.get("tasks", []))
    dec_text = "\n".join(r.get("decisions", []) + r.get("key_points", []) + [r.get("summary", "")])
    dh = sum(1 for kws in e.get("decisions", []) if has(dec_text, kws))
    s["decisions_found"] = "%d/%d" % (dh, len(e.get("decisions", [])))
    oq = "\n".join(r.get("open_questions", []))
    oh = sum(1 for kws in e.get("open", []) if has(oq, kws))
    s["open_found"] = "%d/%d" % (oh, len(e.get("open", [])))
    txt = all_text(r)
    fh = sum(1 for kws in e.get("facts", []) if has(txt, kws))
    s["facts_found"] = "%d/%d" % (fh, len(e.get("facts", [])))
    # Hallucinations: an owner/due that was never said.
    src = norm(" ".join(x[2] for x in case["segments"]))
    bad_owner = [t["owner"] for t in tasks if t.get("owner") and not any(norm(o) in norm(t["owner"]) for o in e.get("owners", []))
                 and norm(t["owner"]) not in src]
    bad_due = [t["due"] for t in tasks if t.get("due") and not any(norm(d) in norm(t["due"]) for d in e.get("dues", []))
               and norm(t["due"]) not in src]
    s["halluc"] = len(bad_owner) + len(bad_due)
    s["halluc_list"] = bad_owner + bad_due
    if e.get("no_tasks"):
        s["no_tasks_ok"] = len(tasks) == 0 and len(r.get("decisions", [])) == 0
    heb = len(re.findall(r"[֐-׿]", txt))
    lat = len(re.findall(r"[A-Za-z]", txt))
    s["hebrew"] = round(heb / max(1, heb + lat), 3)
    times = [t.get("time", "") for t in tasks + r.get("timeline", []) + r.get("topics", [])]
    bad_t = [x for x in times if x and (not re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", x) or secs(x) > dur + 5)]
    s["times_bad"] = len(bad_t)
    s["times_empty"] = sum(1 for x in times if not x)
    tl = [secs(t["time"]) for t in r.get("timeline", []) if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", t.get("time", ""))]
    s["timeline_sorted"] = tl == sorted(tl)
    s["n_tasks"] = len(tasks)
    s["miss"] = miss
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemma4:26b")
    ap.add_argument("--label", default="run")
    ap.add_argument("--cases", default="")
    ap.add_argument("--ai", default=os.path.join(HERE, "..", "..", "app"))
    a = ap.parse_args()
    sys.path.insert(0, os.path.abspath(a.ai))
    import ai
    ai.PREFERRED = [a.model] + [m for m in ai.PREFERRED if m != a.model]
    os.environ.setdefault("HW_AI_MODEL", a.model)
    files = sorted(glob.glob(os.path.join(HERE, "*.json")))
    files = [f for f in files if not os.path.basename(f).startswith("results")]
    if a.cases:
        want = a.cases.split(",")
        files = [f for f in files if os.path.basename(f)[:-5] in want]
    rows, raw = [], {}
    for f in files:
        case = json.load(open(f, encoding="utf-8"))
        key = os.path.basename(f)[:-5]
        segs = [tuple(x) for x in case["segments"]]
        dur = segs[-1][1]
        msgs = []
        t0 = time.time()
        try:
            r = ai.organize(segs, case["name"], None, msgs.append, lambda *x: None)
            err = ""
        except Exception as ex:  # noqa
            r, err = {}, "%s: %s" % (type(ex).__name__, ex)
        dt = time.time() - t0
        s = score(case, r, dur) if r else {"schema": False}
        s["latency_s"] = round(dt, 1)
        s["error"] = err
        s["progress_msgs"] = len(msgs)
        raw[key] = {"result": r, "score": s}
        rows.append((key, s))
        print(key, json.dumps(s, ensure_ascii=False), flush=True)
    cols = ["schema", "tasks_found", "decisions_found", "open_found", "facts_found", "no_tasks_ok", "halluc",
            "hebrew", "times_bad", "times_empty", "timeline_sorted", "n_tasks", "latency_s", "error"]
    md = ["# AI eval: %s (model %s)" % (a.label, a.model), "", "| case | " + " | ".join(cols) + " |",
          "|" + "---|" * (len(cols) + 1)]
    for k, s in rows:
        md.append("| %s | " % k + " | ".join(str(s.get(c, "")) for c in cols) + " |")
    th = sum(s.get("_tasks_hit", 0) for _, s in rows)
    tn = sum(s.get("_tasks_n", 0) for _, s in rows)
    md += ["", "Totals: tasks %d/%d, hallucinated owner/due %d, total latency %.0f s" %
           (th, tn, sum(s.get("halluc", 0) for _, s in rows), sum(s.get("latency_s", 0) for _, s in rows)), ""]
    for k, s in rows:
        if s.get("miss") or s.get("halluc_list"):
            md.append("- %s: missed %s; hallucinated %s" % (k, s.get("miss"), s.get("halluc_list")))
    open(os.path.join(HERE, "results-%s.md" % a.label), "w", encoding="utf-8").write("\n".join(md) + "\n")
    json.dump(raw, open(os.path.join(HERE, "results-%s.json" % a.label), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n".join(md))


if __name__ == "__main__":
    main()
