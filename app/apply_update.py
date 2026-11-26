# Hebrew Whisper - installs an update kit, or puts the previous version back.
#
# Travels inside every update kit (HebrewWhisper-<v>-Update\apply_update.py) and runs with the
# INSTALLED python, so it works on any installed version - also on 1.0.0, which has no updater.
# Stdlib only.
#
#   python apply_update.py --kit <kit folder> --root <install> [--restart] [--quiet-restart]
#                          [--remember] [--wait 60] [--force]
#   python apply_update.py --restore --root <install> [--restart]
#
# What an install does, in this order (nothing changes until step 4):
#   1. the kit is whole: every payload file's SHA-256 matches update.json
#   2. this install may take it: installed version >= kit "base", < kit "version"
#   3. this install is the "base" the kit was built against: every file the kit does NOT carry
#      (except the big model) has the SHA-256 the base had - otherwise the kit would leave old
#      files next to new ones, so it refuses
#   4. Hebrew Whisper is closed (waits for it when the app itself started us)
#   5. every file the kit replaces or removes is copied to _updates\backup-<from>-to-<to>\
#   6. the new files go in (each written beside, then renamed over), old ones listed in
#      "remove" go away, manifest.sha256 is brought up to date
#   7. everything is checked again; any error -> the backup goes back (rollback)
# The result is written to _updates\last.json; the app shows it on its next start.

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

APP_ID = "hebrew-whisper"
PORTS = range(8765, 8771)
SKIP_BASE_CHECK = ("model/",)   # 3 GB, never changes inside a version line; hashing takes a minute
LOG = []
GUI = sys.stdout is None or os.path.basename(sys.executable).lower() == "pythonw.exe"


def say(msg):
    line = time.strftime("%H:%M:%S ") + msg
    LOG.append(line)
    if sys.stdout is not None:
        print("  " + msg, flush=True)


def box(text, error=False):
    if not GUI:
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, text, "Hebrew Whisper - update", 0x10 if error else 0x40)
    except Exception:
        pass


def vtuple(v):
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except ValueError:
        return (0,)


def installed_version(root):
    try:
        with open(os.path.join(root, "app", "version.py"), encoding="utf-8") as f:
            m = re.search(r'VERSION\s*=\s*"([0-9.]+)"', f.read())
            return m.group(1) if m else "1.0.0"
    except OSError:
        return "1.0.0"


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def read_manifest(p):
    out = {}
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if line:
                    d, rel = line.split("  ", 1)
                    out[rel.replace("\\", "/")] = d
    return out


def write_manifest(p, m):
    body = "".join("%s  %s\n" % (m[k], k.replace("/", "\\")) for k in sorted(m, key=str.lower))
    tmp = p + ".new"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    os.replace(tmp, p)


def app_running():
    for p in PORTS:
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % p, timeout=0.6) as r:
                if json.loads(r.read().decode("utf-8")).get("app") == APP_ID:
                    return True
        except Exception:
            continue
    return False


def wait_closed(seconds):
    t0 = time.time()
    while app_running():
        if time.time() - t0 > seconds:
            return False
        time.sleep(1)
    time.sleep(1.5)   # the process lets go of its files a moment after the port
    return True


def safe_rel(rel):
    rel = rel.replace("\\", "/")
    if rel.startswith("/") or ":" in rel or any(p in ("", ".", "..") for p in rel.split("/")):
        raise ValueError("bad path in update.json: %r" % rel)
    return rel


def restart(root, quiet):
    env = dict(os.environ)
    if quiet:
        env["HW_NO_BROWSER"] = "1"   # the window that asked for the update reloads by itself
    exe = os.path.join(root, "python", "pythonw.exe")
    subprocess.Popen([exe, "-X", "utf8", os.path.join(root, "app", "server.py")], cwd=root, env=env,
                     creationflags=0x00000008 | 0x00000200, close_fds=True)   # DETACHED, NEW_GROUP


def write_last(root, d):
    try:
        os.makedirs(os.path.join(root, "_updates"), exist_ok=True)
        d["log"] = LOG[-60:]
        with open(os.path.join(root, "_updates", "last.json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        with open(os.path.join(root, "_updates", "update-log.txt"), "a", encoding="utf-8") as f:
            f.write("\n".join(LOG) + "\n\n")
    except OSError:
        pass


def remember(root, kit):
    # The folder the app looks in for the next kits: the one holding this kit's folder
    # (Windows' "Extract All" adds one more level, "...-Update-Kit": skip that too).
    parent = os.path.dirname(os.path.abspath(kit).rstrip("\\/"))
    if re.search(r"-Update-Kit$", os.path.basename(parent), re.I):
        parent = os.path.dirname(parent)
    os.makedirs(os.path.join(root, "_updates"), exist_ok=True)
    with open(os.path.join(root, "_updates", "folder.txt"), "w", encoding="utf-8") as f:
        f.write(parent)
    say("updates folder remembered: %s" % parent)


def install(kit, root, args):
    with open(os.path.join(kit, "update.json"), encoding="utf-8") as f:
        u = json.load(f)
    if u.get("app") != APP_ID:
        raise ValueError("this is not a Hebrew Whisper update kit")
    new_v, base_v, old_v = u["version"], u.get("base", "1.0.0"), installed_version(root)
    say("installed %s, kit %s (built against %s)" % (old_v, new_v, base_v))
    if vtuple(old_v) >= vtuple(new_v) and not args.force:
        return "same", old_v, new_v
    if vtuple(old_v) < vtuple(base_v):
        raise ValueError("installed version %s is older than %s, which this kit needs. Install the "
                         "kit for %s first, or the full bundle." % (old_v, base_v, base_v))

    files = {safe_rel(k): v for k, v in u["files"].items()}
    remove = [safe_rel(r) for r in u.get("remove", [])]

    say("1/5 checking the kit (%d files)..." % len(files))
    for rel, digest in files.items():
        p = os.path.join(kit, "payload", rel)
        if not os.path.isfile(p) or sha256(p) != digest:
            raise ValueError("the kit is damaged: %s. Copy the kit folder again." % rel)

    say("2/5 checking this install matches %s..." % base_v)
    base = u.get("base_files") or {}
    bad = []
    for rel, digest in base.items():
        rel = safe_rel(rel)
        if rel in files or rel in remove or rel.startswith(SKIP_BASE_CHECK):
            continue
        p = os.path.join(root, rel)
        if not os.path.isfile(p) or sha256(p) != digest:
            bad.append(rel)
    if bad and not args.force:
        raise ValueError("this install is not a clean %s (%d files differ, e.g. %s). Install the full "
                         "bundle instead." % (base_v, len(bad), ", ".join(bad[:3])))

    say("3/5 waiting for Hebrew Whisper to close...")
    if not wait_closed(args.wait):
        raise RuntimeError("Hebrew Whisper is still open. Close its window and run the update again.")

    bdir = os.path.join(root, "_updates", "backup-%s-to-%s" % (old_v, new_v))
    if os.path.isdir(bdir):
        shutil.rmtree(bdir)
    os.makedirs(bdir)
    say("4/5 backing up %d files..." % (len(files) + len(remove)))
    added = []
    for rel in list(files) + remove + ["manifest.sha256"]:
        src = os.path.join(root, rel)
        if os.path.isfile(src):
            dst = os.path.join(bdir, "files", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        elif rel in files:
            added.append(rel)
    with open(os.path.join(bdir, "restore.json"), "w", encoding="utf-8") as f:
        json.dump({"from": old_v, "to": new_v, "added": added, "time": time.time()}, f, indent=1)

    say("5/5 installing...")
    try:
        for rel in files:
            dst = os.path.join(root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".hw-new"
            shutil.copyfile(os.path.join(kit, "payload", rel), tmp)
            os.replace(tmp, dst)
        for rel in remove:
            p = os.path.join(root, rel)
            if os.path.isfile(p):
                os.remove(p)
        for rel, digest in files.items():
            if sha256(os.path.join(root, rel)) != digest:
                raise RuntimeError("installed file does not match: %s" % rel)
        man = os.path.join(root, "manifest.sha256")
        m = read_manifest(man)
        for rel in remove:
            m.pop(rel, None)
        m.update(files)
        write_manifest(man, m)
        if installed_version(root) != new_v:
            raise RuntimeError("version after install is %s, not %s" % (installed_version(root), new_v))
    except Exception:
        say("install FAILED - putting %s back" % old_v)
        restore_from(root, bdir)
        raise
    say("installed %s (backup: %s)" % (new_v, bdir))
    return "ok", old_v, new_v


def restore_from(root, bdir):
    with open(os.path.join(bdir, "restore.json"), encoding="utf-8") as f:
        r = json.load(f)
    for rel in r.get("added", []):
        p = os.path.join(root, safe_rel(rel))
        if os.path.isfile(p):
            os.remove(p)
    fdir = os.path.join(bdir, "files")
    for dp, _, names in os.walk(fdir):
        for n in names:
            src = os.path.join(dp, n)
            rel = os.path.relpath(src, fdir)
            dst = os.path.join(root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".hw-old"
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
    return r


def restore(root, args):
    udir = os.path.join(root, "_updates")
    backs = [os.path.join(udir, d) for d in (os.listdir(udir) if os.path.isdir(udir) else [])
             if d.startswith("backup-") and os.path.isfile(os.path.join(udir, d, "restore.json"))]
    if not backs:
        raise ValueError("there is no backup to restore")
    bdir = max(backs, key=os.path.getmtime)
    if not wait_closed(args.wait):
        raise RuntimeError("Hebrew Whisper is still open. Close its window and run this again.")
    r = restore_from(root, bdir)
    shutil.rmtree(bdir, ignore_errors=True)
    say("restored %s (was %s)" % (r["from"], r["to"]))
    return "restored", r["to"], r["from"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit")
    ap.add_argument("--root", required=True)
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--restart", action="store_true")
    ap.add_argument("--quiet-restart", action="store_true")
    ap.add_argument("--remember", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--wait", type=int, default=5)
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    if not os.path.isfile(os.path.join(root, "python", "python.exe")):
        say("FAILED: %s is not a Hebrew Whisper folder (no python\\python.exe)" % root)
        box("This is not a Hebrew Whisper folder:\n%s" % root, True)
        return 1
    try:
        if args.restore:
            res, a, b = restore(root, args)
        else:
            kit = os.path.abspath(args.kit or os.path.dirname(os.path.abspath(__file__)))
            res, a, b = install(kit, root, args)
            if args.remember:
                remember(root, kit)
        if res == "same":
            say("already on %s - nothing to do" % a)
        write_last(root, {"ok": True, "result": res, "from": a, "to": b, "time": time.time()})
        code = 0
    except Exception as e:
        msg = str(e) or repr(e)
        say("FAILED: " + msg)
        write_last(root, {"ok": False, "error": msg, "time": time.time()})
        box("The update did not install. Nothing was changed.\n\n" + msg, True)
        code = 2
    if args.restart or args.quiet_restart:
        try:
            restart(root, args.quiet_restart)
        except Exception as e:
            say("could not start Hebrew Whisper again: %s" % e)
    return code


if __name__ == "__main__":
    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main())
