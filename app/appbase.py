# Startup plumbing for server.py: where files go, owning the port, guarding requests,
# crash-safe autosave and a visible error when pythonw has no console. Stdlib only.

import ctypes
import json
import os
import shutil
import socket
import urllib.request
from http.server import ThreadingHTTPServer

APP_ID = "hebrew-whisper"
PORTS = list(range(8765, 8771))


def documents_dir():
    # The real Documents folder (may be redirected to OneDrive or a network drive), not ~\Documents.
    try:
        from ctypes import wintypes
        FOLDERID_Documents = (ctypes.c_byte * 16).from_buffer_copy(
            bytes.fromhex("D0 9A D3 FD 8F 23 AF 46 AD B4 6C 85 48 03 69 C7"))
        path = wintypes.LPWSTR()
        if ctypes.windll.shell32.SHGetKnownFolderPath(FOLDERID_Documents, 0, None, ctypes.byref(path)) == 0:
            p = path.value
            ctypes.windll.ole32.CoTaskMemFree(path)
            if p and os.path.isdir(p):
                return p
    except Exception:
        pass
    p = os.path.join(os.path.expanduser("~"), "Documents")
    return p if os.path.isdir(p) else os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")


def _writable(d):
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".write-test")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def out_dir():
    # A folder that already holds our work wins (history lives there); then the real Documents
    # (may be redirected, or blocked by OneDrive / Controlled Folder Access); then the local fallbacks.
    home_docs = os.path.join(os.path.expanduser("~"), "Documents")
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    bases = ([home_docs] if os.path.isdir(home_docs) else []) + [documents_dir(), local]
    names = [os.path.join(b, "Hebrew-Whisper-Output") for b in bases]
    for d in [n for n in names if os.path.isdir(os.path.join(n, "_projects"))] + names:
        if _writable(d):
            return d
    raise OSError("no writable folder for the output")


def message_box(text, title="Hebrew Whisper"):
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
    except Exception:
        pass


class ExclusiveServer(ThreadingHTTPServer):
    # Python sets SO_REUSEADDR, which on Windows lets a second process share the port.
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def is_ours(port):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % port, timeout=1.5) as r:
            return json.loads(r.read().decode("utf-8")).get("app") == APP_ID
    except Exception:
        return False


def bind(handler, first_port):
    """-> (server, port) for a new instance, or (None, port) when this app already runs there."""
    ports = [first_port] + [p for p in PORTS if p != first_port]
    for p in ports:
        try:
            return ExclusiveServer(("127.0.0.1", p), handler), p
        except OSError:
            if is_ours(p):
                return None, p
    raise OSError("ports %d-%d are all taken" % (PORTS[0], PORTS[-1]))


def request_ok(handler, port, post):
    """Only this app's own page may use the API: blocks other web pages in the browser."""
    host = (handler.headers.get("Host") or "").lower()
    if host not in ("127.0.0.1:%d" % port, "localhost:%d" % port):
        return False
    origin = handler.headers.get("Origin")
    if origin and origin.lower() not in ("http://127.0.0.1:%d" % port, "http://localhost:%d" % port):
        return False
    return not post or handler.headers.get("X-HW") == "1"


def free_bytes(path):
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def clean_incoming(folder, keep_paths):
    if not os.path.isdir(folder):
        return
    for n in os.listdir(folder):
        p = os.path.join(folder, n)
        if p not in keep_paths:
            try:
                os.remove(p)
            except OSError:
                pass


def write_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
