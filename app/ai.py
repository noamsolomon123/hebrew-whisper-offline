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
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

from ai_post import _dedupe_strs, _mmss, _repair, as_blocks, as_text, clean  # noqa: F401 (re-exported)
from ai_prompts import FIX_JSON, MERGE_SYSTEM, PART_NOTE, SECTION_HE, SYSTEM

PREFERRED = ["gemma4:26b", "gemma4:12b", "gemma4:latest", "gemma4:12b-it-qat", "gemma4:e4b",
             "qwen2.5:14b", "gemma4:e2b"]
PROBE_PORTS = list(range(11434, 11441))
OWN_PORT = 11441
CHUNK_CHARS = 14000   # ~ one Hebrew chunk (~5k tokens) well inside 16k ctx, with room for the answer
NUM_PREDICT = 4096

_proc = None
_found = {"url": None, "model": None, "think": None}


def _get(url, timeout=2.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(url, body, timeout=900.0):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def _tags(url, timeout=2.0):
    try:
        return [m["name"] for m in _get(url + "/api/tags", timeout).get("models", [])]
    except Exception:
        return None


def _pick(names):
    want = os.environ.get("HW_AI_MODEL")
    if want and want in names:
        return want
    for p in PREFERRED:
        if p in names:
            return p
    g = [n for n in names if n.startswith("gemma")]
    return g[0] if g else None


def _port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def _autopoint_dirs():
    # Per-user NSIS install: %LOCALAPPDATA%\Programs\AutoPoint by default; the uninstall key
    # knows the real place if the owner picked another folder (or a per-machine install).
    roots = []
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for path in (r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
                         r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
                try:
                    k = winreg.OpenKey(hive, path)
                except OSError:
                    continue
                for i in range(winreg.QueryInfoKey(k)[0]):
                    try:
                        sub = winreg.OpenKey(k, winreg.EnumKey(k, i))
                        if str(winreg.QueryValueEx(sub, "DisplayName")[0]).lower().startswith("autopoint"):
                            try:
                                roots.append(winreg.QueryValueEx(sub, "InstallLocation")[0])
                            except OSError:
                                un = str(winreg.QueryValueEx(sub, "UninstallString")[0]).strip('"')
                                roots.append(os.path.dirname(un.split('" ')[0]))
                    except OSError:
                        pass
    except ImportError:
        pass
    la = os.environ.get("LOCALAPPDATA", "")
    roots += [os.path.join(la, "Programs", "AutoPoint"), os.path.join(la, "Programs", "autopoint")]
    for pf in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if pf:
            roots.append(os.path.join(pf, "AutoPoint"))
    out = []
    for r in roots:
        r = (r or "").strip().strip('"')
        if r and os.path.isdir(r) and r not in out:
            out.append(r)
    return out


def _local_models(d):
    lib = os.path.join(d, "manifests", "registry.ollama.ai", "library")
    return [os.path.basename(os.path.dirname(p)) + ":" + os.path.basename(p)
            for p in glob.glob(os.path.join(lib, "*", "*"))]


def _find_exe_and_models():
    exe = os.environ.get("HW_OLLAMA_EXE")
    models = os.environ.get("HW_OLLAMA_MODELS")
    if not exe:
        for r in _autopoint_dirs():
            for c in (os.path.join(r, "resources", "ollama", "ollama.exe"),
                      os.path.join(r, "resources", "app.asar.unpacked", "ollama", "ollama.exe")):
                if os.path.isfile(c):
                    exe = c
                    break
            if exe:
                break
    if not models:
        ad = os.environ.get("APPDATA", "")
        cands = [os.path.join(ad, "AutoPoint", "ollama", "models"), os.path.join(ad, "autopoint", "ollama", "models")]
        if exe:
            cands.insert(0, os.path.join(os.path.dirname(exe), "models"))
        if os.environ.get("OLLAMA_MODELS"):
            cands.append(os.environ["OLLAMA_MODELS"])
        cands.append(os.path.join(os.path.expanduser("~"), ".ollama", "models"))
        models = next((c for c in cands if _pick(_local_models(c))), None)
    return exe, models


def _probe(urls):
    """Asks all candidate ports at once (a hung port costs 2 s, not 2 s each)."""
    res = {}

    def one(u):
        res[u] = _tags(u)
    ts = [threading.Thread(target=one, args=(u,), daemon=True) for u in urls]
    for t in ts:
        t.start()
    for t in ts:
        t.join(3)
    return [(u, res.get(u)) for u in urls]


def connect(log=print):
    """Returns (url, model) or raises RuntimeError with a Hebrew message."""
    global _proc
    if _found["url"] and _tags(_found["url"]) is not None:
        return _found["url"], _found["model"]
    if os.environ.get("HW_OLLAMA_URL"):
        urls = [os.environ["HW_OLLAMA_URL"].rstrip("/")]
        names = _tags(urls[0], 5)
        if names is None:
            raise RuntimeError("מנוע ה-AI לא עונה בכתובת %s (HW_OLLAMA_URL)." % urls[0])
        if not _pick(names):
            raise RuntimeError("במנוע ה-AI בכתובת %s אין מודל gemma4." % urls[0])
        _found.update(url=urls[0], model=_pick(names), think=None)
        return urls[0], _found["model"]
    running_without_model = False
    for url, names in _probe(["http://127.0.0.1:%d" % p for p in PROBE_PORTS + [OWN_PORT]]):
        if names is None:
            continue
        if _pick(names):
            _found.update(url=url, model=_pick(names), think=None)
            log("AI: using running Ollama %s, model %s" % (url, _found["model"]))
            return url, _found["model"]
        running_without_model = True
    exe, models = _find_exe_and_models()
    if not exe:
        raise RuntimeError("לא נמצא AutoPoint במחשב הזה, וה-AI מגיע ממנו. "
                           "אם AutoPoint מותקן - לפתוח אותו פעם אחת ולנסות שוב.")
    if not models:
        raise RuntimeError("נמצא AutoPoint, אבל בלי מודל gemma4 מותקן. "
                           "ב-AutoPoint: הגדרות > התקנת מודלים, ואז לנסות שוב."
                           + (" (יש מנוע AI פתוח, אבל בלי gemma4.)" if running_without_model else ""))
    port = next((p for p in range(OWN_PORT, OWN_PORT + 5) if not _port_open(p)), None)
    if port is None:
        raise RuntimeError("אין פורט פנוי להפעלת מנוע ה-AI (11441-11445 תפוסים).")
    env = dict(os.environ, OLLAMA_HOST="127.0.0.1:%d" % port, OLLAMA_MODELS=models, OLLAMA_NOPRUNE="1")
    log("AI: starting %s on %d (models %s)" % (exe, port, models))
    try:
        _proc = subprocess.Popen([exe, "serve"], env=env, cwd=os.path.dirname(exe),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:
        raise RuntimeError("לא הצלחתי להפעיל את מנוע ה-AI של AutoPoint (%s)." % e)
    url = "http://127.0.0.1:%d" % port
    for _ in range(120):
        time.sleep(0.5)
        names = _tags(url)
        if names is not None:
            m = _pick(names)
            if not m:
                raise RuntimeError("מנוע ה-AI עלה, אבל אין בו מודל gemma4 (תיקיית מודלים: %s)." % models)
            _found.update(url=url, model=m, think=None)
            return url, m
        if _proc.poll() is not None:
            break
    raise RuntimeError("מנוע ה-AI של AutoPoint לא עלה. אם AutoPoint פתוח - לסגור אותו ולנסות שוב, "
                       "או לפתוח אותו ולחכות שה-AI שלו יעלה.")


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


def _ctx_for(chars):
    # Hebrew is ~3 chars/token for gemma; one size per recording so chunks never reload the model.
    need = chars // 3 + 2500 + NUM_PREDICT
    return 8192 if need <= 8192 else 16384 if need <= 16384 else 32768


def _chat(url, model, system, user, num_ctx, on_text=None, temperature=0.2):
    body = {"model": model, "stream": True, "format": "json", "keep_alive": "10m",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": temperature, "top_p": 0.9, "num_ctx": num_ctx,
                        "num_predict": NUM_PREDICT, "repeat_penalty": 1.05}}
    if _found.get("think") is None:
        try:
            caps = json.loads(_post(url + "/api/show", {"model": model}, timeout=30).read()).get("capabilities") or []
            _found["think"] = "thinking" in caps
        except Exception:
            _found["think"] = False
    if _found["think"]:
        body["think"] = False
    parts = []
    try:
        with _post(url + "/api/chat", body) as r:
            for line in r:
                if not line.strip():
                    continue
                d = json.loads(line)
                if d.get("error"):
                    raise RuntimeError(d["error"])
                parts.append((d.get("message") or {}).get("content", ""))
                if on_text and len(parts) % 8 == 0:
                    on_text("".join(parts))
                if d.get("done"):
                    break
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError("מנוע ה-AI החזיר שגיאה (%d): %s" % (e.code, msg))
    except (urllib.error.URLError, ConnectionError, socket.timeout) as e:
        _found["url"] = None
        raise RuntimeError("החיבור למנוע ה-AI נותק (%s). לנסות שוב; אם חוזר - לפתוח מחדש את התוכנה." % e)
    return "".join(parts)


def _progress(say, where):
    state = {"sec": None, "t": 0.0}

    def on_text(txt):
        keys = re.findall(r'"(%s)"\s*:' % "|".join(SECTION_HE), txt)
        sec = keys[-1] if keys else None
        now = time.time()
        if sec != state["sec"] or now - state["t"] > 3:
            state.update(sec=sec, t=now)
            say(("כותב%s: %s…" % (where, SECTION_HE[sec])) if sec else ("מסדר%s…" % where))
    return on_text


def _ask(url, model, system, user, num_ctx, on_text, log):
    raw = _chat(url, model, system, user, num_ctx, on_text)
    try:
        return _repair(raw)
    except ValueError:
        log("AI: invalid JSON, retrying once (%d chars)" % len(raw))
        raw = _chat(url, model, system, user + "\n\n" + FIX_JSON, num_ctx, on_text, temperature=0.0)
        try:
            return _repair(raw)
        except ValueError:
            raise RuntimeError("מודל ה-AI החזיר פעמיים תשובה לא תקינה. לנסות שוב.")


def organize(segs, name, edited_text=None, progress=None, log=print):
    """segs: [(start, end, text)]. edited_text: the user's corrected text (no times) or None."""
    say = progress or (lambda msg: None)
    say("מתחבר למנוע ה-AI…")
    url, model = connect(log)
    if edited_text and edited_text.strip():
        lines = [l for l in edited_text.splitlines() if l.strip()]
        timed, dur = None, 0
    else:
        lines = transcript_lines(segs)
        timed = [(a, t.strip()) for a, _, t in segs if t.strip()]
        dur = max((b for _, b, _ in segs), default=0) or None
    if not lines:
        raise RuntimeError("אין טקסט לסדר - התמלול ריק.")
    src = " ".join(re.sub(r"^\[[\d:]+\]\s*", "", l) for l in lines)
    parts = _chunks(lines)
    num_ctx = _ctx_for(max(len(p) for p in parts))
    t0 = time.time()
    results = []
    for i, part in enumerate(parts, 1):
        where = "" if len(parts) == 1 else " (חלק %d מתוך %d)" % (i, len(parts))
        say(("טוען את %s לזיכרון…" % model) if i == 1 else "מסדר" + where + "…")
        note = PART_NOTE % (i, len(parts)) if len(parts) > 1 else ""
        user = "שם הקובץ: %s\n%s\nהתמלול:\n%s" % (name, note, part)
        data = _ask(url, model, SYSTEM, user, num_ctx, _progress(say, where), log)
        results.append(clean(data, src, dur, timed))
    if len(results) == 1:
        out = results[0]
    else:
        out = _merge(results, url, model, name, num_ctx, say, log, src, dur, timed)
    log("AI: organized in %.0f s (%d part(s), ctx %d)" % (time.time() - t0, len(parts), num_ctx))
    out["model"] = model
    return out


def _merge(results, url, model, name, num_ctx, say, log, src, dur, timed):
    """Joins chunk results: one summary over all parts, lists deduped and kept in time order."""
    say("מסכם את כל החלקים…")
    joined = {"tasks": [], "topics": [], "timeline": [], "speakers": [], "decisions": [],
              "open_questions": [], "key_points": []}
    for r in results:
        for k in joined:
            joined[k] += r[k]
    merged = clean(joined, src, dur, timed)
    tl = merged["timeline"]
    if len(tl) > 14:  # keep it a readable overview: evenly spaced
        step = len(tl) / 14.0
        merged["timeline"] = [tl[int(i * step)] for i in range(14)]
    digest = "\n\n".join("חלק %d:\n%s\nנקודות: %s" % (i, r["summary"], "; ".join(r["key_points"][:8]))
                         for i, r in enumerate(results, 1))
    try:
        top = _ask(url, model, MERGE_SYSTEM, "הקלטה: %s\n\n%s" % (name, digest), num_ctx,
                   _progress(say, " (סיכום כללי)"), log)
    except Exception as e:  # noqa - the parts are still useful without the overall summary
        log("AI: merge summary failed: %s" % e)
        top = {}
    top = top if isinstance(top, dict) else {}
    kp = [str(x).strip() for x in (top.get("key_points") or []) if str(x).strip()] if isinstance(top.get("key_points"), list) else []
    merged["title"] = str(top.get("title") or results[0]["title"]).strip()
    merged["summary"] = str(top.get("summary") or " ".join(r["summary"] for r in results)).strip()
    merged["key_points"] = _dedupe_strs(kp) or merged["key_points"][:10]
    merged["kind"] = results[0].get("kind", "")
    return merged
