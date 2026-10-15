<#
  TextTransfer-Decode.ps1 -- turns the numbered .txt files back into the exact original bytes,
  on the far side of a transfer that only passes text.

  Run by DECODE.bat, which is what the user double-clicks. Uses nothing but what Windows
  already has: [Convert]::FromBase64String and Get-FileHash. No Node, no internet, nothing
  installed.

  The order is the point:

      1. read every header  -> learn how many chunks the set has
      2. check every chunk 1..N is present   (a missing chunk is NAMED, not "corrupt")
      3. decode chunk 1, the manifest -> the file table (name, sha256, parts)
      4. decode each payload chunk, verifying its body checksum as it streams
      5. verify every reconstructed file against its own SHA-256

  Nothing is trusted until all of that passes. On any failure the half-written output is
  deleted, so a bad transfer never leaves a plausible-looking wrong file behind. This may run
  on a machine nobody can reach to fix, so it fails loudly and completely or not at all.

  ASCII ONLY, deliberately -- Windows PowerShell 5.1 reads a BOM-less UTF-8 .ps1 as ANSI.
#>

[CmdletBinding()]
param(
  [string]$OutDir = '',
  [switch]$KeepText
)

$ErrorActionPreference = 'Stop'
$HEADER_TAG = 'TEXT-TRANSFER/2'
$LF = [string][char]10

$here = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
if (-not $OutDir) { $OutDir = Join-Path $here 'decoded' }

$script:Stream = $null

function Fail([string]$Message) {
  if ($script:Stream) { $script:Stream.Dispose(); $script:Stream = $null }
  Write-Host ''
  Write-Host "  $Message" -ForegroundColor Red
  # Leave nothing behind that looks like a good result.
  if (Test-Path -LiteralPath $OutDir) { Remove-Item -Recurse -Force -LiteralPath $OutDir -ErrorAction SilentlyContinue }
  Write-Host ''
  exit 1
}
function Step([string]$Message) { Write-Host "  $Message" }

# Anything unforeseen (a full disk, a locked file, a chunk mangled in a way not anticipated)
# still has to leave no half-written output behind and still has to say something a person can
# act on. Nothing gets to escape as a raw .NET stack trace.
trap { Fail ('Decoding stopped: ' + $_.Exception.Message) }

# SHA-256 straight from .NET rather than Get-FileHash: that cmdlet lives in a module that has
# to autoload, which is not guaranteed on the locked-down machine this is most likely to run
# on. The class below is always there. It streams, so file size is fine.
function Get-Sha256([string]$path) {
  $sha = [System.Security.Cryptography.SHA256]::Create()
  $fs = New-Object System.IO.FileStream($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
  try {
    return ([BitConverter]::ToString($sha.ComputeHash($fs)) -replace '-', '').ToLower()
  } finally {
    $fs.Dispose()
    $sha.Dispose()
  }
}

$utf8 = New-Object System.Text.UTF8Encoding($false)
function New-Reader([string]$path) {
  New-Object System.IO.StreamReader($path, $utf8, $true)
}

# Paths travel percent-encoded (UTF-8 bytes, %XX) so the chunks stay 7-bit ASCII whatever the
# files are named. This is the inverse.
function Decode-Path([string]$enc) {
  $bytes = New-Object System.Collections.Generic.List[byte]
  for ($i = 0; $i -lt $enc.Length; $i++) {
    $ch = $enc[$i]
    if ($ch -eq '%') {
      if ($i + 2 -ge $enc.Length) { Fail "A file name in the manifest is truncated: $enc" }
      $hex = $enc.Substring($i + 1, 2)
      $b = 0
      if (-not [byte]::TryParse($hex, [System.Globalization.NumberStyles]::HexNumber, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$b)) {
        Fail "A file name in the manifest is malformed: $enc"
      }
      $bytes.Add($b)
      $i += 2
    } elseif ([int]$ch -lt 128) {
      $bytes.Add([byte][int]$ch)
    } else {
      # Not produced by the encoder, but a device may have re-encoded something; keep it.
      foreach ($b2 in $utf8.GetBytes([string]$ch)) { $bytes.Add($b2) }
    }
  }
  return $utf8.GetString($bytes.ToArray())
}

# Reads only the header of a chunk (the few lines before BODY) into a hashtable.
function Read-Header([string]$path) {
  $h = @{}
  $reader = New-Reader $path
  try {
    if ($reader.ReadLine() -ne $HEADER_TAG) { return $null }
    while ($true) {
      $line = $reader.ReadLine()
      if ($null -eq $line -or $line -eq 'BODY') { break }
      $eq = $line.IndexOf('=')
      if ($eq -gt 0) { $h[$line.Substring(0, $eq)] = $line.Substring($eq + 1) }
    }
  } finally { $reader.Dispose() }
  return $h
}

# A relative path out of the transfer is untrusted input: it decides where a file gets
# written. Anything absolute, drive-qualified, or climbing out of $OutDir is refused outright
# rather than sanitised, because no legitimate path from the encoder looks like that.
function Resolve-SafePath([string]$rootFull, [string]$rel) {
  if (-not $rel) { Fail 'The manifest names a file with no path.' }
  $r = $rel -replace '/', '\'
  if ($r.StartsWith('\') -or $r -match '^[A-Za-z]:') { Fail "Refusing an absolute path from the transfer: $rel" }
  foreach ($seg in $r.Split('\')) {
    if ($seg -eq '..') { Fail "Refusing a path that climbs out of the output folder: $rel" }
  }
  $full = [System.IO.Path]::GetFullPath((Join-Path $rootFull $r))
  if (-not $full.StartsWith($rootFull.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    Fail "Refusing a path that resolves outside the output folder: $rel"
  }
  return $full
}

# ---------------------------------------------------------------- 1. gather ---------------
$texts = @(Get-ChildItem -LiteralPath $here -Filter 'TextTransfer-*.txt' -File -ErrorAction SilentlyContinue | Sort-Object Name)
if ($texts.Count -eq 0) {
  Fail 'No TextTransfer-*.txt files found next to this script. Copy them here first.'
}

$chunks = @{}
$total = 0
foreach ($t in $texts) {
  $head = Read-Header $t.FullName
  if (-not $head) { continue }
  $seq = [int]$head['seq']
  $chunks[$seq] = @{
    path  = $t.FullName
    kind  = $head['kind']
    file  = $head['file']
    part  = $(if ($head['part']) { [int]$head['part'] } else { 0 })
    parts = $(if ($head['parts']) { [int]$head['parts'] } else { 0 })
  }
  if ($total -eq 0 -and $head['total']) { $total = [int]$head['total'] }
}
if ($total -eq 0) { Fail 'None of the .txt files could be read as a text transfer. They may be damaged.' }

Write-Host ''
Write-Host '  Text transfer - decoding'
Write-Host '  ========================'
Step "Folder: $here"
Step "Transfer of $total chunk(s)."

# ---------------------------------------------------------------- 2. completeness ---------
$missing = @()
for ($i = 1; $i -le $total; $i++) { if (-not $chunks.ContainsKey($i)) { $missing += $i } }
if ($missing.Count -gt 0) {
  # This is why the transfer is numbered .txt files rather than one stream: the piece that
  # did not cross can be named.
  $width = "$total".Length
  $names = $missing | ForEach-Object { 'TextTransfer-' + "$_".PadLeft($width, '0') + "of$total.txt" }
  $nl = [Environment]::NewLine
  Fail ('These chunks have not crossed yet:' + $nl + '    ' + ($names -join ($nl + '    ')))
}
Step "All $total chunks are present."

# Corruption in transit can make a body stop being valid Base64 at all -- a mangled CHUNKSHA
# line, for instance, reads as one more body line. That must come out as "re-send this chunk",
# not as a raw .NET exception that skips the cleanup and tells the user nothing.
function ConvertFrom-Base64([string]$text, [hashtable]$c) {
  try {
    return [Convert]::FromBase64String($text)
  } catch {
    Fail "Chunk $($c.seq2) did not survive the transfer -- its text is damaged. Send it again."
  }
}

# Streams one chunk's body: verifies CHUNKSHA, and hands each decoded block to $OnBlock.
# Returns the body's lines when $CollectLines (used for the small manifest only).
function Read-Body([hashtable]$c, [scriptblock]$OnBlock, [bool]$CollectLines) {
  $sha = [System.Security.Cryptography.SHA256]::Create()
  $reader = New-Reader $c.path
  $b64 = New-Object System.Text.StringBuilder
  $lines = New-Object System.Collections.ArrayList
  $footer = $null
  try {
    while ($true) { $l = $reader.ReadLine(); if ($null -eq $l -or $l -eq 'BODY') { break } }
    while ($true) {
      $line = $reader.ReadLine()
      if ($null -eq $line) { break }
      if ($line.StartsWith('CHUNKSHA=')) { $footer = $line.Substring(9); break }
      # Hash the body rebuilt as (line + LF), so a device that rewrote the line endings in
      # transit still checksums identically while a corrupted character does not.
      $bytes = $utf8.GetBytes($line + $LF)
      [void]$sha.TransformBlock($bytes, 0, $bytes.Length, $null, 0)
      if ($CollectLines) { [void]$lines.Add($line) }
      else {
        [void]$b64.Append($line)
        # Flush on whole-line boundaries only, so the accumulated Base64 is always a multiple
        # of 4 characters and decodes on its own -- the decoder never holds a whole chunk.
        if ($b64.Length -ge 8000000) {
          & $OnBlock (ConvertFrom-Base64 $b64.ToString() $c)
          [void]$b64.Clear()
        }
      }
    }
    if (-not $CollectLines -and $b64.Length -gt 0) {
      & $OnBlock (ConvertFrom-Base64 $b64.ToString() $c)
    }
  } finally { $reader.Dispose() }

  [void]$sha.TransformFinalBlock((New-Object byte[] 0), 0, 0)
  $got = ([BitConverter]::ToString($sha.Hash) -replace '-', '').ToLower()
  $sha.Dispose()

  if (-not $footer) { Fail "Chunk $($c.seq2): the chunk has no CHUNKSHA line -- it was cut off in transit. Send it again." }
  if ($got -ne $footer.ToLower()) { Fail "Chunk $($c.seq2) did not survive the transfer -- its checksum does not match. Send it again." }
  return $lines
}

# ---------------------------------------------------------------- 3. manifest -------------
$manifest = $chunks[1]
$manifest.seq2 = '1 (the manifest)'
if ($manifest.kind -ne 'manifest') { Fail 'Chunk 1 is not the manifest. The set is mixed up -- re-send the whole transfer.' }

$noop = { param($b) }
$mLines = Read-Body $manifest $noop $true

$files = New-Object System.Collections.ArrayList
foreach ($line in $mLines) {
  if (-not $line) { continue }
  # "<sha256> <parts> <relative/path>" -- the path is last, so it may contain spaces.
  $sp1 = $line.IndexOf(' ')
  $sp2 = $line.IndexOf(' ', $sp1 + 1)
  if ($sp1 -lt 0 -or $sp2 -lt 0) { Fail 'The manifest is malformed. Re-send chunk 1.' }
  $relEnc = $line.Substring($sp2 + 1)
  [void]$files.Add([pscustomobject]@{
    Sha    = $line.Substring(0, $sp1)
    Parts  = [int]$line.Substring($sp1 + 1, $sp2 - $sp1 - 1)
    RelEnc = $relEnc
    Rel    = Decode-Path $relEnc
  })
}
if ($files.Count -eq 0) { Fail 'The manifest lists no files.' }
Step "Manifest: $($files.Count) file(s)."

# ---------------------------------------------------------------- 4. decode ---------------
if (Test-Path -LiteralPath $OutDir) { Remove-Item -Recurse -Force -LiteralPath $OutDir }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$rootFull = (Get-Item -LiteralPath $OutDir).FullName

# Index the payload chunks by file+part, so the manifest -- not readdir order -- decides what
# gets appended to what.
$byFilePart = @{}
foreach ($seq in $chunks.Keys) {
  $c = $chunks[$seq]
  if ($c.kind -ne 'payload') { continue }
  $byFilePart["$($c.file)`t$($c.part)"] = $seq
}

$done = 0
foreach ($f in $files) {
  $dest = Resolve-SafePath $rootFull $f.Rel
  $dir = Split-Path -Parent $dest
  if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }

  # Create on the first part, append on the rest: a chunk never spans two files, so appending
  # parts in order rebuilds the file with no byte-offset bookkeeping.
  $script:Stream = New-Object System.IO.FileStream($dest, [IO.FileMode]::Create, [IO.FileAccess]::Write)
  try {
    for ($part = 1; $part -le $f.Parts; $part++) {
      $key = "$($f.RelEnc)`t$part"
      if (-not $byFilePart.ContainsKey($key)) {
        Fail "No chunk carries part $part of $($f.Rel). Re-send the transfer."
      }
      $c = $chunks[$byFilePart[$key]]
      $c.seq2 = "$($byFilePart[$key]) ($($f.Rel) part $part/$($f.Parts))"
      $sink = { param($bytes) $script:Stream.Write($bytes, 0, $bytes.Length) }
      [void](Read-Body $c $sink $false)
      Write-Host ("  decoded $($f.Rel) part $part/$($f.Parts)                    ") -NoNewline
      Write-Host ([string][char]13) -NoNewline
    }
  } finally {
    if ($script:Stream) { $script:Stream.Dispose(); $script:Stream = $null }
  }
  $done++
}

# ---------------------------------------------------------------- 5. verify files ---------
Write-Host ''
Step 'Checking every reconstructed file against its checksum...'
foreach ($f in $files) {
  $dest = Resolve-SafePath $rootFull $f.Rel
  if (-not (Test-Path -LiteralPath $dest)) { Fail "The transfer finished but $($f.Rel) was not reconstructed." }
  $got = Get-Sha256 $dest
  if ($got -ne $f.Sha.ToLower()) { Fail "$($f.Rel) does not match its checksum after decoding. Send its chunks again." }
}
Step "$($files.Count) file(s) reconstructed and verified."

if (-not $KeepText) {
  # The .txt chunks are large and no longer needed; the verified originals are in $OutDir.
  foreach ($t in $texts) { Remove-Item -Force -LiteralPath $t.FullName -ErrorAction SilentlyContinue }
}

Write-Host ''
Step 'Done. The original files are in:'
Step "  $rootFull"
Write-Host ''
exit 0
