#!/usr/bin/env bash
# Copy documents from SRC to DEST with all metadata removed. Originals are never changed.
# Usage: scripts/strip_metadata.sh SRC_DIR DEST_DIR
# Needs: exiftool and qpdf  (sudo apt install libimage-exiftool-perl qpdf)
# This removes metadata only. It does NOT remove text hidden under black boxes.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 SRC_DIR DEST_DIR" >&2
  exit 2
fi
src=$1
dest=$2
for tool in exiftool qpdf; do
  command -v "$tool" >/dev/null || { echo "Missing $tool. Run: sudo apt install libimage-exiftool-perl qpdf" >&2; exit 2; }
done
[ -d "$src" ] || { echo "Not a folder: $src" >&2; exit 2; }
mkdir -p "$dest"

shopt -s nullglob nocaseglob
count=0
for f in "$src"/*.pdf "$src"/*.xlsx "$src"/*.ods; do
  out="$dest/$(basename "$f")"
  if [ -e "$out" ]; then
    echo "skip (already in $dest): $(basename "$f")"
    continue
  fi
  cp -- "$f" "$out"
  exiftool -all= -overwrite_original -q "$out"
  case "${out,,}" in
    *.pdf) qpdf --linearize --replace-input "$out" ;;
  esac
  echo "cleaned: $(basename "$f")"
  count=$((count + 1))
done
echo "Done. $count file(s) written to $dest. Run: python3 scripts/leak_scan.py"
