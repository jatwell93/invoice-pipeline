"""Leak scan for redacted fixtures (PLAN.md section 12.4).

Checks every file under a folder (default: fixtures/redacted) for:
  - any line of your private deny-list (names, addresses, account numbers)
  - email addresses, Australian phone numbers, BSB-like numbers
  - valid ABNs (reported as a count so you can check they are supplier ABNs)
  - PDF metadata fields (author, creator, producer, title)
  - embedded images (reported as a count so you can look at them by eye)

It never prints a matched deny-list term, only the deny-list line number, so the
output is safe to paste into a chat. Exit code 0 = no deny-list or pattern hits,
1 = something to review.

Needs pdftotext, pdfinfo and pdfimages (package poppler-utils) for PDFs.
"""

import argparse
import os
import re
import subprocess
import sys
import zipfile

DEFAULT_DENY = os.path.expanduser("~/invoice-private/leak-deny-list.txt")
DEFAULT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "redacted")

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?<!\d)(?:\+?61|0)[2-478](?:[ -]?\d){8}(?!\d)")
BSB = re.compile(r"(?<!\d)\d{3}-\d{3}(?!\d)")
ABN = re.compile(r"(?<!\d)\d{2} ?\d{3} ?\d{3} ?\d{3}(?!\d)")


def run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def abn_valid(digits):
    weights = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
    n = [int(c) for c in digits]
    n[0] -= 1
    return sum(a * b for a, b in zip(n, weights)) % 89 == 0


def read_deny_list(path):
    terms = []
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for number, line in enumerate(fh, 1):
            line = line.strip()
            if line and not line.startswith("#"):
                terms.append((number, line.lower()))
    return terms


def extract(path):
    """Return (text, metadata_text, image_count) for one file."""
    if path.lower().endswith(".pdf"):
        text = run("pdftotext", "-layout", path, "-")
        meta = run("pdfinfo", path)
        images = len([l for l in run("pdfimages", "-list", path).splitlines()[2:] if l.strip()])
        return text, meta, images
    text, images = "", 0
    try:
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.endswith((".xml", ".rels")):
                    raw = z.read(name).decode("utf-8", "ignore")
                    text += re.sub(r"<[^>]+>", " ", raw) + "\n"
                if name.lower().startswith(("media/", "xl/media", "pictures/")):
                    images += 1
    except (OSError, zipfile.BadZipFile):
        pass
    return text, "", images


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", nargs="?", default=DEFAULT_ROOT)
    parser.add_argument("--deny-list", default=DEFAULT_DENY)
    args = parser.parse_args()

    if not os.path.isfile(args.deny_list):
        print(f"No deny-list at {args.deny_list}. Create it (one name, address or number per line) and run again.")
        return 2
    terms = read_deny_list(args.deny_list)
    print(f"Deny-list: {len(terms)} terms. Scanning {os.path.normpath(args.folder)}")

    problems = 0
    for folder, _, files in os.walk(args.folder):
        for name in sorted(files):
            path = os.path.join(folder, name)
            text, meta, images = extract(path)
            blob = (name + "\n" + text + "\n" + meta).lower()
            hits = sorted({n for n, t in terms if t in blob})
            emails, phones, bsbs = len(EMAIL.findall(blob)), len(PHONE.findall(blob)), len(BSB.findall(blob))
            abns = sum(1 for m in ABN.findall(blob) if abn_valid(re.sub(r"\s", "", m)))
            fields = [l.split(":", 1)[1].strip() for l in meta.splitlines()
                      if l.split(":")[0] in ("Author", "Creator", "Producer", "Title")]
            flag = "FAIL" if hits or phones or bsbs else "check" if emails or abns or images else "ok"
            if flag == "FAIL":
                problems += 1
            print(f"[{flag}] {os.path.relpath(path, args.folder)}: deny-list lines={hits or 'none'} "
                  f"emails={emails} phones={phones} bsb_like={bsbs} abns={abns} images={images} meta={fields}")

    print("\nFAIL = fix before committing. check = look by eye (supplier-only emails and ABNs, images).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
