# Hebrew Whisper (offline)

Hebrew speech-to-text for the offline A5000 PC. Model: `ivrit-ai/whisper-large-v3-ct2`
(Whisper large-v3 fine-tuned on Hebrew) on faster-whisper / CTranslate2, CUDA float16,
CPU int8 fallback. Fully self-contained: embeddable Python 3.12 + CUDA 12 libs (pip wheels) + model.
Version: `app/version.py`.

## Full install (first time, or when an update kit says so)
- blackberry: `git pull`, double-click `PREPARE-ON-BLACKBERRY.bat` (~5 GB download, ~15 GB free disk)
  -> copy all of `build\HebrewWhisper-text\` (~5.5 GB, 13 .txt) to the stick.
- Offline PC (START-HERE-HE.txt): `DECODE.bat` (~25 min) -> extract `decoded\HebrewWhisper.zip` to `C:\` -> `C:\HebrewWhisper\SELFTEST.bat`
  -> drag audio/video onto `TRANSCRIBE.bat` -> `<name>.txt` + `<name>.docx` next to it.

## Updates (like AutoPoint)
- Release: raise `VERSION` in `app/version.py`, write `releases/<version>.notes-he.txt` (one line per change), push.
- blackberry: `git pull`, double-click `MAKE-UPDATE-KIT.bat` -> copy all of `build\kit-<version>-text\` to the stick.
  Only the files that changed since the base are carried (the base = the newest version built on
  this PC before; its file list is in `build\releases\`). The script decodes its own text files to check them.
- Offline PC (HOW-TO-UPDATE-HE.txt): `DECODE.bat` -> extract the kit zip into the updates folder ->
  in the app: **עדכונים -> עדכון והפעלה מחדש** (open work is autosaved and comes back).
  An install without the button (before 1.1.0): `UPDATE-HEBREW-WHISPER.bat` from the kit, once.
- `RESTORE-HEBREW-WHISPER.bat` (in every kit) puts the previous version back from `C:\HebrewWhisper\_updates\`.
- The installer (`app/apply_update.py`, also inside each kit) checks every file's SHA-256, refuses an
  install that is not the kit's base, backs up what it replaces, rolls back on any error, and keeps
  `manifest.sha256` right so SELFTEST still passes.
