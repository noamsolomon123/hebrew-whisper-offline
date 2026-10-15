<#
  TextTransfer-Encode.ps1 -- turns any file or folder into numbered plain-text (.txt) chunks,
  for crossing a one-way transfer device / mail filter / anything that only passes text.

  The reverse is TextTransfer-Decode.ps1, which travels with the chunks and needs nothing but
  Windows PowerShell -- no Node, no internet, nothing installed.

      powershell -File TextTransfer-Encode.ps1 "C:\some\folder" [-OutDir <dir>] [-ChunkMB 50]

  FORMAT (TEXT-TRANSFER/2)
  -----------------------
  Chunk 1 is the MANIFEST: one line per file, "<sha256> <parts> <relative/path>".
  Chunks 2..N are payload: one file (or a slice of one) as Base64, wrapped at 4096 chars.
  A chunk never spans two files, so the decoder rebuilds a file by appending its parts in
  order and never tracks a byte offset across a file boundary.

      TEXT-TRANSFER/2
      seq=<n>  total=<N>  kind=manifest|payload
      file=<relative/path>  part=<p>  parts=<pp>     (payload only)
      BODY
      <body lines>
      CHUNKSHA=<sha256>

  Every chunk header carries total=<N>, so ANY single chunk tells the decoder how many there
  should be and a missing one is NAMED rather than guessed at. CHUNKSHA is taken over the body
  rebuilt as (line + LF) per line -- not over the raw bytes -- so a device that rewrites LF to
  CRLF does not break the checksum, while a device that corrupts a character does.

  Why the manifest is its own chunk rather than a header field repeated everywhere: with
  thousands of files the file table is bigger than many of the chunks. Keeping total= in every
  header preserves the property that matters (any chunk knows the size of the set); the table
  itself is needed only once, at the end, to verify what was rebuilt.

  File names may be in any language. They travel percent-encoded (UTF-8 bytes, %XX), so every
  byte of every chunk stays printable 7-bit ASCII -- a device that passes "text" may mean that
  literally.

  This SCRIPT is ASCII only, deliberately: Windows PowerShell 5.1 reads a BOM-less UTF-8 .ps1
  as ANSI, which can break parsing outright.
#>

[CmdletBinding()]
param(
  [Parameter(Position = 0)][string]$Source = '',
  [string]$OutDir = '',
  [int]$ChunkMB = 50
)

$ErrorActionPreference = 'Stop'
$HEADER_TAG = 'TEXT-TRANSFER/2'
$WRAP = 4096
$LF = [string][char]10
$utf8 = New-Object System.Text.UTF8Encoding($false)

# Paths go into the chunks percent-encoded (UTF-8 bytes, %XX for anything but A-Za-z0-9-._~/).
# That is what keeps EVERY byte of EVERY chunk inside printable ASCII even when the files are
# named in Hebrew, Arabic or anything else -- a transfer device that passes "text" may well
# mean 7-bit text. It also removes the risk of a device trimming a trailing space in a name.
function Encode-Path([string]$rel) {
  $sb = New-Object System.Text.StringBuilder
  foreach ($b in $utf8.GetBytes($rel)) {
    $c = [char]$b
    if (($b -ge 48 -and $b -le 57) -or ($b -ge 65 -and $b -le 90) -or ($b -ge 97 -and $b -le 122) -or
        $c -eq '-' -or $c -eq '.' -or $c -eq '_' -or $c -eq '~' -or $c -eq '/') {
      [void]$sb.Append($c)
    } else {
      [void]$sb.AppendFormat('%{0:X2}', $b)
    }
  }
  return $sb.ToString()
}

# SHA-256 straight from .NET rather than Get-FileHash: that cmdlet lives in a module that has
# to autoload, which is not guaranteed on a locked-down machine or when the environment reaches
# PowerShell through a .bat. The class below is always there. It streams, so file size is fine.
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

$here = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }

function Fail([string]$Message) {
  Write-Host ''
  Write-Host "  $Message" -ForegroundColor Red
  exit 1
}
function Step([string]$Message) { Write-Host "  $Message" }

# ---------------------------------------------------------------- 0. arguments ------------
if (-not $Source) { Fail 'Nothing to encode. Pass a file or folder, or drag one onto ENCODE.bat.' }
if (-not (Test-Path -LiteralPath $Source)) { Fail "Not found: $Source" }
if ($ChunkMB -lt 1 -or $ChunkMB -gt 4096) { Fail "-ChunkMB must be between 1 and 4096 (got $ChunkMB)." }

$item = Get-Item -LiteralPath $Source -Force
$isDir = $item.PSIsContainer
$root = if ($isDir) { $item.FullName } else { $item.Directory.FullName }

if (-not $OutDir) {
  $leaf = if ($isDir) { $item.Name } else { $item.BaseName }
  $OutDir = Join-Path (Split-Path -Parent $item.FullName) ($leaf + '-text')
}

# Bytes of source per chunk: the text target scaled by 3/4 (Base64's ratio), floored to a
# multiple of 3 so no chunk but a file's last one carries Base64 padding.
$slice = [int64][Math]::Max(3, [Math]::Floor(($ChunkMB * 1MB * 3 / 4) / 3) * 3)

# ---------------------------------------------------------------- 1. list + hash ----------
Write-Host ''
Write-Host '  Text transfer - encoding'
Write-Host '  ========================'
Step "Source: $($item.FullName)"

$sources = @(if ($isDir) {
  Get-ChildItem -LiteralPath $root -Recurse -File -Force | Sort-Object FullName
} else {
  $item
})
if ($sources.Count -eq 0) { Fail "$root has no files to encode." }

# The output must never sit inside the input, or the encoder would encode its own chunks.
$outFull = [System.IO.Path]::GetFullPath($OutDir).TrimEnd('\') + '\'
if ($isDir -and $outFull.StartsWith($root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
  Fail 'The output folder is inside the source folder. Pass -OutDir somewhere else.'
}

Step "Hashing $($sources.Count) file(s)..."
$files = @()
$rootPrefix = $root.TrimEnd('\') + '\'
foreach ($f in $sources) {
  # Relative path with forward slashes: portable, and it keeps the folder tree.
  $rel = $f.FullName
  if ($rel.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    $rel = $rel.Substring($rootPrefix.Length)
  } else {
    $rel = $f.Name
  }
  $rel = $rel -replace '\\', '/'
  if ($rel.IndexOf([char]10) -ge 0 -or $rel.IndexOf([char]13) -ge 0) {
    Fail "This file name contains a line break and cannot be transferred: $rel"
  }

  $parts = if ($f.Length -eq 0) { 1 } else { [int][Math]::Ceiling($f.Length / $slice) }
  $files += [pscustomobject]@{
    Path   = $f.FullName
    Rel    = $rel
    RelEnc = Encode-Path $rel
    Bytes = [int64]$f.Length
    Sha   = Get-Sha256 $f.FullName
    Parts = $parts
  }
}

$total = 1 + [int](($files | Measure-Object -Property Parts -Sum).Sum)
$width = "$total".Length
$totalBytes = [int64](($files | Measure-Object -Property Bytes -Sum).Sum)

function ChunkName([int]$seq) { 'TextTransfer-' + "$seq".PadLeft($width, '0') + "of$total.txt" }

if (Test-Path -LiteralPath $OutDir) {
  # Clear stale chunks from an earlier run, so a shorter transfer cannot leave orphans that
  # make the set look complete.
  Get-ChildItem -LiteralPath $OutDir -Filter 'TextTransfer-*.txt' -File -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
} else {
  New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
}
$OutDir = (Get-Item -LiteralPath $OutDir).FullName

Step ("{0} file(s), {1:N1} MB -> {2} chunk(s) of ~{3} MB" -f $files.Count, ($totalBytes / 1MB), $total, $ChunkMB)
Write-Host ''

# ---------------------------------------------------------------- 2. writer helper --------

function New-Chunk([int]$seq) {
  $w = New-Object System.IO.StreamWriter((Join-Path $OutDir (ChunkName $seq)), $false, $utf8)
  $w.NewLine = $LF
  return $w
}

# ---------------------------------------------------------------- 3. manifest chunk -------
$w = New-Chunk 1
$sha = [System.Security.Cryptography.SHA256]::Create()
try {
  $w.Write("$HEADER_TAG$LF" + "seq=1$LF" + "total=$total$LF" + "kind=manifest$LF" +
           "files=$($files.Count)$LF" + "BODY$LF")
  foreach ($f in $files) {
    $line = "$($f.Sha) $($f.Parts) $($f.RelEnc)$LF"
    $b = $utf8.GetBytes($line)
    [void]$sha.TransformBlock($b, 0, $b.Length, $null, 0)
    $w.Write($line)
  }
  [void]$sha.TransformFinalBlock((New-Object byte[] 0), 0, 0)
  $w.Write('CHUNKSHA=' + ([BitConverter]::ToString($sha.Hash) -replace '-', '').ToLower() + $LF)
} finally {
  $sha.Dispose()
  $w.Dispose()
}
Step ((ChunkName 1) + '   (manifest)')

# ---------------------------------------------------------------- 4. payload chunks -------
$seq = 1
$BLOCK = 3 * 1024 * 1024   # multiple of 3: Base64 of consecutive blocks concatenates cleanly
$buf = New-Object byte[] $BLOCK

foreach ($f in $files) {
  $fs = New-Object System.IO.FileStream($f.Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
  try {
    for ($part = 1; $part -le $f.Parts; $part++) {
      $seq++
      $offset = [int64]($part - 1) * $slice
      $length = [int64][Math]::Max(0, [Math]::Min($slice, $f.Bytes - $offset))
      $fs.Position = $offset

      $w = New-Chunk $seq
      $sha = [System.Security.Cryptography.SHA256]::Create()
      try {
        $w.Write("$HEADER_TAG$LF" + "seq=$seq$LF" + "total=$total$LF" + "kind=payload$LF" +
                 "file=$($f.RelEnc)$LF" + "part=$part$LF" + "parts=$($f.Parts)$LF" + "BODY$LF")

        $remaining = $length
        $carry = ''
        while ($remaining -gt 0) {
          $want = [int][Math]::Min([int64]$BLOCK, $remaining)
          $got = $fs.Read($buf, 0, $want)
          if ($got -le 0) { break }
          $remaining -= $got
          $s = $carry + [Convert]::ToBase64String($buf, 0, $got)
          $cut = $s.Length - ($s.Length % $WRAP)
          if ($cut -gt 0) {
            $sb = New-Object System.Text.StringBuilder
            for ($i = 0; $i -lt $cut; $i += $WRAP) {
              [void]$sb.Append($s, $i, $WRAP)
              [void]$sb.Append($LF)
            }
            $text = $sb.ToString()
            $b = $utf8.GetBytes($text)
            [void]$sha.TransformBlock($b, 0, $b.Length, $null, 0)
            $w.Write($text)
          }
          $carry = $s.Substring($cut)
        }
        # Only a file's final block leaves a partial line; flush it whole so every body line
        # stays a multiple of 4 characters except possibly the last.
        if ($carry.Length -gt 0) {
          $text = $carry + $LF
          $b = $utf8.GetBytes($text)
          [void]$sha.TransformBlock($b, 0, $b.Length, $null, 0)
          $w.Write($text)
        }

        [void]$sha.TransformFinalBlock((New-Object byte[] 0), 0, 0)
        $w.Write('CHUNKSHA=' + ([BitConverter]::ToString($sha.Hash) -replace '-', '').ToLower() + $LF)
      } finally {
        $sha.Dispose()
        $w.Dispose()
      }
      Write-Host ('  ' + (ChunkName $seq) + "   ($($f.Rel) part $part/$($f.Parts))          ") -NoNewline
      Write-Host ([string][char]13) -NoNewline
    }
  } finally { $fs.Dispose() }
}

# ---------------------------------------------------------------- 5. ship the decoder -----
# The decoder and its double-click wrapper travel alongside -- small, plain text.
$parent = Split-Path -Parent $here
foreach ($name in @('DECODE.bat', 'TextTransfer-Decode.ps1', 'README-TRANSFER.txt')) {
  if (Test-Path -LiteralPath (Join-Path $OutDir $name)) { continue }
  foreach ($dir in @($here, $parent, (Join-Path $parent 'scripts'))) {
    $from = Join-Path $dir $name
    if (Test-Path -LiteralPath $from) {
      Copy-Item -LiteralPath $from -Destination (Join-Path $OutDir $name) -Force
      break
    }
  }
}

Write-Host ''
Write-Host ''
Step ("{0} chunk(s) written to:" -f $total)
Step "  $OutDir"
Step 'Send EVERY file in that folder across, then double-click DECODE.bat on the far side.'
Write-Host ''
exit 0
