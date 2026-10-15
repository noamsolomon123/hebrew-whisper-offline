Text transfer - moving files across something that only passes TEXT
===================================================================

Binary files (installers, videos, models, zips, photos) are blocked by a one-way transfer
device, a mail filter, or a paste-only remote session. This tool encodes them as numbered
plain-text files -- TextTransfer-001of042.txt, ...002..., and so on -- which cross as text,
and turns them back into the EXACT original bytes on the far side.

Nothing is installed. Both halves are Windows PowerShell, which every Windows 10/11 already
has. No Node, no internet, no admin rights.


On the SOURCE machine
---------------------
  Drag a file or a folder onto ENCODE.bat.
  (Or double-click it and type the path. Or: ENCODE.bat "C:\path\to\folder" 50)

  You get a folder called "<name>-text" next to the original, holding:
      TextTransfer-001of042.txt ... TextTransfer-042of042.txt   (~50 MB each by default)
      DECODE.bat, TextTransfer-Decode.ps1, README-TRANSFER.txt

  A whole folder tree is encoded, sub-folders included, and rebuilt with the same layout.


On the FAR side
---------------
  1. Send EVERY file from that folder across, including DECODE.bat and
     TextTransfer-Decode.ps1. The chunks are numbered "NNNofTTT" so you can see at a glance
     if one did not cross.

  2. Put them all in one folder and double-click DECODE.bat.
       - It checks every chunk is present, and NAMES any that is missing.
       - It verifies every chunk's checksum, so a chunk the device corrupted is caught.
       - It rebuilds the originals into a "decoded" sub-folder and verifies each one.
     Nothing is trusted unless its SHA-256 matches. If anything is wrong it stops, tells you
     exactly which chunk to re-send, and deletes the partial output -- it never leaves a
     half-correct file behind.

  3. The originals are in the "decoded" folder. The .txt chunks are deleted once everything
     has been verified; pass -KeepText to DECODE.bat to keep them.


If the device blocks .bat or .ps1 by their extension
----------------------------------------------------
  Send them as .txt (rename DECODE.bat -> DECODE.bat.txt, TextTransfer-Decode.ps1 ->
  TextTransfer-Decode.ps1.txt), then rename them back on the far side before running.


Notes
-----
  * The text is standard Base64 (A-Z a-z 0-9 + / =), wrapped at 4096 characters per line.
  * Size on the wire is about 4/3 of the original, which is what Base64 costs.
  * A device that rewrites line endings (LF to CRLF) does NOT break the transfer -- the
    checksums are taken over the lines, not the raw bytes.
  * Chunk size: the second argument to ENCODE.bat, in MB. Smaller chunks mean re-sending
    less when one does not make it.
  * Empty folders are not carried across (only files are). Zip them first if you need them.
  * File names may be in any language (Hebrew, Arabic, anything). They travel percent-encoded,
    so every byte of every .txt is plain 7-bit ASCII even then -- a device that passes "text"
    may well mean that literally.
  * Nothing is installed and nothing on the machine is changed. Both halves are Windows
    PowerShell, run with -ExecutionPolicy Bypass scoped to that one run.
