# Builds the offline Hebrew Whisper bundle and encodes it to text.
# Runs on blackberry (needs internet). Windows PowerShell 5.1. ASCII only.
#
#   build\HebrewWhisper\          the ready-to-run folder (python + libs + model + app)
#   build\HebrewWhisper-text\     the numbered .txt files + DECODE.bat to carry across

param(
  [string]$OutRoot = '',
  [int]$ChunkMB = 500,
  [switch]$SkipEncode
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repo = Split-Path -Parent $PSScriptRoot
if (-not $OutRoot) { $OutRoot = Join-Path $repo 'build' }

$PY_VER = '3.12.10'
$PY_URL = "https://www.python.org/ftp/python/$PY_VER/python-$PY_VER-embed-amd64.zip"
$GETPIP = 'https://bootstrap.pypa.io/get-pip.py'
$MODEL_REPO = 'ivrit-ai/whisper-large-v3-ct2'
$MODEL_REV = 'e9ed4a4a98d761b0f617d668303de2c514236c66'
$MODEL_FILES = @('config.json', 'model.bin', 'preprocessor_config.json', 'tokenizer.json', 'vocabulary.json')
$MODEL_BIN_SHA = '765965efd777190f76e8b337520056f00d68e48bb99b2f95d28670b2364a02ce'
$PIP_PKGS = @('faster-whisper==1.2.1', 'ctranslate2==4.7.1', 'av==16.1.0', 'nvidia-cublas-cu12==12.9.2.10', 'nvidia-cudnn-cu12==9.27.0.42')

$curl = Join-Path $env:SystemRoot 'System32\curl.exe'

function Step($m) { Write-Host ''; Write-Host "== $m" }
function Fail($m) { Write-Host ''; Write-Host "FAILED: $m"; exit 1 }

function Sha256File($p) {
  $s = [System.Security.Cryptography.SHA256]::Create()
  $f = [System.IO.File]::OpenRead($p)
  try { return ([BitConverter]::ToString($s.ComputeHash($f)) -replace '-', '').ToLower() }
  finally { $f.Dispose(); $s.Dispose() }
}

function Download($url, $dest) {
  $ErrorActionPreference = 'Continue'
  & $curl -L --fail --retry 5 --retry-delay 3 -C - -o $dest $url
  if ($LASTEXITCODE -ne 0) { Fail "download $url (curl exit $LASTEXITCODE)" }
}

if (-not (Test-Path -LiteralPath $curl)) { Fail 'curl.exe not found in System32 (needs Windows 10 1803+).' }

$bundle = Join-Path $OutRoot 'HebrewWhisper'
$cache = Join-Path $OutRoot 'cache'
New-Item -ItemType Directory -Force -Path $bundle, $cache | Out-Null

# ---- 1. Python (embeddable) -----------------------------------------------------------
Step "Python $PY_VER (embeddable)"
$pyDir = Join-Path $bundle 'python'
$pyExe = Join-Path $pyDir 'python.exe'
if (-not (Test-Path -LiteralPath $pyExe)) {
  $zip = Join-Path $cache "python-$PY_VER-embed-amd64.zip"
  if (-not (Test-Path -LiteralPath $zip)) { Download $PY_URL $zip }
  Expand-Archive -LiteralPath $zip -DestinationPath $pyDir -Force
  $pth = Get-ChildItem -LiteralPath $pyDir -Filter 'python3*._pth' | Select-Object -First 1
  $lines = Get-Content -LiteralPath $pth.FullName | ForEach-Object { if ($_ -eq '#import site') { 'import site' } else { $_ } }
  $lines = @($lines) + @('Lib\site-packages')
  [System.IO.File]::WriteAllLines($pth.FullName, $lines)
}

# ---- 2. pip + packages ----------------------------------------------------------------
Step 'pip + faster-whisper + CUDA 12 libs (about 1.5 GB)'
$env:PYTHONIOENCODING = 'utf-8'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
# native tools write warnings to stderr; under 'Stop' PS 5.1 would turn those into errors
$ErrorActionPreference = 'Continue'
if (-not (Test-Path -LiteralPath (Join-Path $pyDir 'Lib\site-packages\pip'))) {
  $gp = Join-Path $cache 'get-pip.py'
  # Never "resume" this one: it changes upstream, and a resumed download is a broken script.
  if (Test-Path -LiteralPath $gp) { Remove-Item -LiteralPath $gp -Force }
  Download $GETPIP $gp
  & $pyExe $gp --no-warn-script-location
  if ($LASTEXITCODE -ne 0) { Fail 'get-pip.py' }
}
& $pyExe -m pip install --no-warn-script-location --only-binary=:all: @PIP_PKGS
if ($LASTEXITCODE -ne 0) { Fail 'pip install' }
& $pyExe -c 'import faster_whisper, ctranslate2, av; print(faster_whisper.__version__, ctranslate2.__version__, av.__version__)'
if ($LASTEXITCODE -ne 0) { Fail 'import test' }
# pip is not needed on the far side; drop its caches to keep the bundle small
Get-ChildItem -LiteralPath $pyDir -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
# ctranslate2 / onnxruntime need the MSVC C++ runtime; the offline PC may not have it installed.
$sys32 = Join-Path $env:SystemRoot 'System32'
foreach ($dll in @('msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'concrt140.dll')) {
  $src = Join-Path $sys32 $dll
  if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination $pyDir -Force }
  else { Write-Host "  WARNING: $dll not found in System32 (install the VC++ 2015-2022 x64 runtime on this PC and run again)" }
}
$ErrorActionPreference = 'Stop'

# ---- 3. model -------------------------------------------------------------------------
Step "Model $MODEL_REPO (about 3.1 GB)"
$modelDir = Join-Path $bundle 'model'
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
foreach ($name in $MODEL_FILES) {
  $dest = Join-Path $modelDir $name
  if ($name -eq 'model.bin' -and (Test-Path -LiteralPath $dest) -and ((Sha256File $dest) -eq $MODEL_BIN_SHA)) { continue }
  # the small files are pinned to one revision: one that is there is complete (curl -C - on a
  # finished file is an error, so do not ask again)
  if ($name -ne 'model.bin' -and (Test-Path -LiteralPath $dest) -and (Get-Item -LiteralPath $dest).Length -gt 0) { continue }
  Download "https://huggingface.co/$MODEL_REPO/resolve/$MODEL_REV/$name" $dest
}
Write-Host '  verifying model.bin SHA-256...'
if ((Sha256File (Join-Path $modelDir 'model.bin')) -ne $MODEL_BIN_SHA) {
  Remove-Item -LiteralPath (Join-Path $modelDir 'model.bin') -Force
  Fail 'model.bin hash mismatch (deleted; run again)'
}

# ---- 4. app ---------------------------------------------------------------------------
Step 'App files'
$appDir = Join-Path $bundle 'app'
# From scratch: a file left from an older build (or a __pycache__ from a test run) must not ship.
if (Test-Path -LiteralPath $appDir) { Remove-Item -LiteralPath $appDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $appDir | Out-Null
foreach ($n in @('transcribe.py', 'server.py', 'ai.py', 'ai_prompts.py', 'ai_post.py', 'projects.py', 'appbase.py', 'window.py',
                 'version.py', 'updates.py', 'apply_update.py', 'ui.html', 'ui.css', 'ui.js', 'icon.ico')) {
  Copy-Item -LiteralPath (Join-Path $repo "app\$n") -Destination $appDir -Force
}
Copy-Item -LiteralPath (Join-Path $repo 'tests\sample-he.mp3') -Destination $appDir -Force
foreach ($n in @('HEBREW-WHISPER.bat', 'TRANSCRIBE.bat', 'SELFTEST.bat', 'HOW-TO-HE.txt')) {
  Copy-Item -LiteralPath (Join-Path $repo "app\$n") -Destination $bundle -Force
}

# ---- 5. manifest ----------------------------------------------------------------------
Step 'manifest.sha256'
Get-ChildItem -LiteralPath $bundle -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
# (-Include does not filter together with -LiteralPath in PS 5.1: filter by name instead)
Get-ChildItem -LiteralPath $bundle -Recurse -File | Where-Object { $_.Name -like '*.hw-new' -or $_.Name -like '*.hw-old' } | Remove-Item -Force
$man = Join-Path $bundle 'manifest.sha256'
if (Test-Path -LiteralPath $man) { Remove-Item -LiteralPath $man -Force }
$root = (Get-Item -LiteralPath $bundle).FullName.TrimEnd('\') + '\'
$sb = New-Object System.Text.StringBuilder
Get-ChildItem -LiteralPath $bundle -Recurse -File | Sort-Object FullName | ForEach-Object {
  $rel = $_.FullName.Substring($root.Length)
  [void]$sb.Append((Sha256File $_.FullName) + '  ' + $rel + [char]10)
}
[System.IO.File]::WriteAllText($man, $sb.ToString(), (New-Object System.Text.UTF8Encoding($false)))
$size = (Get-ChildItem -LiteralPath $bundle -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ('  bundle size {0:N1} GB' -f ($size / 1GB))
# This version's file list: what a later update kit is compared against (build-update-kit.ps1).
$verText = [System.IO.File]::ReadAllText((Join-Path $repo 'app\version.py'))
if ($verText -match 'VERSION\s*=\s*"([0-9.]+)"') {
  $relDir = Join-Path $OutRoot 'releases'
  New-Item -ItemType Directory -Force -Path $relDir | Out-Null
  Copy-Item -LiteralPath $man -Destination (Join-Path $relDir ($Matches[1] + '.manifest.sha256')) -Force
  Write-Host ('  version {0} (file list kept in {1})' -f $Matches[1], $relDir)
}

# ---- 6. encode to text ----------------------------------------------------------------
if ($SkipEncode) { Write-Host ''; Write-Host "DONE (not encoded): $bundle"; exit 0 }
# One zip, so the stick carries ~11 .txt files instead of one per Python file (3000+).
Step 'Zip the bundle'
$zipDir = Join-Path $OutRoot 'zip'
New-Item -ItemType Directory -Force -Path $zipDir | Out-Null
$zipPath = Join-Path $zipDir 'HebrewWhisper.zip'
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($bundle, $zipPath, [System.IO.Compression.CompressionLevel]::Fastest, $true)
Write-Host ('  zip {0:N1} GB' -f ((Get-Item -LiteralPath $zipPath).Length / 1GB))

Step "Encode to text ($ChunkMB MB per .txt)"
$ErrorActionPreference = 'Continue'
$textDir = Join-Path $OutRoot 'HebrewWhisper-text'
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo 'tools\text-transfer\scripts\TextTransfer-Encode.ps1') -Source $zipPath -OutDir $textDir -ChunkMB $ChunkMB
if ($LASTEXITCODE -ne 0) { Fail 'encode' }
Copy-Item -LiteralPath (Join-Path $repo 'app\START-HERE-HE.txt') -Destination $textDir -Force

Write-Host ''
Write-Host 'DONE. Copy EVERY file in this folder to the stick:'
Write-Host "  $textDir"
exit 0
