# Hebrew Whisper - local drag-and-drop page.
#
# Serves app/ui.html on http://127.0.0.1:<port>/ and transcribes files dropped on it, one at a
# time, with the same engine as transcribe.py. Nothing leaves this PC: the server only listens
# on 127.0.0.1. It exits by itself a minute after the last browser tab is closed.

import json
import os
import queue
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# The embeddable Python's ._pth file means the script folder is not on sys.path by itself.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.stdout is None:  # pythonw: no console, keep a log next to the outputs instead
    _log_dir = os.path.join(os.path.expanduser("~"), "Documents", "Hebrew-Whisper-Output")
    os.makedirs(_log_dir, exist_ok=True)
    sys.stdout = sys.stderr = open(os.path.join(_log_dir, "_log.txt"), "a", encoding="utf-8")

import ai  # noqa: E402
import projects  # noqa: E402
import window  # noqa: E402
import transcribe as engine  # noqa: E402

PORT = int(os.environ.get("HW_PORT", "8765"))
OUT_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Hebrew-Whisper-Output")
WORK_DIR = os.path.join(OUT_DIR, "_incoming")
UI = os.path.join(engine.HERE, "ui.html")
IDLE_EXIT_SEC = 90          # app window: its poll keeps running even when minimized
IDLE_EXIT_BROWSER_SEC = 900  # plain browser tab: background tabs poll rarely
win = {"closed": False, "app": False}

jobs = {}           # id -> dict
order = []          # ids, oldest first
todo = queue.Queue()
lock = threading.Lock()
status = {"model": "loading", "device": None, "error": None}
last_ping = [time.time()]
project = {"id": None, "name": "", "dirty": False}   # the work in the window; unsaved until Save


def touch():
    project["dirty"] = True


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def safe_name(name):
    name = os.path.basename(name.replace("\\", "/")) or "audio"
    bad = '<>:"/\\|?*'
    name = "".join("_" if c in bad or ord(c) < 32 else c for c in name).strip(". ")
    return name[:150] or "audio"


def unique_base(folder, stem):
    base = os.path.join(folder, stem)
    n = 2
    while os.path.exists(base + ".txt") or os.path.exists(base + ".docx"):
        base = os.path.join(folder, "%s (%d)" % (stem, n))
        n += 1
    return base


def load_model():
    try:
        dev = engine.pick_device()
        try:
            engine.get_model(dev)
        except Exception as e:
            if dev != "cuda":
                raise
            log("GPU load failed, using CPU: %s" % str(e).splitlines()[0][:200])
            dev = "cpu"
            engine.get_model(dev)
        engine.state["device"] = dev
        status.update(model="ready", device=dev)
        log("model ready on %s" % dev)
    except Exception as e:
        status.update(model="error", error=str(e).splitlines()[0][:300] if str(e) else repr(e))
        log("model load FAILED\n" + traceback.format_exc())


gpu = {"holder": "whisper"}   # which model holds the GPU now: "whisper" or "ai"


def free_whisper():
    # gemma4:26b (~17 GB) and Whisper large-v3 (~5 GB) together crowd a 24 GB card.
    import gc
    engine._models.clear()
    gc.collect()
    gpu["holder"] = "ai"


def run_ai(job, edited):
    job.update(ai_state="running", ai_msg="מתחיל…", ai_error=None)
    if gpu["holder"] == "whisper":
        free_whisper()

    def say(msg):
        job["ai_msg"] = msg

    try:
        segs = [tuple(x) for x in job["segments"]]
        res = ai.organize(segs, job["name"], edited or None, say, log)
        job.update(ai=res, ai_state="done", ai_msg="", done_tasks=[])
        touch()
        if job.get("out"):
            base = job["out"] + " - סיכום AI"
            with open(base + ".docx", "wb") as f:
                f.write(engine.docx_from_blocks(ai.as_blocks(res)))
            with open(base + ".txt", "w", encoding="utf-8-sig") as f:
                f.write(ai.as_text(res))
        log("AI done %s (%s)" % (job["name"], res.get("model")))
    except Exception as e:
        msg = str(e).splitlines()[0][:300] if str(e) else repr(e)
        if "Connection refused" in msg or "actively refused" in msg or "timed out" in msg:
            msg = "אין חיבור למנוע ה-AI (%s)" % msg
        job.update(ai_state="error", ai_error=msg)
        log("AI FAILED %s\n%s" % (job["name"], traceback.format_exc()))


def worker():
    load_model()
    while True:
        item = todo.get()
        kind, jid = ("transcribe", item) if isinstance(item, str) else item[:2]
        job = jobs.get(jid)
        if not job or job["state"] == "cancelled":
            continue
        if kind == "ai":
            run_ai(job, item[2])
            continue
        if gpu["holder"] == "ai":
            ai.unload()
            gpu["holder"] = "whisper"
        if status["model"] != "ready":
            job.update(state="error", error="המודל לא נטען: %s" % status["error"])
            continue
        job.update(state="running", started=time.time())

        def progress(pct, segs, job=job):
            job["progress"] = pct
            job["segments"] = [[a, z, t] for a, z, t in segs]

        try:
            segs, dur = engine.transcribe(job["path"], progress)
            job["segments"] = [[a, z, t] for a, z, t in segs]
            base = unique_base(OUT_DIR, os.path.splitext(job["name"])[0])
            engine.write_outputs(base + ".x", segs)
            job.update(state="done", progress=100.0, duration=dur, out=base,
                       seconds=time.time() - job["started"], device=engine.state["device"])
            touch()
            log("done %s (%.0fs)" % (job["name"], job["seconds"]))
        except Exception as e:
            msg = str(e).splitlines()[0][:300] if str(e) else repr(e)
            if "Invalid data" in msg or "could not" in msg.lower() or "decode" in msg.lower():
                msg = "הקובץ לא נקרא כשמע או וידאו. אולי הוא פגום או בפורמט אחר."
            job.update(state="error", error=msg)
            log("FAILED %s\n%s" % (job["name"], traceback.format_exc()))
        finally:
            try:
                os.remove(job["path"])
            except OSError:
                pass


def public(job):
    keys = ("id", "name", "size", "state", "progress", "error", "duration", "seconds", "device", "out",
            "ai_state", "ai_msg", "ai_error", "ai", "edited", "done_tasks")
    d = {k: job.get(k) for k in keys}
    d["text"] = engine.plain_text(job.get("segments", []))
    return d


def busy():
    return any(j["state"] in ("queued", "running") or j.get("ai_state") in ("queued", "running")
               for j in jobs.values())


def replace_jobs(new_jobs, pid=None, name="", dirty=False):
    with lock:
        jobs.clear()
        order.clear()
        for j in new_jobs:
            j.setdefault("progress", 100.0 if j.get("state") == "done" else 0.0)
            j.setdefault("segments", [])
            jobs[j["id"]] = j
            order.append(j["id"])
        project.update(id=pid, name=name, dirty=dirty)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        last_ping[0] = time.time()
        if u.path == "/":
            with open(UI, "rb") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        if u.path == "/icon.ico":
            with open(os.path.join(engine.HERE, "icon.ico"), "rb") as f:
                return self.send(200, f.read(), "image/x-icon")
        if u.path == "/api/status":
            with lock:
                return self.send(200, {"model": status, "out_dir": OUT_DIR, "project": project,
                                       "jobs": [public(jobs[i]) for i in order if i in jobs]})
        if u.path == "/api/history":
            return self.send(200, {"projects": projects.listing()})
        if u.path == "/api/ai-file":
            job = jobs.get((q.get("id") or [""])[0])
            fmt = (q.get("fmt") or ["docx"])[0]
            if not job or not job.get("ai") or fmt not in ("docx", "txt"):
                return self.send(404, {"error": "not found"})
            stem = os.path.splitext(job["name"])[0] + " - סיכום AI"
            if fmt == "docx":
                data = engine.docx_from_blocks(ai.as_blocks(job["ai"]))
                ctype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            else:
                data = ("\ufeff" + ai.as_text(job["ai"]).replace("\n", "\r\n")).encode("utf-8")
                ctype = "text/plain; charset=utf-8"
            cd = "attachment; filename*=UTF-8''" + urllib.parse.quote(stem + "." + fmt)
            return self.send(200, data, ctype, {"Content-Disposition": cd})
        if u.path == "/api/open-folder":
            os.makedirs(OUT_DIR, exist_ok=True)
            os.startfile(OUT_DIR)
            return self.send(200, {"ok": True})
        return self.send(404, {"error": "not found"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        last_ping[0] = time.time()
        if u.path == "/api/upload":
            name = safe_name((q.get("name") or ["audio"])[0])
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return self.send(400, {"error": "empty"})
            os.makedirs(WORK_DIR, exist_ok=True)
            jid = uuid.uuid4().hex[:12]
            path = os.path.join(WORK_DIR, jid + "_" + name)
            left = length
            with open(path, "wb") as f:
                while left > 0:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            if left:
                os.remove(path)
                return self.send(400, {"error": "upload cut"})
            with lock:
                jobs[jid] = {"id": jid, "name": name, "size": length, "path": path, "created": time.time(),
                             "state": "queued", "progress": 0.0, "segments": []}
                order.append(jid)
                touch()
            todo.put(jid)
            return self.send(200, {"id": jid})
        if u.path == "/api/save":
            # The page sends the (possibly edited) text back; we return it as a file to save.
            fmt = (q.get("fmt") or ["txt"])[0]
            stem = os.path.splitext(safe_name((q.get("name") or ["transcript"])[0]))[0]
            length = int(self.headers.get("Content-Length") or 0)
            text = self.rfile.read(length).decode("utf-8", "replace") if length else ""
            if fmt == "docx":
                data = engine.docx_bytes(text, stem)
                ctype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            elif fmt == "txt":
                data = ("\ufeff" + text.replace("\r\n", "\n").replace("\n", "\r\n")).encode("utf-8")
                ctype = "text/plain; charset=utf-8"
            else:
                return self.send(400, {"error": "fmt"})
            cd = "attachment; filename*=UTF-8''" + urllib.parse.quote(stem + "." + fmt)
            return self.send(200, data, ctype, {"Content-Disposition": cd})
        if u.path == "/api/ai":
            jid = (q.get("id") or [""])[0]
            length = int(self.headers.get("Content-Length") or 0)
            edited = self.rfile.read(length).decode("utf-8", "replace") if length else ""
            job = jobs.get(jid)
            edited = edited or (job or {}).get("edited") or ""
            if not job or job["state"] != "done":
                return self.send(400, {"error": "not ready"})
            if job.get("ai_state") in ("queued", "running"):
                return self.send(200, {"ok": True})
            job.update(ai_state="queued", ai_msg="ממתין בתור…", ai_error=None, ai=None)
            todo.put(("ai", jid, edited))
            return self.send(200, {"ok": True})
        if u.path == "/api/remove":
            jid = (q.get("id") or [""])[0]
            with lock:
                job = jobs.get(jid)
                if job and job["state"] in ("queued",):
                    job["state"] = "cancelled"
                if job and job["state"] != "running":
                    jobs.pop(jid, None)
                    if jid in order:
                        order.remove(jid)
                    touch()
            return self.send(200, {"ok": True})
        if u.path == "/api/edit":
            # The user's corrections to a transcript (empty body = back to the original).
            job = jobs.get((q.get("id") or [""])[0])
            length = int(self.headers.get("Content-Length") or 0)
            text = self.rfile.read(length).decode("utf-8", "replace") if length else ""
            if job:
                job["edited"] = text or None
                touch()
            return self.send(200, {"ok": True})
        if u.path == "/api/task":
            job = jobs.get((q.get("id") or [""])[0])
            if job:
                k = int((q.get("k") or ["-1"])[0])
                on = (q.get("v") or ["1"])[0] == "1"
                done = set(job.get("done_tasks") or [])
                (done.add if on else done.discard)(k)
                job["done_tasks"] = sorted(done)
                touch()
            return self.send(200, {"ok": True})
        if u.path == "/api/project/save":
            name = ((q.get("name") or [""])[0]).strip()[:120] or project["name"] or "פרויקט ללא שם"
            with lock:
                snap = [jobs[i] for i in order if i in jobs]
            pid = projects.save(project["id"], name, snap)
            project.update(id=pid, name=name, dirty=False)
            log("project saved: %s (%d recordings)" % (name, len(snap)))
            return self.send(200, {"ok": True, "id": pid})
        if u.path in ("/api/project/new", "/api/project/open"):
            if busy():
                return self.send(409, {"error": "busy"})
            if u.path.endswith("/new"):
                replace_jobs([])
            else:
                try:
                    d = projects.load((q.get("id") or [""])[0])
                except (OSError, ValueError):
                    return self.send(404, {"error": "not found"})
                replace_jobs(d.get("jobs") or [], d.get("id"), d.get("name") or "")
            return self.send(200, {"ok": True})
        if u.path == "/api/project/delete":
            pid = (q.get("id") or [""])[0]
            projects.delete(pid)
            if project["id"] == pid:
                project.update(id=None, dirty=bool(jobs))
            return self.send(200, {"ok": True})
        return self.send(404, {"error": "not found"})


def idle_watch(server):
    while True:
        time.sleep(10)

        limit = IDLE_EXIT_SEC if win["app"] else IDLE_EXIT_BROWSER_SEC
        if not busy() and (win["closed"] or time.time() - last_ping[0] > limit):
            log("window closed / no page - exiting")
            server.shutdown()
            return


def watch_window(proc):
    t0 = time.time()
    proc.wait()
    # A browser that was already running hands the window over and exits at once; only a
    # long-lived process ending means the user closed the window.
    if time.time() - t0 > 5:
        win["closed"] = True


def main():
    url = "http://127.0.0.1:%d/" % PORT
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        # Already running (second double-click): just show the window again.
        window.open_window(url)
        return 0
    os.makedirs(OUT_DIR, exist_ok=True)
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=idle_watch, args=(server,), daemon=True).start()
    log("Hebrew Whisper on %s" % url)
    if os.environ.get("HW_NO_BROWSER") != "1":
        window.ensure_shortcut(engine.ROOT)
        proc = window.open_window(url)
        if proc:
            win["app"] = True
            threading.Thread(target=watch_window, args=(proc,), daemon=True).start()
    try:
        server.serve_forever()
    finally:
        ai.stop()
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
