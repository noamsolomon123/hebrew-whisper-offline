# Post-processing for "Organize with AI" (app/ai.py): JSON repair, grounding against the
# transcript (no invented owners/dates), time fixing, dedupe, and Word/TXT export blocks.

import json
import re


def _mmss(sec):
    sec = int(sec or 0)
    return "%d:%02d" % (sec // 60, sec % 60) if sec < 3600 else "%d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def _secs(t):
    m = re.fullmatch(r"\s*\[?(\d{1,2}):(\d{2})(?::(\d{2}))?\]?\s*", str(t or ""))
    if not m:
        return None
    a, b, c = m.groups()
    return int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)


def _repair(raw):
    """Best effort: fences, prose around the object, trailing commas, a cut-off ending."""
    s = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    i = s.find("{")
    if i < 0:
        raise ValueError("no JSON object")
    s = s[i:]
    # Hebrew acronyms written with an ASCII quote (ש"ח, יו"ר, צה"ל) end the JSON string early and
    # cost everything after them. Between two Hebrew letters it is always gershayim.
    s = re.sub('(?<=[א-ת])"(?=[א-ת])', "״", s)
    try:
        return json.loads(s)
    except ValueError:
        pass
    j = s.rfind("}")
    for cand in ([s[:j + 1]] if j > 0 else []) + [s]:
        c = re.sub(r",\s*([}\]])", r"\1", cand)
        try:
            return json.loads(c)
        except ValueError:
            pass
    # Truncated (num_predict hit): drop the last partial value and close the brackets.
    st, out, q, esc = [], [], False, False
    for ch in s:
        out.append(ch)
        if q:
            esc = (ch == "\\") and not esc
            if ch == '"' and not esc:
                q = False
            continue
        if ch == '"':
            q = True
        elif ch in "{[":
            st.append("}" if ch == "{" else "]")
        elif ch in "}]" and st:
            st.pop()
    c = "".join(out) + ('"' if q else "")
    c = re.sub(r",\s*\"[^\"]*\"\s*:?\s*\"?[^\"{}\[\]]*$", "", c)
    c = re.sub(r"[,:]\s*$", "", c)
    return json.loads(c + "".join(reversed(st)))


def _words(s):
    return [w for w in re.findall(r"[\w']+", str(s or "")) if len(w) > 1]


_PRE = ("וכש", "וב", "ול", "וה", "ומ", "וש", "כש", "מה", "שה", "שב", "של", "ו", "ב", "ל", "ה", "מ", "ש", "כ")
_vocab = {}


def _stem(w):
    """The word and its forms without Hebrew prefix letters (only if 3+ letters remain)."""
    out = {w}
    for p in _PRE:
        if w.startswith(p) and len(w) - len(p) >= 3:
            out.add(w[len(p):])
    return out


def _said(text, src):
    """True if most words of text were actually said in src (whole words, prefixes ignored)."""
    ws = _words(text)
    if not ws:
        return False
    if src not in _vocab:
        _vocab.clear()
        v = set()
        for w in _words(src):
            v |= _stem(w)
        _vocab[src] = v
    v = _vocab[src]
    ok = sum(1 for w in ws if _stem(w) & v)
    return ok * 2 >= len(ws)


def _sim(a, b):
    if a.strip() == b.strip():
        return 1.0
    wa, wb = set(_words(a)), set(_words(b))
    return len(wa & wb) / max(1, min(len(wa), len(wb)))


def _dedupe_strs(xs, thr=0.8):
    out = []
    for x in xs:
        if not any(_sim(x, y) >= thr for y in out):
            out.append(x)
    return out


def clean(d, src="", dur=None, lines=None):
    """Normalizes the model's JSON to the fixed shape; with src (the transcript), drops owners and
    dates that were never said, fixes/fills times from the transcript, dedupes."""
    def s(x):
        return str(x).strip() if x is not None and not isinstance(x, (list, dict)) else ""

    def strs(x):
        return [s(v) for v in (x if isinstance(x, list) else []) if s(v)]

    def objs(x, keys):
        out = []
        for o in x if isinstance(x, list) else []:
            if isinstance(o, dict):
                out.append({k: (strs(o.get(k)) if k == "points" else s(o.get(k))) for k in keys})
            elif s(o):
                out.append({k: (s(o) if i == 0 else ([] if k == "points" else "")) for i, k in enumerate(keys)})
        return out

    def fix_time(t, text=""):
        if dur == 0:  # user-edited text: there are no times to point at
            return ""
        v = _secs(t)
        if v is not None and (dur is None or v <= dur + 2):
            return _mmss(v)
        if lines and text:  # snap to the transcript line that best matches
            best = max(lines, key=lambda l: _sim(text, l[1]))
            if _sim(text, best[1]) >= 0.34:
                return _mmss(best[0])
        return ""

    d = d if isinstance(d, dict) else {}
    tasks, seen = [], []
    for t in objs(d.get("tasks"), ["task", "owner", "due", "priority", "time"]):
        if not t["task"]:
            continue
        if src:
            if t["owner"] and not _said(t["owner"], src):
                t["owner"] = ""
            if t["due"] and not _said(t["due"], src):
                t["due"] = ""
        if t["priority"] not in ("גבוהה", "רגילה"):
            t["priority"] = ""
        t["time"] = fix_time(t["time"], t["task"]) if src else s(t["time"])
        dup = next((x for x in seen if _sim(x["task"], t["task"]) >= 0.7
                    and (not x["owner"] or not t["owner"] or x["owner"] == t["owner"])), None)
        if dup:
            for k in ("owner", "due", "time", "priority"):
                dup[k] = dup[k] or t[k]
            continue
        seen.append(t)
        tasks.append(t)
    timeline = [t for t in objs(d.get("timeline"), ["time", "event"]) if t["event"]]
    topics = [t for t in objs(d.get("topics"), ["title", "time", "points"]) if t["title"]]
    if src:
        for t in timeline:
            t["time"] = fix_time(t["time"], t["event"])
        for t in topics:
            t["time"] = fix_time(t["time"], t["title"] + " " + " ".join(t["points"]))
    if all(_secs(t["time"]) is not None for t in timeline):
        timeline.sort(key=lambda t: _secs(t["time"]))
    tl, last = [], None
    for t in timeline:
        if tl and (t["time"] and t["time"] == last or _sim(t["event"], tl[-1]["event"]) >= 0.8):
            continue
        tl.append(t)
        last = t["time"]
    speakers = []
    for p in objs(d.get("speakers"), ["name", "role"]):
        if p["name"] and (not src or _said(p["name"], src)) and p["name"] not in [x["name"] for x in speakers]:
            speakers.append(p)
    kind = s(d.get("kind"))
    return {
        "title": s(d.get("title")),
        "kind": kind if len(kind) < 30 else "",
        "summary": s(d.get("summary")),
        "speakers": speakers,
        "key_points": _dedupe_strs(strs(d.get("key_points"))),
        "topics": topics,
        "tasks": tasks,
        "decisions": _dedupe_strs(strs(d.get("decisions"))),
        "timeline": tl,
        "open_questions": _dedupe_strs(strs(d.get("open_questions"))),
    }


def as_blocks(r):
    """The organized result as (kind, text) blocks, for Word and for plain-text copy."""
    b = [("title", r.get("title") or "סיכום")]
    if r.get("summary"):
        b += [("h", "סיכום"), ("p", r["summary"])]
    if r.get("speakers"):
        b += [("h", "משתתפים")] + [("li", p["name"] + (" - " + p["role"] if p.get("role") else ""))
                                    for p in r["speakers"]]
    if r.get("key_points"):
        b += [("h", "נקודות עיקריות")] + [("li", x) for x in r["key_points"]]
    if r.get("tasks"):
        b.append(("h", "משימות"))
        for t in r["tasks"]:
            extra = " · ".join(x for x in (t.get("owner") and "אחראי: " + t["owner"],
                                           t.get("due") and "עד: " + t["due"],
                                           t.get("priority") == "גבוהה" and "דחוף") if x)
            b.append(("task", t["task"] + (" (" + extra + ")" if extra else "")))
    if r.get("decisions"):
        b += [("h", "החלטות")] + [("li", x) for x in r["decisions"]]
    if r.get("timeline"):
        b += [("h", "ציר זמן")] + [("li", (t["time"] + " - " if t["time"] else "") + t["event"])
                                     for t in r["timeline"]]
    if r.get("topics"):
        b.append(("h", "נושאים"))
        for t in r["topics"]:
            b.append(("h2", t["title"] + ("  (" + t["time"] + ")" if t["time"] else "")))
            b += [("li", p) for p in t["points"]]
    if r.get("open_questions"):
        b += [("h", "שאלות פתוחות")] + [("li", x) for x in r["open_questions"]]
    return b


def as_text(r):
    out = []
    for kind, t in as_blocks(r):
        if kind == "title":
            out += [t, "=" * min(len(t), 40)]
        elif kind == "h":
            out += ["", t]
        elif kind == "h2":
            out += ["", "  " + t]
        elif kind == "task":
            out.append("☐ " + t)
        elif kind == "li":
            out.append("• " + t)
        else:
            out.append(t)
    return "\n".join(out).strip() + "\n"
