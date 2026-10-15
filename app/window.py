# Shows the page as its own app window (Edge/Chrome "--app" mode: no tabs, no address bar,
# own taskbar icon) and puts a shortcut on the desktop. Both are on every Windows 10/11 PC,
# so nothing new has to be installed. Falls back to the default browser.

import os
import subprocess
import webbrowser

APP_NAME = "תמלול עברית"


def _browser():
    pf = [os.environ.get(k, "") for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for base in pf:
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            p = os.path.join(base, rel)
            if base and os.path.isfile(p):
                return p
    return None


def open_window(url):
    """Returns the browser process when an app window was opened, else None."""
    exe = _browser()
    if not exe:
        webbrowser.open(url)
        return None
    profile = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "HebrewWhisper", "window")
    os.makedirs(profile, exist_ok=True)
    args = [exe, "--app=" + url, "--user-data-dir=" + profile, "--window-size=1320,860",
            "--no-first-run", "--no-default-browser-check", "--disable-features=Translate",
            # keep the page's 1-second poll alive while the window is minimized
            "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows"]
    try:
        return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        webbrowser.open(url)
        return None


def ensure_shortcut(root):
    """Desktop shortcut to the app, with its icon. Best effort, created once."""
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(desktop):
        return
    lnk = os.path.join(desktop, APP_NAME + ".lnk")
    if os.path.exists(lnk):
        return
    # Paths travel through env vars: the user name may be Hebrew.
    env = dict(os.environ, HW_LNK=lnk,
               HW_TARGET=os.path.join(root, "python", "pythonw.exe"),
               HW_ARGS='-X utf8 "%s"' % os.path.join(root, "app", "server.py"),
               HW_ICON=os.path.join(root, "app", "icon.ico"), HW_DIR=root)
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:HW_LNK);"
          "$s.TargetPath=$env:HW_TARGET;$s.Arguments=$env:HW_ARGS;$s.IconLocation=$env:HW_ICON;"
          "$s.WorkingDirectory=$env:HW_DIR;$s.Save()")
    try:
        subprocess.run([os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                     r"System32\WindowsPowerShell\v1.0\powershell.exe"),
                        "-NoProfile", "-NonInteractive", "-Command", ps],
                       env=env, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass
