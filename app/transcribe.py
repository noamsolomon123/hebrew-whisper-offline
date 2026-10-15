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
import re
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

# GPU: batched decoding (VAD cuts the speech into <=30 s pieces, BATCH of them run at once).
# 2-3x faster than one-by-one on the same text. HW_BATCH=0 forces the old one-by-one mode.
BATCH = int(os.environ.get("HW_BATCH", "8") or 0)
BEAM = 5
SR = 16000
VAD = {"min_silence_duration_ms": 160}   # batched mode (tested best); one-by-one keeps defaults


def get_model(device):
    if device not in _models:
        compute = "float16" if device == "cuda" else "int8"
        threads = 0 if device == "cuda" else max(4, (os.cpu_count() or 8) - 2)
        _models[device] = WhisperModel(MODEL_DIR, device=device, compute_type=compute,
                                       cpu_threads=threads, local_files_only=True)
    return _models[device]


state = {"device": None, "words": None, "batch": BATCH}


def pick_device():
    import ctranslate2
    try:
        n = ctranslate2.get_cuda_device_count()
    except Exception:
        n = 0
    return "cuda" if n > 0 else "cpu"


def load_audio(path):
    # Decode once (PyAV, bundled ffmpeg libs) -> 16 kHz mono float32. Clear error if broken.
    from faster_whisper.audio import decode_audio
    if not os.path.isfile(path):
        raise FileNotFoundError("File not found: %s" % path)
    if os.path.getsize(path) == 0:
        raise ValueError("The file is empty (0 bytes): %s" % os.path.basename(path))
    try:
        audio = decode_audio(path, sampling_rate=SR)
    except Exception as e:
        raise ValueError("Cannot read audio from %s - the file is damaged or not an audio/video "
                         "file (%s)" % (os.path.basename(path), str(e).splitlines()[0][:150] if str(e)
                                         else type(e).__name__))
    return audio


def _opts(prompt, hotwords, words):
    return dict(language="he", task="transcribe", beam_size=BEAM, vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt=prompt or None, hotwords=hotwords or None,
                word_timestamps=bool(words), no_speech_threshold=0.6, log_prob_threshold=-1.0,
                compression_ratio_threshold=2.4)


def run(path, device, on_progress=None, audio=None, prompt=None, hotwords=None, words=False,
        batch=None):
    if audio is None:
        audio = load_audio(path)
    duration = len(audio) / float(SR)
    if duration < 0.1:
        return [], duration
    model = get_model(device)
    kw = _opts(prompt, hotwords, words)
    batch = state["batch"] if batch is None else batch
    if device == "cuda" and batch and batch > 1:
        from faster_whisper import BatchedInferencePipeline
        segments, info = BatchedInferencePipeline(model).transcribe(
            audio, batch_size=batch, without_timestamps=False, vad_parameters=dict(VAD), **kw)
    else:
        segments, info = model.transcribe(audio, **kw)
    out, raw = [], []
    for s in segments:
        raw.append(s)
        t = s.text.strip()
        if t:
            out.append((s.start, s.end, t))
        pct = min(100.0, 100.0 * s.end / duration) if duration else 0
        if on_progress:
            on_progress(pct, out)
        print("\r  %5.1f%%  (%s / %s)" % (pct, ts(s.end, "."), ts(duration, ".")), end="", flush=True)
    print()
    segs = clean(raw)
    state["words"] = ([(float(w.start), float(w.end), w.word.strip()) for s in raw if keep_raw(s)
                       for w in (s.words or [])] if words else None)
    return segs, duration


def transcribe(path, on_progress=None, prompt=None, hotwords=None, words=False):
    """-> (segments [(start, end, text)], duration). prompt: earlier text / style hint;
    hotwords: names and terms to prefer (e.g. "Avi Cohen, Rafael, Iron Dome");
    words=True also fills state["words"] = [(start, end, word), ...] for the whole file."""
    if state["device"] is None:
        state["device"] = pick_device()
    elif state.get("cpu_reason") == "memory":
        # The last job ran out of GPU memory (e.g. while gemma was loaded): try the GPU again.
        state["device"], state["cpu_reason"] = "cuda", None
        _models.pop("cpu", None)
    audio = load_audio(path)
    kw = dict(audio=audio, prompt=prompt, hotwords=hotwords, words=words)
    try:
        return run(path, state["device"], on_progress, **kw)
    except Exception as e:
        msg = str(e).lower()
        gpu_words = ("cuda", "cublas", "cudnn", "gpu", "device", "memory", "dll", "driver")
        if state["device"] != "cuda" or not any(w in msg for w in gpu_words):
            raise
        print()
        print("  GPU failed (%s)" % str(e).splitlines()[0][:200])
        if "memory" in msg and state["batch"] and state["batch"] > 1:
            # Out of GPU memory in batched mode: retry smaller batches, then one-by-one.
            b = state["batch"]
            while b > 1:
                b = b // 2 if b > 2 else 0
                print("  Retrying on GPU with batch %d" % b)
                try:
                    r = run(path, "cuda", on_progress, batch=b, **kw)
                    state["batch"] = b
                    return r
                except Exception as e2:
                    if "memory" not in str(e2).lower():
                        break
        print("  Switching to CPU - slower, same text.")
        state["device"] = "cpu"
        state["cpu_reason"] = "memory" if "memory" in msg else "error"
        return run(path, "cpu", on_progress, **kw)


def ts(sec, sep=","):
    sec = max(0.0, sec or 0.0)
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d%s%03d" % (h, m, s, sep, ms)


# ---- clean-up: Whisper "hallucinations" on silence / music / noise -------------------------
# Subtitle credits learned from TV subtitles, and short thank-yous with weak confidence.
_CREDITS = re.compile(r"(כתוביות|תורגם|תרגום|תרגם|סונכרן|סנכרון|הופק|subtitles)", re.I)
_URL = re.compile(r"(amara\.org|www\.|\.co\.il|\.com)", re.I)
_THANKS = {"תודה", "תודה רבה", "תודה רבה לכם", "תודה לכם", "תודה שצפיתם", "תודה על הצפייה",
           "תודה רבה על הצפייה", "תודה שהאזנתם", "שבוע טוב", "ביי", "להתראות", "אמן"}


def _bare(t):
    return re.sub(r"[^\w\s]", "", t).strip()


def keep_raw(s):
    t = s.text.strip()
    if not t:
        return False
    weak = s.no_speech_prob > 0.45 or s.avg_logprob < -0.9
    if _URL.search(t) and len(t) < 120:
        return False
    if _CREDITS.search(t) and (weak or (":" in t and len(t.split()) <= 8)):
        return False   # "kituviyot: ..." credit line; a real sentence about translation stays
    if _bare(t) in _THANKS and (weak or (s.end - s.start) > 6):
        return False
    if s.no_speech_prob > 0.8 and s.avg_logprob < -0.7:
        return False   # the model itself thinks this is not speech
    return True


def _unloop(t):
    # Repetition loop: a word 4+ times in a row -> 3 ("lo lo lo" is real speech);
    # a 2-6 word phrase 3+ times in a row -> 2.
    w = t.split()
    for n in range(1, 7):
        r = 4 if n == 1 else 3
        out = []
        for x in w:
            out.append(x)
            k = len(out)
            if k >= r * n and all(out[k - n:] == out[k - (j + 1) * n:k - j * n] for j in range(1, r)):
                del out[k - n:]
        w = out
    return " ".join(w)


MERGE_SEC = 1.0   # a fragment shorter than this is glued to its neighbour (same sentence)


def clean(raw):
    segs = []
    for s in raw:
        if not keep_raw(s):
            continue
        t = _unloop(s.text.strip())
        if segs and t == segs[-1][2] and s.start - segs[-1][1] < 2:
            continue   # the same line twice in a row
        a, z = s.start, s.end
        if segs:
            pa, pz, pt = segs[-1]
            gap = a - pz
            short = (z - a) < MERGE_SEC or len(t.split()) <= 1
            if gap < 0.4 and short and pt[-1:] not in ".?!" and len(pt) < 300:
                segs[-1] = (pa, z, pt + " " + t)
                continue
        segs.append((a, z, t))
    return [(float(a), float(z), t) for a, z, t in segs]


PARA_GAP_SEC = 1.6     # a pause this long starts a new paragraph
PARA_SOFT_GAP = 0.9    # ...a shorter pause after a full sentence, once the paragraph is long
PARA_SOFT_CHARS = 300
PARA_MAX_CHARS = 700   # ...and so does a long run of speech, at the end of a sentence
PARA_HARD_CHARS = 1400  # never longer than this, sentence end or not


def paragraphs(segs):
    out, cur, last_end = [], [], None
    for seg in segs:
        a, z, t = seg[0], seg[1], seg[2]
        t = t.strip()
        if not t:
            continue
        if cur:
            size = sum(len(x) + 1 for x in cur)
            gap = a - last_end
            end = cur[-1][-1:] in ".?!"
            if (gap >= PARA_GAP_SEC or (end and size >= PARA_MAX_CHARS) or
                    (end and gap >= PARA_SOFT_GAP and size >= PARA_SOFT_CHARS) or
                    size >= PARA_HARD_CHARS):
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
    blocks = [("title", title)] if title else []
    blocks += [("p", p) for p in text.replace("\r\n", "\n").split("\n")]
    return docx_from_blocks(blocks)


_STYLE = {  # kind -> (size in half-points, bold, space after, colour, indent, prefix)
    "title": (34, True, 200, "1F3A68", 0, ""),
    "h": (27, True, 100, "2F5597", 0, ""),
    "h2": (24, True, 60, "404040", 0, ""),
    "p": (24, False, 160, None, 0, ""),
    "li": (24, False, 60, None, 360, "•  "),
    "task": (24, False, 60, None, 360, "☐  "),
}


def docx_from_blocks(blocks):
    # Minimal Word document, right-to-left Hebrew. No python-docx needed.
    import io
    import zipfile
    paras = []
    for kind, text in blocks:
        size, bold, after, color, ind, prefix = _STYLE.get(kind, _STYLE["p"])
        before = 280 if kind == "h" else 0
        rpr = ('<w:rPr>%s<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/>%s<w:rtl/>'
               '<w:sz w:val="%d"/><w:szCs w:val="%d"/><w:lang w:bidi="he-IL"/></w:rPr>'
               % ("<w:b/><w:bCs/>" if bold else "", '<w:color w:val="%s"/>' % color if color else "",
                  size, size))
        ppr = ('<w:pPr><w:bidi/><w:spacing w:before="%d" w:after="%d" w:line="%d" w:lineRule="auto"/>%s</w:pPr>'
               % (before, after, 300 if kind in ("li", "task") else 360,
                  '<w:ind w:start="%d"/>' % ind if ind else ""))
        paras.append('<w:p>%s<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r></w:p>'
                     % (ppr, rpr, _xml(prefix + text)))
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
    base = os.path.splitext(os.path.abspath(path))[0]
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


def nvidia_driver():
    import subprocess
    exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
    try:
        out = subprocess.run([exe, "--query-gpu=name,driver_version", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
        return out.splitlines()[0] if out else "unknown"
    except Exception:
        return "unknown (no NVIDIA driver found)"


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
    print("  NVIDIA driver   %s  (needs 528 or newer for the GPU)" % nvidia_driver())
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
