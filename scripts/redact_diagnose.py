"""Explain why a deny-list term survives redaction in one PDF. Prints structure only, never text.

Usage:
    python3 scripts/redact_diagnose.py FILE.pdf [--deny-list FILE] [--lines 33,11]

For each deny-list line (all of them, or only --lines) found in the page text, it reports:
  text   = occurrences in the page text
  search = occurrences PyMuPDF's search_for() can locate (these are what get redacted)
  MISSED = text found but not locatable, so it cannot be redacted by search
plus the shape of the term, the fonts and text direction of the lines that hold it, and
whether the term runs across more than one text span.
Output is safe to paste: it holds deny-list line numbers, counts and font names only.
"""

import argparse
import os
import re
import sys

import pymupdf

DEFAULT_DENY = os.path.expanduser("~/invoice-private/leak-deny-list.txt")


def shape(term):
    return (f"len={len(term)} digits={sum(c.isdigit() for c in term)} "
            f"letters={sum(c.isalpha() for c in term)} spaces={sum(c.isspace() for c in term)} "
            f"nonascii={sum(not c.isascii() for c in term)}")


def mask(text):
    """Shape of a text snippet with no readable content: A upper, a lower, 9 digit."""
    out = []
    for ch in " ".join(text.split())[:60]:
        out.append("A" if ch.isupper() else "a" if ch.isalpha() else "9" if ch.isdigit() else ch)
    return "".join(out)


def explain_remaining(path, data, terms, fakes):
    """For each occurrence still in the redacted bytes: where it is, whether it is in the same
    spot as in the original, its font and size, and whether it sits inside one of our fake
    values. Positions and font names only, never text."""
    before = pymupdf.open(path)
    after = pymupdf.open(stream=data, filetype="pdf")
    fake_texts = [f.lower() for f in fakes.values()]
    for n, term in terms:
        low = term.lower()
        for pno, page in enumerate(after):
            rects = page.search_for(term)
            if not rects and low in page.get_text().lower():
                print(f"  line {n} page {pno + 1}: in page text but search_for cannot locate it")
                continue
            originals = before[pno].search_for(term)
            spans_all = [s for block in page.get_text("dict")["blocks"] for line in block.get("lines", [])
                         for s in line["spans"]]
            for r in rects:
                same = any(abs(r.x0 - o.x0) < 1 and abs(r.y0 - o.y0) < 1 for o in originals)
                spans = [s for s in spans_all if low in s["text"].lower() and pymupdf.Rect(s["bbox"]).intersects(r)]
                from_fake = any(f in s["text"].lower() for s in spans for f in fake_texts)
                # What was at this spot in the original? Shapes only (A=upper, a=lower, 9=digit).
                clip = pymupdf.Rect(r.x0 - 3, r.y0 - 2, r.x1 + 3, r.y1 + 2)
                was = before[pno].get_text(clip=clip)
                now = after[pno].get_text(clip=clip)
                print(f"  line {n} page {pno + 1}: rect={tuple(round(x) for x in r)} same-spot-as-original={same} "
                      f"font={sorted({s['font'] for s in spans})} size={sorted({round(s['size'], 1) for s in spans})} "
                      f"inside-fake-text={from_fake}\n"
                      f"    original-at-spot has-term={low in was.lower()} shape={mask(was)!r}\n"
                      f"    now-at-spot      has-term={low in now.lower()} shape={mask(now)!r}")


def try_redact(path, terms, salt_file):
    """Redact one file in memory with several removal settings and report what is left.
    Numbers only: the deny-list line and how many occurrences remain."""
    import redact_pdf as r  # same folder as this script

    fakes = r.make_fakes(terms, r.load_salt(salt_file))
    variants = [
        ("default", {}),
        ("images=NONE", {"images": pymupdf.PDF_REDACT_IMAGE_NONE}),
        ("images=REMOVE", {"images": pymupdf.PDF_REDACT_IMAGE_REMOVE}),
        ("graphics=REMOVE_IF_COVERED", {"graphics": pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED}),
    ]
    for label, kwargs in variants:
        try:
            with pymupdf.open(path) as doc:
                replaced, _ = r.redact(doc, terms, fakes, **kwargs)
                data = doc.tobytes(garbage=4, deflate=True, clean=True)
            left = {n: count for n, (count, _) in r.remaining_hits(data, terms).items()}
            print(f"{label}: marked={replaced} remaining={left or 'none'}")
            if label == "default" and left:
                explain_remaining(path, data, [(n, t) for n, t in terms if n in left], fakes)
        except Exception as err:
            print(f"{label}: error {type(err).__name__}: {err}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf")
    parser.add_argument("--deny-list", default=DEFAULT_DENY)
    parser.add_argument("--lines", default="")
    parser.add_argument("--try-redact", action="store_true", help="try removal settings and report what remains")
    parser.add_argument("--salt-file", default=os.path.expanduser("~/invoice-private/redact-salt"))
    args = parser.parse_args()
    only = {int(x) for x in args.lines.split(",") if x.strip()}

    terms = []
    with open(args.deny_list, encoding="utf-8", errors="ignore") as fh:
        for number, line in enumerate(fh, 1):
            line = line.strip()
            if line and not line.startswith("#") and (not only or number in only):
                terms.append((number, line))

    if args.try_redact:
        try_redact(args.pdf, terms, args.salt_file)
        return 0

    doc = pymupdf.open(args.pdf)
    print(f"pages={len(doc)} encrypted={bool(doc.needs_pass)} rotation={sorted({p.rotation for p in doc})}")
    for pno, page in enumerate(doc, 1):
        annots = {}
        for a in page.annots() or []:
            annots[a.type[1]] = annots.get(a.type[1], 0) + 1
        rnd = lambda r: tuple(round(x, 1) for x in r)
        # Structure only: box sizes, annotation kinds, font kinds. No document text.
        print(f"page {pno}: rect={rnd(page.rect)} mediabox={rnd(page.mediabox)} cropbox={rnd(page.cropbox)} "
              f"contents={len(page.get_contents())} annots={annots} drawings={len(page.get_drawings())} "
              f"images={len(page.get_images())} fonts={[(f[2], f[1], f[5]) for f in page.get_fonts()]}")
    for number, term in terms:
        low = term.lower()
        for pno, page in enumerate(doc, 1):
            text = page.get_text().lower()
            n_text = text.count(low)
            n_flat = re.sub(r"\s+", " ", text).count(re.sub(r"\s+", " ", low))
            n_search = len(page.search_for(term))
            if not (n_text or n_flat or n_search):
                continue
            fonts, dirs, in_span, in_line = set(), set(), 0, 0
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    joined = "".join(s["text"] for s in line["spans"]).lower()
                    if low in joined:
                        in_line += 1
                        dirs.add(tuple(round(x, 1) for x in line["dir"]))
                        for s in line["spans"]:
                            fonts.add(s["font"])
                            if low in s["text"].lower():
                                in_span += 1
            flag = "MISSED" if max(n_text, n_flat) > n_search else "ok"
            print(f"line {number} page {pno}: text={n_text} flat={n_flat} search={n_search} {flag} | {shape(term)} "
                  f"| lines={in_line} one-span={in_span} dirs={sorted(dirs)} fonts={sorted(fonts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
