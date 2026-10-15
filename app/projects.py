# Project history: a project is the set of recordings in the window (transcript, edits,
# AI result, ticked tasks). Work starts unsaved; "Save" writes it here, and it shows up in
# History. One JSON file per project, written atomically.

import json
import os
import time
import uuid

DIR = os.path.join(os.path.expanduser("~"), "Documents", "Hebrew-Whisper-Output", "_projects")

KEEP = ("id", "name", "size", "state", "error", "duration", "seconds", "device", "out",
        "segments", "edited", "ai", "ai_state", "ai_error", "done_tasks", "created")


def _path(pid):
    pid = "".join(c for c in pid if c.isalnum())
    return os.path.join(DIR, pid + ".json")


def snapshot(job):
    d = {k: job.get(k) for k in KEEP}
    if d["ai_state"] in ("queued", "running"):
        d["ai_state"] = None
    if d["state"] in ("queued", "running"):
        d.update(state="error", error="התמלול לא הסתיים לפני השמירה. שמרו שוב בסיום.")
    return d


def save(pid, name, jobs):
    os.makedirs(DIR, exist_ok=True)
    pid = pid or uuid.uuid4().hex[:12]
    old = load(pid) if os.path.exists(_path(pid)) else None
    data = {"id": pid, "name": name, "created": (old or {}).get("created") or time.time(),
            "saved": time.time(), "jobs": [snapshot(j) for j in jobs]}
    tmp = _path(pid) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, _path(pid))
    return pid


def load(pid):
    with open(_path(pid), encoding="utf-8") as f:
        return json.load(f)


def delete(pid):
    try:
        os.remove(_path(pid))
    except OSError:
        pass


def listing():
    out = []
    if not os.path.isdir(DIR):
        return out
    for fn in os.listdir(DIR):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(DIR, fn), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        jobs = d.get("jobs") or []
        out.append({"id": d.get("id"), "name": d.get("name") or "ללא שם", "saved": d.get("saved"),
                    "count": len(jobs), "duration": sum(j.get("duration") or 0 for j in jobs),
                    "names": [j.get("name") for j in jobs][:4],
                    "ai": sum(1 for j in jobs if j.get("ai"))})
    out.sort(key=lambda x: x["saved"] or 0, reverse=True)
    return out
