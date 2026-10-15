# Hebrew Whisper (offline)

Hebrew speech-to-text for the offline A5000 PC. Model: `ivrit-ai/whisper-large-v3-ct2`
(Whisper large-v3 fine-tuned on Hebrew) on faster-whisper / CTranslate2, CUDA float16,
CPU int8 fallback. Fully self-contained: embeddable Python 3.12 + CUDA 12 libs (pip wheels) + model.

- blackberry: `git pull`, double-click `PREPARE-ON-BLACKBERRY.bat` (~5 GB download, ~15 GB free disk)
  -> copy all of `build\HebrewWhisper-text\` (~5.5 GB, 13 .txt) to the stick.
- Offline PC (START-HERE-HE.txt): `DECODE.bat` (~25 min) -> extract `decoded\HebrewWhisper.zip` to `C:\` -> `C:\HebrewWhisper\SELFTEST.bat`
  -> drag audio/video onto `TRANSCRIBE.bat` -> `<name>.txt` + `<name>.srt` next to it.
