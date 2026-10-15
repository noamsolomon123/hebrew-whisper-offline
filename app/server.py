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
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# The embeddable Python's ._pth file means the script folder is not on sys.path by itself.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.stdout is None:  # pythonw: no console, keep a log next to the outputs instead
    _log_dir = os.path.join(os.path.expanduser("~"), "Documents", "Hebrew-Whisper-Output")
    os.makedirs(_log_dir, exist_ok=True)
    sys.stdout = sys.stderr = open(os.path.join(_log_dir, "_log.txt"), "a", encoding="utf-8")

import transcribe as engine  # noqa: E402

PORT = int(os.environ.get("HW_PORT", "8765"))
OUT_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Hebrew-Whisper-Output")
WORK_DIR = os.path.join(OUT_DIR, "_incoming")
UI = os.path.join(engine.HERE, "ui.html")
IDLE_EXIT_SEC = 60

jobs = {}           # id -> dict
order = []          # ids, oldest first
todo = queue.Queue()
lock = threading.Lock()
status = {"model": "loading", "device": None, "error": None}
last_ping = [time.time()]


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
    while os.path.exists(base + ".txt") or os.path.exists(base + ".srt"):
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


def worker():
    load_model()
    while True:
        jid = todo.get()
        job = jobs.get(jid)
        if not job or job["state"] == "cancelled":
            continue
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
    keys = ("id", "name", "size", "state", "progress", "error", "duration", "seconds", "device", "out")
    d = {k: job.get(k) for k in keys}
    d["segments"] = job.get("segments", [])
    return d


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
        if u.path == "/api/status":
            with lock:
                return self.send(200, {"model": status, "out_dir": OUT_DIR,
                                       "jobs": [public(jobs[i]) for i in order if i in jobs]})
        if u.path == "/api/download":
            job = jobs.get((q.get("id") or [""])[0])
            fmt = (q.get("fmt") or ["txt"])[0]
            if not job or job["state"] != "done" or fmt not in ("txt", "srt"):
                return self.send(404, {"error": "not found"})
            path = job["out"] + "." + fmt
            with open(path, "rb") as f:
                data = f.read()
            fn = os.path.splitext(job["name"])[0] + "." + fmt
            cd = "attachment; filename*=UTF-8''" + urllib.parse.quote(fn)
            return self.send(200, data, "text/plain; charset=utf-8", {"Content-Disposition": cd})
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
                jobs[jid] = {"id": jid, "name": name, "size": length, "path": path,
                             "state": "queued", "progress": 0.0, "segments": []}
                order.append(jid)
            todo.put(jid)
            return self.send(200, {"id": jid})
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
            return self.send(200, {"ok": True})
        return self.send(404, {"error": "not found"})


def idle_watch(server):
    while True:
        time.sleep(10)
        busy = any(j["state"] in ("queued", "running") for j in jobs.values())
        if not busy and time.time() - last_ping[0] > IDLE_EXIT_SEC:
            log("no open page for %ds - exiting" % IDLE_EXIT_SEC)
            server.shutdown()
            return


def main():
    url = "http://127.0.0.1:%d/" % PORT
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        # Already running (second double-click): just show the page again.
        webbrowser.open(url)
        return 0
    os.makedirs(OUT_DIR, exist_ok=True)
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=idle_watch, args=(server,), daemon=True).start()
    log("Hebrew Whisper on %s" % url)
    if os.environ.get("HW_NO_BROWSER") != "1":
        webbrowser.open(url)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
