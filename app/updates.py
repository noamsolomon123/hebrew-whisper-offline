# Finds an update kit in the updates folder and hands it to the kit's own apply_update.py.
#
# The folder is chosen once per PC (in the app, or remembered by UPDATE-HEBREW-WHISPER.bat) and
# kept in <install>\_updates\folder.txt. A kit is a folder HebrewWhisper-<v>-Update holding
# update.json; Windows' "Extract All" puts it one level deeper (...-Update-Kit\...-Update),
# which is found too. Stdlib only.

import json
import os
import subprocess
import threading
import time

from version import VERSION

APP_ID = "hebrew-whisper"
CHECK_EVERY_SEC = 600


def vtuple(v):
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except ValueError:
        return (0,)


class Updates:
    def __init__(self, root, log=print):
        self.root = root
        self.dir = os.path.join(root, "_updates")
        self.log = log
        self.found = None        # {"version", "notes", "kit"}
        self.error = None        # why the folder could not be read
        self.checked = None
        self.last = self._take_last()
        self._lock = threading.Lock()

    # ---- the folder ---------------------------------------------------------------------
    def folder(self):
        try:
            with open(os.path.join(self.dir, "folder.txt"), encoding="utf-8") as f:
                return f.read().strip() or None
        except OSError:
            return None

    def set_folder(self, path):
        path = (path or "").strip().strip('"')
        if path and not os.path.isdir(path):
            raise ValueError("התיקייה לא נמצאה: %s" % path)
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, "folder.txt"), "w", encoding="utf-8") as f:
            f.write(path)
        return self.check()

    # ---- looking --------------------------------------------------------------------------
    def _kits(self, folder):
        out = []
        for name in os.listdir(folder):
            d = os.path.join(folder, name)
            if not os.path.isdir(d):
                continue
            for k in [d] + [os.path.join(d, n) for n in os.listdir(d) if os.path.isdir(os.path.join(d, n))]:
                if os.path.isfile(os.path.join(k, "update.json")) and os.path.isfile(os.path.join(k, "apply_update.py")):
                    out.append(k)
        return out

    def check(self):
        with self._lock:
            self.checked = time.time()
            folder = self.folder()
            self.found, self.error = None, None
            if not folder:
                return self.state()
            try:
                best = None
                for k in self._kits(folder):
                    try:
                        with open(os.path.join(k, "update.json"), encoding="utf-8") as f:
                            u = json.load(f)
                    except (OSError, ValueError):
                        continue
                    v = u.get("version", "0")
                    if (u.get("app") != APP_ID or vtuple(v) <= vtuple(VERSION) or
                            vtuple(u.get("base", "1.0.0")) > vtuple(VERSION)):
                        continue
                    if best is None or vtuple(v) > vtuple(best["version"]):
                        best = {"version": v, "notes": u.get("notes_he") or [], "kit": k}
                self.found = best
            except OSError as e:
                self.error = "אין גישה לתיקיית העדכונים: %s" % e
            return self.state()

    def loop(self):
        while True:
            try:
                self.check()
            except Exception as e:   # never let the checker take the app down
                self.log("update check failed: %s" % e)
            time.sleep(CHECK_EVERY_SEC)

    def state(self):
        f = self.found
        return {"version": VERSION, "folder": self.folder(), "error": self.error,
                "available": {"version": f["version"], "notes": f["notes"]} if f else None,
                "last": self.last}

    # ---- installing -----------------------------------------------------------------------
    def apply(self):
        """Starts the kit's installer, detached. It waits for this app to close, installs,
        and starts the app again without a new window (the open page reloads itself)."""
        f = self.found
        if not f:
            raise ValueError("no update")
        exe = os.path.join(self.root, "python", "pythonw.exe")
        script = os.path.join(f["kit"], "apply_update.py")
        subprocess.Popen([exe, "-X", "utf8", script, "--kit", f["kit"], "--root", self.root,
                          "--quiet-restart", "--wait", "120"], cwd=self.root,
                         creationflags=0x00000008 | 0x00000200, close_fds=True)
        self.log("update to %s started from %s" % (f["version"], f["kit"]))

    def _take_last(self):
        # The result of the last install, shown once on the next start.
        p = os.path.join(self.dir, "last.json")
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            os.replace(p, p + ".seen")
            d.pop("log", None)
            return d
        except (OSError, ValueError):
            return None
