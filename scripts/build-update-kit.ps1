# Builds an UPDATE KIT for the offline PC: only the files that changed since the version
# installed there, as numbered .txt files for the text-only transfer device.
# Runs on blackberry (internet). Windows PowerShell 5.1. ASCII only.
#
#   MAKE-UPDATE-KIT.bat                       (= this script, base = the newest older release)
#   powershell -File build-update-kit.ps1 -Base 1.1.0 [-SkipBundle] [-ChunkMB 500]
#
# How it knows what changed: every full bundle and every kit leaves its file list
# (manifest.sha256) in build\releases\<version>.manifest.sha256 (and releases\ in the repo).
# The kit carries every file whose SHA-256 differs from the base's, plus the whole app\ folder,
# and lists the files to delete. The base's file list rides along, so the installer can refuse
# an install that is not that base (it would leave old and new files mixed).
#
#   build\kit-<v>\HebrewWhisper-<v>-Update-Kit.zip     the kit (unzip into the updates folder)
#   build\kit-<v>-text\                                 the .txt files + DECODE.bat to carry across

param(
  [string]$Base = '',
  [switch]$SkipBundle,
  [int]$ChunkMB = 500
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $repo 'build'

function Step($m) { Write-Host ''; Write-Host "== $m" }
function Fail($m) { Write-Host ''; Write-Host "FAILED: $m"; exit 1 }
function VKey($v) { ($v.Split('.') | ForEach-Object { '{0:D5}' -f [int]$_ }) -join '.' }
function Sha256File($p) {
  $s = [System.Security.Cryptography.SHA256]::Create()
  $f = [System.IO.File]::OpenRead($p)
  try { return ([BitConverter]::ToString($s.ComputeHash($f)) -replace '-', '').ToLower() }
  finally { $f.Dispose(); $s.Dispose() }
}
function ReadManifest($p) {
  $m = @{}
  foreach ($line in [System.IO.File]::ReadAllLines($p)) {
    if ($line.Length -lt 67) { continue }
    $m[$line.Substring(66).Replace('\', '/')] = $line.Substring(0, 64)
  }
  return $m
}
function JStr($s) {
  $sb = New-Object System.Text.StringBuilder
  [void]$sb.Append('"')
  foreach ($c in $s.ToCharArray()) {
    $n = [int]$c
    if ($c -eq '"') { [void]$sb.Append('\"') }
    elseif ($c -eq '\') { [void]$sb.Append('\\') }
    elseif ($n -lt 32 -or $n -gt 126) { [void]$sb.Append(('\u{0:x4}' -f $n)) }
    else { [void]$sb.Append($c) }
  }
  [void]$sb.Append('"')
  return $sb.ToString()
}
function JMap($h) {
  $parts = foreach ($k in ($h.Keys | Sort-Object)) { (JStr $k) + ': ' + (JStr $h[$k]) }
  return '{' + ($parts -join ', ') + '}'
}

# ---- versions -------------------------------------------------------------------------
$verText = [System.IO.File]::ReadAllText((Join-Path $repo 'app\version.py'))
if ($verText -notmatch 'VERSION\s*=\s*"([0-9.]+)"') { Fail 'no VERSION in app\version.py' }
$ver = $Matches[1]

$relDirs = @((Join-Path $buildDir 'releases'), (Join-Path $repo 'releases'))
if (-not $Base) {
  $cands = foreach ($d in $relDirs) {
    if (Test-Path -LiteralPath $d) {
      Get-ChildItem -LiteralPath $d -Filter '*.manifest.sha256' | ForEach-Object { $_.Name -replace '\.manifest\.sha256$', '' }
    }
  }
  $older = @($cands | Where-Object { (VKey $_) -lt (VKey $ver) } | Sort-Object { VKey $_ } -Unique)
  if ($older.Count -eq 0) { Fail "no release older than $ver in build\releases or releases\ (pass -Base)" }
  $Base = $older[-1]
}
if ((VKey $Base) -ge (VKey $ver)) { Fail "app\version.py says $ver, not newer than the base $Base. Raise VERSION first." }
$baseMan = $null
foreach ($d in $relDirs) { $p = Join-Path $d "$Base.manifest.sha256"; if (-not $baseMan -and (Test-Path -LiteralPath $p)) { $baseMan = $p } }
if (-not $baseMan) { Fail "the file list of $Base is missing ($Base.manifest.sha256 in build\releases or releases\)" }
Write-Host "Kit: $Base -> $ver   (base list: $baseMan)"

# ---- the full bundle of this version --------------------------------------------------
if (-not $SkipBundle) {
  Step 'Bundle of this version (prepare.ps1, downloads only what is missing)'
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'prepare.ps1') -SkipEncode
  if ($LASTEXITCODE -ne 0) { Fail 'prepare.ps1' }
}
$bundle = Join-Path $buildDir 'HebrewWhisper'
$newMan = Join-Path $bundle 'manifest.sha256'
if (-not (Test-Path -LiteralPath $newMan)) { Fail "no bundle at $bundle" }

# ---- what changed ---------------------------------------------------------------------
Step 'Comparing with the base'
$old = ReadManifest $baseMan
$new = ReadManifest $newMan
$files = @{}
foreach ($k in $new.Keys) {
  if ($k -eq 'manifest.sha256') { continue }
  if ($k.StartsWith('app/') -or -not $old.ContainsKey($k) -or $old[$k] -ne $new[$k]) { $files[$k] = $new[$k] }
}
$remove = @($old.Keys | Where-Object { -not $new.ContainsKey($_) -and $_ -ne 'manifest.sha256' } | Sort-Object)
$size = 0
foreach ($k in $files.Keys) { $size += (Get-Item -LiteralPath (Join-Path $bundle $k)).Length }
Write-Host ('  {0} files to carry ({1:N1} MB), {2} to remove' -f $files.Count, ($size / 1MB), $remove.Count)
if ($size -gt 2GB) { Write-Host '  NOTE: a big kit - is the model or Python changing? A full bundle may be simpler.' }

$notesFile = Join-Path $repo "releases\$ver.notes-he.txt"
$notes = @()
if (Test-Path -LiteralPath $notesFile) {
  $notes = @([System.IO.File]::ReadAllLines($notesFile, [System.Text.Encoding]::UTF8) | Where-Object { $_.Trim() })
} else { Write-Host "  NOTE: no releases\$ver.notes-he.txt - the kit has no 'what is new' text" }

# ---- the kit folder -------------------------------------------------------------------
$kitRoot = Join-Path $buildDir "kit-$ver"
$kitName = "HebrewWhisper-$ver-Update"
$kit = Join-Path $kitRoot $kitName
Step "Kit folder $kit"
if (Test-Path -LiteralPath $kitRoot) { Remove-Item -LiteralPath $kitRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $kit | Out-Null
foreach ($k in $files.Keys) {
  $dst = Join-Path $kit ('payload\' + $k.Replace('/', '\'))
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
  Copy-Item -LiteralPath (Join-Path $bundle $k.Replace('/', '\')) -Destination $dst -Force
  if ((Sha256File $dst) -ne $files[$k]) { Fail "copy of $k does not match the bundle's list (stale bundle? run without -SkipBundle)" }
}
Copy-Item -LiteralPath (Join-Path $bundle 'app\apply_update.py') -Destination $kit -Force
foreach ($n in @('UPDATE-HEBREW-WHISPER.bat', 'RESTORE-HEBREW-WHISPER.bat')) {
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot "kit\$n") -Destination $kit -Force
}
$noteLines = ($notes | ForEach-Object { '- ' + $_ }) -join "`r`n"
if (-not $noteLines) { $noteLines = '-' }
$howto = [System.IO.File]::ReadAllText((Join-Path $PSScriptRoot 'kit\HOW-TO-UPDATE-HE.txt'), [System.Text.Encoding]::UTF8)
$howto = $howto.Replace('__VERSION__', $ver).Replace('__NOTES__', $noteLines)
$utf8bom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText((Join-Path $kit 'README-HE.txt'), $howto, $utf8bom)

$json = '{"app": "hebrew-whisper", "version": ' + (JStr $ver) + ', "base": ' + (JStr $Base) +
  ', "built": ' + (JStr (Get-Date -Format 'yyyy-MM-dd HH:mm')) +
  ', "notes_he": [' + (($notes | ForEach-Object { JStr $_ }) -join ', ') + ']' +
  ', "files": ' + (JMap $files) +
  ', "remove": [' + (($remove | ForEach-Object { JStr $_ }) -join ', ') + ']' +
  ', "base_files": ' + (JMap $old) + '}'
[System.IO.File]::WriteAllText((Join-Path $kit 'update.json'), $json, (New-Object System.Text.UTF8Encoding($false)))

# ---- zip + text -----------------------------------------------------------------------
Step 'Zip'
$zip = Join-Path $kitRoot "$kitName-Kit.zip"
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($kit, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $true)
Write-Host ('  {0} ({1:N1} MB)' -f $zip, ((Get-Item -LiteralPath $zip).Length / 1MB))

Step "Encode to text ($ChunkMB MB per .txt)"
$textDir = Join-Path $buildDir "kit-$ver-text"
if (Test-Path -LiteralPath $textDir) { Remove-Item -LiteralPath $textDir -Recurse -Force }
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo 'tools\text-transfer\scripts\TextTransfer-Encode.ps1') -Source $zip -OutDir $textDir -ChunkMB $ChunkMB
if ($LASTEXITCODE -ne 0) { Fail 'encode' }
[System.IO.File]::WriteAllText((Join-Path $textDir 'HOW-TO-UPDATE-HE.txt'), $howto, $utf8bom)

Step 'Check: decode the text files the way the offline PC will'
$probe = Join-Path $env:TEMP ("hw-kit-check-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
Copy-Item -LiteralPath $textDir -Destination $probe -Recurse
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $probe 'TextTransfer-Decode.ps1') -OutDir (Join-Path $probe 'out') | Out-Null
$back = Join-Path $probe "out\$kitName-Kit.zip"
if (-not (Test-Path -LiteralPath $back) -or (Sha256File $back) -ne (Sha256File $zip)) {
  Fail "the text files do not decode back to the kit (look in $probe)"
}
Remove-Item -LiteralPath $probe -Recurse -Force
Write-Host '  decoded byte for byte - OK'

# ---- remember this version's file list ------------------------------------------------
$rel = Join-Path $buildDir 'releases'
New-Item -ItemType Directory -Force -Path $rel | Out-Null
Copy-Item -LiteralPath $newMan -Destination (Join-Path $rel "$ver.manifest.sha256") -Force

Write-Host ''
Write-Host "DONE. Update kit $Base -> $ver. Copy EVERY file in this folder to the stick:"
Write-Host "  $textDir"
exit 0
