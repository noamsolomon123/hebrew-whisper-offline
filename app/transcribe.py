# Hebrew Whisper (offline) - transcribe audio/video files to Hebrew text.
#
#   python transcribe.py <file-or-folder> [...]      -> writes <name>.txt and <name>.docx
#   python transcribe.py --selftest                  -> checks the bundle, prints OK / FAIL
#
# Model: ivrit-ai/whisper-large-v3-ct2 (Whisper large-v3 fine-tuned for Hebrew), run by
# faster-whisper / CTranslate2. GPU (CUDA, float16) first, CPU (int8) if the GPU fails.
# Nothing here touches the network.

import glob
import hashlib
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODEL_DIR = os.path.join(ROOT, "model")
SAMPLE = os.path.join(HERE, "sample-he.mp3")
MEDIA_EXT = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".amr",
    ".mp4", ".mov", ".mkv", ".avi", ".mxf", ".webm", ".m4v", ".wmv", ".mts", ".ts",
}

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def add_cuda_dlls():
    # cuBLAS / cuDNN come from the nvidia-* wheels inside the bundle, not from a system CUDA.
    site = os.path.join(ROOT, "python", "Lib", "site-packages")
    dirs = glob.glob(os.path.join(site, "nvidia", "*", "bin"))
    for d in dirs:
        os.add_dll_directory(d)
    os.environ["PATH"] = os.pathsep.join(dirs + [os.environ.get("PATH", "")])


add_cuda_dlls()

from faster_whisper import WhisperModel  # noqa: E402

_models = {}


def get_model(device):
    if device not in _models:
        compute = "float16" if device == "cuda" else "int8"
        threads = 0 if device == "cuda" else max(4, (os.cpu_count() or 8) - 2)
        _models[device] = WhisperModel(MODEL_DIR, device=device, compute_type=compute,
                                       cpu_threads=threads, local_files_only=True)
    return _models[device]


state = {"device": None}


def pick_device():
    import ctranslate2
    try:
        n = ctranslate2.get_cuda_device_count()
    except Exception:
        n = 0
    return "cuda" if n > 0 else "cpu"


def run(path, device, on_progress=None):
    model = get_model(device)
    segments, info = model.transcribe(path, language="he", task="transcribe", beam_size=5,
                                      vad_filter=True, condition_on_previous_text=False)
    out = []
    for s in segments:
        out.append((s.start, s.end, s.text.strip()))
        pct = 100.0 * s.end / info.duration if info.duration else 0
        if on_progress:
            on_progress(min(pct, 100.0), out)
        print("\r  %5.1f%%  (%s / %s)" % (min(pct, 100), ts(s.end, "."), ts(info.duration, ".")),
              end="", flush=True)
    print()
    return out, info.duration


def transcribe(path, on_progress=None):
    if state["device"] is None:
        state["device"] = pick_device()
    try:
        return run(path, state["device"], on_progress)
    except Exception as e:
        gpu_words = ("cuda", "cublas", "cudnn", "gpu", "device", "memory", "dll", "driver")
        if state["device"] != "cuda" or not any(w in str(e).lower() for w in gpu_words):
            raise
        print()
        print("  GPU failed (%s)" % str(e).splitlines()[0][:200])
        print("  Switching to CPU - slower, same text.")
        state["device"] = "cpu"
        return run(path, "cpu", on_progress)


def ts(sec, sep=","):
    sec = max(0.0, sec or 0.0)
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d%s%03d" % (h, m, s, sep, ms)


PARA_GAP_SEC = 1.6     # a pause this long starts a new paragraph
PARA_MAX_CHARS = 700   # ...and so does a long run of speech, at the end of a sentence


def paragraphs(segs):
    out, cur, last_end = [], [], None
    for a, z, t in segs:
        t = t.strip()
        if not t:
            continue
        size = sum(len(x) + 1 for x in cur)
        if cur and ((a - last_end) >= PARA_GAP_SEC or
                    (size >= PARA_MAX_CHARS and cur[-1][-1:] in ".?!")):
            out.append(" ".join(cur))
            cur = []
        cur.append(t)
        last_end = z
    if cur:
        out.append(" ".join(cur))
    return out


def plain_text(segs):
    return "\n\n".join(paragraphs(segs))


def _xml(s):
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "".join(c for c in s if c in "\t\n" or ord(c) >= 32)


def docx_bytes(text, title=""):
    # Minimal Word document, right-to-left Hebrew paragraphs. No python-docx needed.
    import io
    import zipfile
    rpr = ('<w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:rtl/>'
           '<w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:bidi="he-IL"/></w:rPr>')
    paras = []
    if title:
        paras.append('<w:p><w:pPr><w:bidi/><w:spacing w:after="240"/></w:pPr><w:r>'
                     '<w:rPr><w:b/><w:bCs/><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:rtl/>'
                     '<w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr><w:t xml:space="preserve">%s</w:t></w:r></w:p>'
                     % _xml(title))
    for p in text.replace("\r\n", "\n").split("\n"):
        paras.append('<w:p><w:pPr><w:bidi/><w:spacing w:after="160" w:line="360" w:lineRule="auto"/></w:pPr>'
                     '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r></w:p>' % (rpr, _xml(p)))
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           + "".join(paras) +
           '<w:sectPr><w:bidi/><w:pgSz w:w="11906" w:h="16838"/>'
           '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>')
    types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/word/document.xml" ContentType="application/'
             'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def write_outputs(path, segs):
    base = os.path.splitext(path)[0]
    targets = [base]
    fallback = os.path.join(os.path.expanduser("~"), "Documents", "Hebrew-Whisper-Output",
                            os.path.basename(base))
    targets.append(fallback)
    text = plain_text(segs)
    for b in targets:
        try:
            os.makedirs(os.path.dirname(b), exist_ok=True)
            with open(b + ".txt", "w", encoding="utf-8-sig") as f:
                f.write(text + "\n")
            with open(b + ".docx", "wb") as f:
                f.write(docx_bytes(text, os.path.basename(b)))
            return b
        except OSError:
            continue
    raise OSError("could not write output next to the file or in Documents")


def collect(args):
    files = []
    for a in args:
        a = a.strip().strip('"')
        if os.path.isdir(a):
            for dp, _, names in os.walk(a):
                for n in sorted(names):
                    if os.path.splitext(n)[1].lower() in MEDIA_EXT:
                        files.append(os.path.join(dp, n))
        elif os.path.isfile(a):
            files.append(a)
        else:
            print("  Not found: %s" % a)
    return files


def main(args):
    files = collect(args)
    if not files:
        print("  No audio/video files to transcribe.")
        return 1
    failed = 0
    for i, f in enumerate(files, 1):
        print("[%d/%d] %s" % (i, len(files), f))
        t0 = time.time()
        try:
            segs, dur = transcribe(f)
            b = write_outputs(f, segs)
            dt = time.time() - t0
            print("  Done in %.0fs (%s, audio %.0fs) -> %s.txt / .docx" % (dt, state["device"], dur or 0, b))
        except Exception as e:
            failed += 1
            print("  FAILED: %s" % str(e).splitlines()[0][:300] if str(e) else "  FAILED: %r" % e)
    print()
    print("  %d done, %d failed." % (len(files) - failed, failed))
    return 0 if failed == 0 else 2


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def selftest():
    import ctranslate2
    import faster_whisper
    ok = True
    print("Hebrew Whisper self-test")
    print("  python          %s" % sys.version.split()[0])
    print("  faster-whisper  %s" % faster_whisper.__version__)
    print("  ctranslate2     %s" % ctranslate2.__version__)
    man = os.path.join(ROOT, "manifest.sha256")
    bad = 0
    total = 0
    if os.path.isfile(man):
        print("  checking files (about a minute)...")
        with open(man, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if not line:
                    continue
                digest, rel = line.split("  ", 1)
                total += 1
                p = os.path.join(ROOT, rel)
                if not os.path.isfile(p) or sha256(p) != digest:
                    bad += 1
                    if bad <= 5:
                        print("  BAD FILE: %s" % rel)
        print("  files           %d checked, %d bad" % (total, bad))
        ok = ok and bad == 0
    else:
        print("  manifest.sha256 missing")
        ok = False
    try:
        n = ctranslate2.get_cuda_device_count()
    except Exception:
        n = 0
    print("  CUDA devices    %d" % n)
    t0 = time.time()
    try:
        segs, _ = transcribe(SAMPLE)
        text = " ".join(t for _, _, t in segs)
    except Exception as e:
        text = ""
        print("  transcribe ERROR: %s" % str(e).splitlines()[0][:300])
    print("  device used     %s  (%.1fs)" % (state["device"], time.time() - t0))
    print("  text: %s" % text)
    hit = all(w in text for w in ("בדיקה", "בעברית"))
    print("  sample check    %s" % ("OK" if hit else "WRONG TEXT"))
    ok = ok and hit
    print()
    print("RESULT: %s  (%s)" % ("OK" if ok else "FAIL", "GPU" if state["device"] == "cuda" else "CPU only"))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    a = sys.argv[1:]
    sys.exit(selftest() if a[:1] == ["--selftest"] else main(a))
