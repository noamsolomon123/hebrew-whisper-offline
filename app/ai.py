# "Organize with AI": turns a transcript into a summary, tasks, decisions and a timeline,
# using the gemma4 that AutoPoint already has on the offline PC (its bundled Ollama).
#
# 1. Use an Ollama that is already running on 127.0.0.1 (AutoPoint's, on 11434-11440).
# 2. Otherwise start AutoPoint's bundled ollama.exe ourselves on 11441, against AutoPoint's
#    model folder, and stop it when this program exits.
# Nothing here leaves the PC: every URL is 127.0.0.1.

import glob
import json
import os
import re
import subprocess
import time
import urllib.request

PREFERRED = ["gemma4:26b", "gemma4:12b", "gemma4:latest", "gemma4:e4b", "qwen2.5:14b", "gemma4:e2b"]
PROBE_PORTS = list(range(11434, 11441))
OWN_PORT = 11441
NUM_CTX = 32768
CHUNK_CHARS = 14000   # ~ one Hebrew chunk well inside NUM_CTX, with room for the answer

_proc = None
_found = {"url": None, "model": None}


def _get(url, timeout=2.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(url, body, timeout=900.0):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def _tags(url):
    try:
        return [m["name"] for m in _get(url + "/api/tags").get("models", [])]
    except Exception:
        return None


def _pick(names):
    for p in PREFERRED:
        if p in names:
            return p
    g = [n for n in names if n.startswith("gemma")]
    return g[0] if g else None


def _autopoint_dirs():
    # Per-user NSIS install: %LOCALAPPDATA%\Programs\AutoPoint by default; the uninstall key
    # knows the real place if the owner picked another folder.
    roots = []
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                k = winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Uninstall")
            except OSError:
                continue
            for i in range(winreg.QueryInfoKey(k)[0]):
                try:
                    sub = winreg.OpenKey(k, winreg.EnumKey(k, i))
                    name = winreg.QueryValueEx(sub, "DisplayName")[0]
                    if str(name).startswith("AutoPoint"):
                        roots.append(winreg.QueryValueEx(sub, "InstallLocation")[0])
                except OSError:
                    pass
    except ImportError:
        pass
    la = os.environ.get("LOCALAPPDATA", "")
    roots += [os.path.join(la, "Programs", "AutoPoint"), os.path.join(la, "Programs", "autopoint")]
    return [r for r in roots if r and os.path.isdir(r)]


def _has_models(d):
    return os.path.isdir(os.path.join(d, "manifests", "registry.ollama.ai", "library"))


def _local_models(d):
    lib = os.path.join(d, "manifests", "registry.ollama.ai", "library")
    out = []
    for p in glob.glob(os.path.join(lib, "*", "*")):
        out.append(os.path.basename(os.path.dirname(p)) + ":" + os.path.basename(p))
    return out


def _find_exe_and_models():
    exe = os.environ.get("HW_OLLAMA_EXE")
    models = os.environ.get("HW_OLLAMA_MODELS")
    if not exe:
        for r in _autopoint_dirs():
            c = os.path.join(r, "resources", "ollama", "ollama.exe")
            if os.path.isfile(c):
                exe = c
                break
    if not models:
        cands = [os.path.join(os.environ.get("APPDATA", ""), "AutoPoint", "ollama", "models"),
                 os.path.join(os.environ.get("APPDATA", ""), "autopoint", "ollama", "models")]
        if exe:
            cands.insert(0, os.path.join(os.path.dirname(exe), "models"))
        cands.append(os.path.join(os.path.expanduser("~"), ".ollama", "models"))
        models = next((c for c in cands if _has_models(c) and _pick(_local_models(c))), None)
    return exe, models


def connect(log=print):
    """Returns (url, model) or raises RuntimeError with a Hebrew message."""
    global _proc
    if _found["url"] and _tags(_found["url"]) is not None:
        return _found["url"], _found["model"]
    if os.environ.get("HW_OLLAMA_URL"):
        ports = []
        urls = [os.environ["HW_OLLAMA_URL"].rstrip("/")]
    else:
        ports = PROBE_PORTS + [OWN_PORT]
        urls = ["http://127.0.0.1:%d" % p for p in ports]
    for url in urls:
        names = _tags(url)
        if names and _pick(names):
            _found.update(url=url, model=_pick(names))
            log("AI: using running Ollama %s, model %s" % (url, _found["model"]))
            return url, _found["model"]
    exe, models = _find_exe_and_models()
    if not exe:
        raise RuntimeError("לא נמצא AutoPoint במחשב הזה (ה-AI מגיע ממנו). אפשר לפתוח את AutoPoint ולנסות שוב.")
    if not models:
        raise RuntimeError("נמצא AutoPoint אבל בלי מודלי AI מותקנים (הגדרות > התקנת מודלים).")
    env = dict(os.environ, OLLAMA_HOST="127.0.0.1:%d" % OWN_PORT, OLLAMA_MODELS=models,
               OLLAMA_NOPRUNE="1")
    log("AI: starting %s on %d (models %s)" % (exe, OWN_PORT, models))
    _proc = subprocess.Popen([exe, "serve"], env=env, cwd=os.path.dirname(exe),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    url = "http://127.0.0.1:%d" % OWN_PORT
    for _ in range(120):
        time.sleep(0.5)
        names = _tags(url)
        if names is not None:
            m = _pick(names)
            if not m:
                raise RuntimeError("אין מודל gemma4 בתיקיית המודלים של AutoPoint.")
            _found.update(url=url, model=m)
            return url, m
        if _proc.poll() is not None:
            break
    raise RuntimeError("מנוע ה-AI של AutoPoint לא עלה. אולי AutoPoint פתוח ומשתמש בו - לסגור ולנסות שוב.")


def stop():
    if _proc and _proc.poll() is None:
        _proc.terminate()


def unload():
    """Frees the GPU memory gemma holds, so Whisper can load again."""
    url, model = _found["url"], _found["model"]
    if not url:
        return
    try:
        _post(url + "/api/generate", {"model": model, "keep_alive": 0}, timeout=20).read()
    except Exception:
        pass


SYSTEM = (
    "אתה עוזר שמסדר תמלולים של הקלטות בעברית (ישיבות, שיחות, הרצאות, הודעות קוליות). "
    "התמלול נוצר אוטומטית ועלול להכיל טעויות זיהוי - תבין לפי ההקשר. "
    "כתוב הכל בעברית תקנית, ברורה וקצרה. אל תמציא פרטים שלא נאמרו. "
    "אם משהו לא נאמר (למשל מי אחראי או תאריך יעד) - השאר מחרוזת ריקה. "
    "ענה ב-JSON בלבד, בדיוק במבנה הזה:\n"
    '{"title": "כותרת קצרה להקלטה",\n'
    ' "summary": "סיכום של 2-5 משפטים",\n'
    ' "key_points": ["נקודה חשובה", "..."],\n'
    ' "topics": [{"title": "נושא", "time": "mm:ss", "points": ["מה נאמר עליו", "..."]}],\n'
    ' "tasks": [{"task": "מה צריך לעשות", "owner": "מי", "due": "מתי", "time": "mm:ss"}],\n'
    ' "decisions": ["החלטה שהתקבלה", "..."],\n'
    ' "timeline": [{"time": "mm:ss", "event": "מה קרה בנקודה הזאת בהקלטה"}],\n'
    ' "open_questions": ["שאלה שנשארה פתוחה", "..."]}\n'
    "ה-time הוא הזמן בהקלטה לפי הסימונים [mm:ss] בתמלול (אם אין סימונים - מחרוזת ריקה). "
    "ציר הזמן: 4-12 נקודות לפי סדר. רשימה ריקה [] אם אין מה לכתוב בה."
)


def _mmss(sec):
    sec = int(sec or 0)
    return "%d:%02d" % (sec // 60, sec % 60) if sec < 3600 else "%d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def transcript_lines(segs):
    return ["[%s] %s" % (_mmss(a), t.strip()) for a, _, t in segs if t.strip()]


def _chunks(lines):
    out, cur, n = [], [], 0
    for l in lines:
        if cur and n + len(l) > CHUNK_CHARS:
            out.append("\n".join(cur))
            cur, n = [], 0
        cur.append(l)
        n += len(l) + 1
    if cur:
        out.append("\n".join(cur))
    return out


def _chat(url, model, system, user, on_tokens=None):
    body = {"model": model, "stream": True, "format": "json", "keep_alive": "5m",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": 0.2, "num_ctx": NUM_CTX, "num_predict": 4096}}
    try:
        caps = json.loads(_post(url + "/api/show", {"model": model}, timeout=30).read()).get("capabilities") or []
        if "thinking" in caps:
            body["think"] = False
    except Exception:
        pass
    parts = []
    with _post(url + "/api/chat", body) as r:
        for line in r:
            if not line.strip():
                continue
            d = json.loads(line)
            if d.get("error"):
                raise RuntimeError(d["error"])
            parts.append((d.get("message") or {}).get("content", ""))
            if on_tokens:
                on_tokens(len(parts))
            if d.get("done"):
                break
    return "".join(parts)


def _parse(raw):
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.S)
    data = json.loads(m.group(0) if m else raw)
    return clean(data)


def clean(d):
    def strs(x):
        return [str(s).strip() for s in (x or []) if str(s).strip()] if isinstance(x, list) else []

    def objs(x, keys):
        out = []
        for o in x if isinstance(x, list) else []:
            if isinstance(o, dict):
                out.append({k: (strs(o.get(k)) if k == "points" else str(o.get(k) or "").strip()) for k in keys})
            elif str(o).strip():
                out.append({k: (str(o).strip() if i == 0 else ([] if k == "points" else ""))
                            for i, k in enumerate(keys)})
        return out

    d = d if isinstance(d, dict) else {}
    return {
        "title": str(d.get("title") or "").strip(),
        "summary": str(d.get("summary") or "").strip(),
        "key_points": strs(d.get("key_points")),
        "topics": objs(d.get("topics"), ["title", "time", "points"]),
        "tasks": [t for t in objs(d.get("tasks"), ["task", "owner", "due", "time"]) if t["task"]],
        "decisions": strs(d.get("decisions")),
        "timeline": [t for t in objs(d.get("timeline"), ["time", "event"]) if t["event"]],
        "open_questions": strs(d.get("open_questions")),
    }


def organize(segs, name, edited_text=None, progress=None, log=print):
    """segs: [(start, end, text)]. edited_text: the user's corrected text (no times) or None."""
    say = progress or (lambda msg: None)
    say("מתחבר למנוע ה-AI…")
    url, model = connect(log)
    lines = edited_text.splitlines() if edited_text else transcript_lines(segs)
    parts = _chunks([l for l in lines if l.strip()])
    results = []
    for i, part in enumerate(parts, 1):
        where = "" if len(parts) == 1 else " (חלק %d מתוך %d)" % (i, len(parts))
        say("טוען את %s לזיכרון…" % model if i == 1 else "מסדר" + where + "…")
        user = "שם הקובץ: %s\n\nהתמלול:\n%s" % (name, part)
        raw = _chat(url, model, SYSTEM, user,
                    lambda n: say("מסדר" + where + "… (%d)" % n))
        try:
            results.append(_parse(raw))
        except Exception:
            raw = _chat(url, model, SYSTEM, user + "\n\nענה ב-JSON תקין בלבד.")
            results.append(_parse(raw))
    if len(results) == 1:
        out = results[0]
    else:
        out = {k: [] for k in ("key_points", "topics", "tasks", "decisions", "timeline", "open_questions")}
        for r in results:
            for k in out:
                out[k] += r[k]
        say("מסכם את כל החלקים…")
        merged = "\n".join("- " + r["summary"] for r in results if r["summary"])
        raw = _chat(url, model,
                    'סכם בעברית. ענה ב-JSON בלבד: {"title": "כותרת קצרה", "summary": "2-5 משפטים"}',
                    "סיכומי החלקים של אותה הקלטה (%s):\n%s" % (name, merged))
        try:
            top = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        except Exception:
            top = {}
        out["title"] = str(top.get("title") or results[0]["title"])
        out["summary"] = str(top.get("summary") or " ".join(r["summary"] for r in results))
    out["model"] = model
    return out


def as_blocks(r):
    """The organized result as (kind, text) blocks, for Word and for plain-text copy."""
    b = [("title", r.get("title") or "סיכום")]
    if r.get("summary"):
        b += [("h", "סיכום"), ("p", r["summary"])]
    if r.get("key_points"):
        b += [("h", "נקודות עיקריות")] + [("li", x) for x in r["key_points"]]
    if r.get("tasks"):
        b.append(("h", "משימות"))
        for t in r["tasks"]:
            extra = " · ".join(x for x in (t["owner"] and "אחראי: " + t["owner"],
                                           t["due"] and "עד: " + t["due"]) if x)
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
