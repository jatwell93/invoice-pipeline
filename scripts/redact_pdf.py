"""Redact PDFs by deleting deny-list terms and replacing them with fake values of the same shape.

For every term in your private deny-list, each match in the PDF is removed from the file
(not just covered by a box) and a fake value is written in its place. Digits become other
digits, letters become other letters of the same case, and punctuation and spaces stay.
The same term always gets the same fake value, so a name used on ten invoices stays one
consistent fake name. Metadata, hidden text, attachments and links are scrubbed as well.

The output is checked before it is written: if any deny-list term can still be found in
the redacted text, the file is NOT written. Terms are never printed, only line numbers
from the deny-list file.

Usage:
    python3 scripts/redact_pdf.py SRC_DIR DEST_DIR [--deny-list FILE] [--salt-file FILE]

Needs: pip install pymupdf
Limits: text inside images (logos, scanned pages) is not searched. A term split across
different spacing (for example an ABN written with and without spaces) needs both
spellings on the deny-list.
"""

import argparse
import hashlib
import hmac
import os
import secrets
import sys

import pymupdf

DEFAULT_DENY = os.path.expanduser("~/invoice-private/leak-deny-list.txt")
DEFAULT_SALT = os.path.expanduser("~/invoice-private/redact-salt")


def read_deny_list(path):
    terms = []
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for number, line in enumerate(fh, 1):
            line = line.strip()
            if line and not line.startswith("#"):
                terms.append((number, line))
    # Longest first so a name is replaced whole before any shorter term inside it.
    return sorted(terms, key=lambda t: len(t[1]), reverse=True)


def load_salt(path):
    if os.path.isfile(path):
        with open(path, "rb") as fh:
            return fh.read()
    salt = secrets.token_bytes(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(salt)
    return salt


def fake_for(term, salt, attempt=0):
    """Same-shape fake value, stable for a given term and salt, not guessable without the salt.
    Attempt 0 is the original value; higher attempts give different fakes for the same term."""
    key = term.lower() if attempt == 0 else f"{term.lower()}#{attempt}"
    stream = hashlib.sha256(hmac.new(salt, key.encode(), "sha256").digest()).digest()
    stream += hashlib.sha256(stream).digest()
    out = []
    for i, ch in enumerate(term):
        b = stream[i % len(stream)]
        if ch.isdigit():
            out.append(str(b % 10))
        elif ch.isalpha() and ch.isascii():
            letter = chr(ord("a") + b % 26)
            out.append(letter.upper() if ch.isupper() else letter)
        else:
            out.append(ch)
    return "".join(out)


def make_fakes(terms, salt):
    """One fake per deny-list line. A fake must not contain any deny-list term (a short term can
    turn up by chance inside a random fake), or the finished file would fail its own check."""
    lowered = [t.lower() for _, t in terms]
    fakes = {}
    for number, term in terms:
        for attempt in range(500):
            fake = fake_for(term, salt, attempt)
            if fake.lower() != term.lower() and not any(t in fake.lower() for t in lowered):
                fakes[number] = fake
                break
        else:
            raise SystemExit(f"Deny-list line {number} is too short or too common to give a safe fake value. "
                             "Make it longer or remove it.")
    return fakes


def redact(doc, terms, fakes, images=pymupdf.PDF_REDACT_IMAGE_PIXELS, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE):
    """Mark every term occurrence for removal and apply. Returns (replacements, {line: replacements})."""
    total = 0
    per_term = {}
    for page in doc:
        # Notes, comments and markup can hold private text that page-text checks never see.
        # Invoices do not need them, so remove them all.
        for annot in list(page.annots() or []):
            page.delete_annot(annot)
        marked = []
        for number, term in terms:
            fake = fakes[number]
            for rect in page.search_for(term):
                if any(prev.contains(rect) for prev in marked):
                    continue
                marked.append(rect)
                per_term[number] = per_term.get(number, 0) + 1
                page.add_redact_annot(
                    rect,
                    text=fake,
                    fontname="helv",
                    fontsize=min(11, max(4, rect.height * 0.8)),
                    fill=(1, 1, 1),
                    cross_out=False,
                )
        if marked:
            page.apply_redactions(
                images=images,
                graphics=graphics,
                text=pymupdf.PDF_REDACT_TEXT_REMOVE,
            )
            total += len(marked)
    return total, per_term


def scrub_safely(doc):
    """Scrub metadata, hidden text, attachments and links. Some PDFs have broken internal references
    that make scrub() fail, so retry on a saved-and-reloaded copy, then fall back to metadata only.
    Returns (doc, note); note is empty when the normal path worked."""
    try:
        doc.scrub()
        return doc, ""
    except Exception:
        pass
    try:
        fresh = pymupdf.open(stream=doc.tobytes(garbage=4, clean=True, deflate=True), filetype="pdf")
        fresh.scrub()
        return fresh, "scrub needed a reload"
    except Exception:
        pass
    doc.set_metadata({})
    doc.del_xml_metadata()
    return doc, "PARTIAL SCRUB: metadata cleared, but hidden text and attachments were not removed"


def remaining_hits(data, terms):
    """Deny-list lines still found in the redacted bytes, as {line: where}. Where is the page
    numbers holding it, and 'metadata' if it is in the document properties."""
    check = pymupdf.open(stream=data, filetype="pdf")
    pages = [page.get_text().lower() for page in check]
    meta = " ".join(str(v) for v in check.metadata.values()).lower()
    found = {}
    for n, term in terms:
        low = term.lower()
        where = [f"page{i}" for i, text in enumerate(pages, 1) if low in text]
        if low in meta:
            where.append("metadata")
        if where:
            found[n] = (sum(text.count(low) for text in pages) + meta.count(low), where)
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("src")
    parser.add_argument("dest")
    parser.add_argument("--deny-list", default=DEFAULT_DENY)
    parser.add_argument("--salt-file", default=DEFAULT_SALT)
    args = parser.parse_args()

    if not os.path.isdir(args.src):
        print(f"Not a folder: {args.src}")
        return 2
    if not os.path.isfile(args.deny_list):
        print(f"No deny-list at {args.deny_list}. Create it (one name, address or number per line).")
        return 2
    terms = read_deny_list(args.deny_list)
    if not terms:
        print("Deny-list is empty. Nothing to redact.")
        return 2
    fakes = make_fakes(terms, load_salt(args.salt_file))
    os.makedirs(args.dest, exist_ok=True)

    failed = 0
    for name in sorted(os.listdir(args.src)):
        if not name.lower().endswith(".pdf"):
            continue
        out_path = os.path.join(args.dest, name)
        if os.path.exists(out_path):
            print(f"[skip] {name}: already in {args.dest}")
            continue
        try:
            with pymupdf.open(os.path.join(args.src, name)) as doc:
                if doc.needs_pass:
                    print(f"[FAIL] {name}: password protected")
                    failed += 1
                    continue
                original = {n: sum(p.get_text().lower().count(t.lower()) for p in doc) for n, t in terms}
                replaced, per_term = redact(doc, terms, fakes)
                images = sum(len(page.get_images()) for page in doc)
                doc, note = scrub_safely(doc)
                data = doc.tobytes(garbage=4, deflate=True, clean=True)
        except Exception as err:
            # One bad file must not stop the run. The message is MuPDF's, not document text.
            print(f"[FAIL] {name}: {type(err).__name__}: {err}. Not written.")
            failed += 1
            continue
        hits = remaining_hits(data, terms)
        if hits:
            # original = occurrences in the source text, marked = occurrences the search found and
            # redacted, remaining = occurrences left in the result. Numbers only, never the term.
            detail = "; ".join(f"line {n}: original={original[n]} marked={per_term.get(n, 0)} remaining={count} in={where}"
                               for n, (count, where) in hits.items())
            print(f"[FAIL] {name}: {detail}. Not written.")
            failed += 1
            continue
        with open(out_path, "wb") as fh:
            fh.write(data)
        print(f"[done] {name}: {replaced} replacement(s), {images} image(s) left to check by eye" + (f" ({note})" if note else ""))

    print("\nNext: python3 scripts/leak_scan.py, then look at each file, including logos and images.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
