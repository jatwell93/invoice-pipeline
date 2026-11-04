#!/usr/bin/env python3
"""Thin-path spike: pdf-inspector -> keyword rules -> vendor pack -> extract -> validation rail.

Usage: .venv-spike/bin/python pipeline/spike.py [pdf ...]
Defaults to the four research sample invoices.
"""
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pdf_inspector

ROOT = Path(__file__).parent
VENDOR_DIR = ROOT / "vendors"
SAMPLES = ROOT.parent / "research/invoice-automation/examples/invoices"

ABN_WEIGHTS = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]

# Ordered: first hit wins. "invoice" is deliberately last and broad —
# credit notes/statements/remittances all contain the word invoice.
CLASS_RULES = [
    ("fred_report", r"completed (invoice|credit note) (summary|details)"),
    ("credit_note", r"adjustment note|credit note|credit memo"),
    ("proforma", r"pro[ -]?forma"),
    ("statement", r"account statement|statement date|opening balance|closing balance"),
    # Line-anchored: a remittance/reminder doc has it as a title. Mid-sentence
    # mentions (e.g. "send your remittance advice to ...") are payment boilerplate.
    ("remittance", r"(?:^|\n)\s*#?\s*(?:<u>)?\s*remittance (advice|receipt)"),
    ("reminder", r"(?:^|\n)\s*#?\s*(?:<u>)?\s*(payment reminder|overdue notice|final notice)"),
    ("invoice", r"tax invoice|invoice"),
]

MONEY_RE = re.compile(r"[^\d.\-]")
DATE_FMTS = ("%d/%m/%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y")


def abn_valid(digits: str) -> bool:
    if len(digits) != 11 or not digits.isdigit():
        return False
    d = [int(c) for c in digits]
    d[0] -= 1
    return sum(a * b for a, b in zip(d, ABN_WEIGHTS)) % 89 == 0


def to_money(raw):
    s = MONEY_RE.sub("", raw)
    return round(float(s), 2) if s not in ("", "-", ".") else None


def to_date(raw):
    s = raw.strip().rstrip(".")
    for fmt in DATE_FMTS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def classify(md: str) -> tuple[str, str]:
    for kind, pat in CLASS_RULES:
        if re.search(pat, md, re.I):
            return kind, f"rule:{pat.split('|')[0]}"
    return "other", "no rule hit"


def load_packs():
    packs = []
    for p in sorted(VENDOR_DIR.glob("*.json")):
        packs.append(json.loads(p.read_text()))
    return packs


def find_abn(md: str):
    m = re.search(r"ABN[: ]?\s*\**\s*([0-9][0-9 ]{9,15}[0-9])", md, re.I)
    if not m:
        return None
    return re.sub(r"\D", "", m.group(1))[:11]


def match_vendor(md: str, abn: str | None, packs):
    for pack in packs:
        if abn and pack.get("abn") == abn:
            return pack, "abn"
    up = md.upper()
    for pack in packs:
        for name in pack.get("match_names", []):
            if name.upper() in up:
                return pack, f"name:{name}"
    return None, "no pack matched"


def apply_field(md: str, spec):
    if isinstance(spec, str):
        spec = {"regex": spec}
    m = re.search(spec["regex"], md, re.S)
    if not m:
        return None
    return m.group(spec.get("group", 1))


def extract(md: str, pack: dict) -> dict:
    out = {}
    for name, spec in pack.get("fields", {}).items():
        out[name] = apply_field(md, spec)
    return out


@dataclass
class Verdict:
    code: str
    ok: bool
    detail: str = ""


def validate(doc_type: str, pack: dict | None, fields: dict, abn: str | None) -> list[Verdict]:
    v = []
    v.append(Verdict("V-ABN", abn is not None and abn_valid(abn), abn or "no ABN found"))

    ex, gst, inc = (to_money(fields.get(k) or "") for k in ("ex_gst", "gst", "inc_gst"))
    if ex is not None and gst is not None:
        v.append(Verdict("V-GST", abs(gst - ex * 0.10) <= 0.03, f"ex={ex} gst={gst}"))
    if ex is not None and gst is not None and inc is not None:
        v.append(Verdict("V-TOT", abs(inc - (ex + gst)) <= 0.02, f"ex+gst={ex + gst:.2f} inc={inc}"))

    if doc_type == "credit_note":
        v.append(Verdict("V-SIGN", inc is not None and inc < 0, f"credit total={inc}"))
        v.append(Verdict("V-REF", bool(fields.get("ref_invoice")), fields.get("ref_invoice") or "no ref invoice"))
    elif doc_type == "invoice":
        v.append(Verdict("V-SIGN", inc is not None and inc > 0, f"invoice total={inc}"))

    inv_d = to_date(fields["invoice_date"]) if fields.get("invoice_date") else None
    v.append(Verdict("V-DATE", inv_d is not None, str(inv_d or fields.get("invoice_date") or "missing")))
    due = fields.get("_due_date")
    if due and inv_d and due < inv_d:
        v.append(Verdict("V-DUE", False, f"due {due} before invoice date {inv_d}"))

    key = f"{(pack or {}).get('id', '?')}|{fields.get('invoice_number')}"
    v.append(Verdict("V-KEY", bool(fields.get("invoice_number")), key))
    return v


ODS_T = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
ODS_P = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


def ods_rows(path: Path):
    root = ET.fromstring(zipfile.ZipFile(path).read("content.xml"))
    rows = []
    for tbl in root.iter(ODS_T + "table"):
        for row in tbl.iter(ODS_T + "table-row"):
            rep = int(row.get(ODS_T + "number-rows-repeated", 1))
            cells = []
            for c in row.iter(ODS_T + "table-cell"):
                crep = int(c.get(ODS_T + "number-columns-repeated", 1))
                txt = " ".join(t.text or "" for t in c.iter(ODS_P + "p")).strip()
                cells.extend([txt] * min(crep, 8))
            for _ in range(min(rep, 3)):
                rows.append(cells)
    return rows


def load_doc(path: Path):
    """Source dispatch: bytes -> (text, meta). PDF via pdf-inspector; ODS table -> rows."""
    if path.suffix.lower() == ".ods":
        rows = ods_rows(path)
        md = "\n".join(" | ".join(cells).rstrip(" |") for cells in rows)
        return md, {"pdf_type": "ods", "pdf_confidence": 1.0, "rows": rows}
    r = pdf_inspector.process_pdf(str(path))
    return r.markdown, {"pdf_type": r.pdf_type, "pdf_confidence": round(r.confidence, 2)}


# --- Fred report extraction ------------------------------------------------
FRED_SUP = re.compile(r"Supplier Name:(.+)")
FRED_DT = re.compile(r"Invoice Date:(\d{1,2}/\d{2}/\d{4})")
FRED_INV = re.compile(r"^\d{4,}[\w\-/]*$")  # Fred splits multi-part invoices: 534765, 534765-2
FRED_MONEY = re.compile(r"^\$?-?[\d,]+\.\d{2}$")


def parse_fred(rows):
    def money(c):
        return to_money(c) if c and FRED_MONEY.match(c) else None

    suppliers, sup, grp, bare_totals = [], None, None, []
    for r in rows:
        vals = [c for c in r if c]
        if not vals:
            continue
        m = FRED_SUP.match(vals[0])
        if m:
            sup = {"name": m.group(1).strip(), "total": money(vals[1] if len(vals) > 1 else ""),
                   "tax": money(vals[2] if len(vals) > 2 else ""), "groups": []}
            suppliers.append(sup)
            grp = None
            continue
        m = FRED_DT.match(vals[0])
        if m and sup is not None:
            grp = {"date": to_date(m.group(1)), "total": money(vals[1] if len(vals) > 1 else ""),
                   "tax": money(vals[2] if len(vals) > 2 else ""), "invoices": []}
            sup["groups"].append(grp)
            continue
        if FRED_INV.match(vals[0]) and grp is not None:
            grp["invoices"].append({"number": vals[0], "total": money(vals[1] if len(vals) > 1 else ""),
                                    "tax": money(vals[2] if len(vals) > 2 else "")})
            continue
        if FRED_MONEY.match(vals[0]):
            bare_totals.append({"total": money(vals[0]), "tax": money(vals[1] if len(vals) > 1 else "")})

    gen = None
    for r in rows:
        ds = [c for c in r if re.fullmatch(r"\d{1,2}/\d{2}/\d{4}", c or "")]
        if ds:
            gen = ds[-1]
    return {"suppliers": suppliers, "grand": bare_totals[-1] if bare_totals else None,
            "generated": gen}


def validate_fred(rep):
    v = []
    sup_ok, sup_bad = 0, []
    grp_ok = grp_bad = 0
    for s in rep["suppliers"]:
        gs = [g["total"] for g in s["groups"] if g["total"] is not None]
        if s["total"] is not None and abs(s["total"] - sum(gs)) <= 0.02:
            sup_ok += 1
        else:
            sup_bad.append(s["name"])
        for g in s["groups"]:
            invs = [i["total"] for i in g["invoices"] if i["total"] is not None]
            if g["total"] is not None and abs(g["total"] - sum(invs)) <= 0.02:
                grp_ok += 1
            else:
                grp_bad += 1
    v.append(Verdict("V-FRED-SUP", not sup_bad, f"{sup_ok}/{sup_ok + len(sup_bad)} suppliers reconcile" + (f" off:{sup_bad}" if sup_bad else "")))
    v.append(Verdict("V-FRED-GRP", grp_bad == 0, f"{grp_ok}/{grp_ok + grp_bad} date groups reconcile"))
    st = [s["total"] for s in rep["suppliers"] if s["total"] is not None]
    g = rep["grand"]["total"] if rep["grand"] else None
    v.append(Verdict("V-FRED-GRAND", g is not None and abs(g - sum(st)) <= 0.02, f"grand={g} sum={sum(st):.2f}"))
    seen = set()
    dups = []
    for s in rep["suppliers"]:
        for gg in s["groups"]:
            for i in gg["invoices"]:
                k = (s["name"], i["number"])
                if k in seen:
                    dups.append(i["number"])
                seen.add(k)
    v.append(Verdict("V-FRED-DUP", not dups, f"{len(dups)} duplicate invoice numbers"))
    v.append(Verdict("V-DATE", to_date(rep["generated"]) is not None, f"generated={rep['generated']}"))
    return v


def process(path: Path, packs) -> dict:
    md, meta = load_doc(path)
    doc_type, class_why = classify(md)

    if doc_type == "fred_report":
        rep = parse_fred(meta["rows"])
        verdicts = validate_fred(rep)
        n_inv = sum(len(g["invoices"]) for s in rep["suppliers"] for g in s["groups"])
        return {
            "file": path.name, "pdf_type": meta["pdf_type"], "pdf_confidence": meta["pdf_confidence"],
            "doc_type": doc_type, "class_why": class_why, "vendor": None, "match_why": "internal report",
            "fred": rep, "fred_lines": n_inv,
            "fields": {},
            "verdicts": [(x.code, x.ok, x.detail) for x in verdicts],
            "status": "review" if any(not x.ok for x in verdicts) else "ok",
        }

    abn = find_abn(md)
    pack, match_why = match_vendor(md, abn, packs)

    fields = extract(md, pack) if pack else {}
    inv_d = to_date(fields["invoice_date"]) if fields.get("invoice_date") else None
    due = to_date(fields["due_date"]) if fields.get("due_date") else None
    due_src = "printed"
    if due is None and inv_d is not None and fields.get("terms_days"):
        due = inv_d + timedelta(days=int(fields["terms_days"]))
        due_src = f"terms+{fields['terms_days']}d"
    fields["_due_date"] = due

    verdicts = validate(doc_type, pack, fields, abn)
    failed = [x for x in verdicts if not x.ok]
    status = "review" if (failed or pack is None or doc_type == "other") else "ok"

    return {
        "file": path.name,
        "pdf_type": meta["pdf_type"],
        "pdf_confidence": meta["pdf_confidence"],
        "doc_type": doc_type,
        "class_why": class_why,
        "vendor": (pack or {}).get("id"),
        "match_why": match_why,
        "fields": {
            "supplier_abn": abn,
            "invoice_number": fields.get("invoice_number"),
            "ref_invoice": fields.get("ref_invoice"),
            "invoice_date": str(inv_d) if inv_d else fields.get("invoice_date"),
            "due_date": str(due) if due else None,
            "due_source": due_src if due else None,
            "ex_gst": to_money(fields.get("ex_gst") or ""),
            "gst": to_money(fields.get("gst") or ""),
            "inc_gst": to_money(fields.get("inc_gst") or ""),
            "currency": "AUD",
        },
        "verdicts": [(x.code, x.ok, x.detail) for x in verdicts],
        "status": status,
    }


def main(paths):
    packs = load_packs()
    docs = [Path(p) for p in paths] if paths else sorted(
        f for f in SAMPLES.iterdir() if f.suffix.lower() in (".pdf", ".ods"))
    for doc in docs:
        r = process(doc, packs)
        print("=" * 74)
        print(f"{r['file']}  [{r['status'].upper()}]  src={r['pdf_type']}({r['pdf_confidence']})")
        print(f"  classify : {r['doc_type']}  ({r['class_why']})")
        print(f"  vendor   : {r['vendor']}  ({r['match_why']})")
        if r["doc_type"] == "fred_report":
            rep = r["fred"]
            print(f"  generated: {rep['generated']}   suppliers: {len(rep['suppliers'])}   invoice lines: {r['fred_lines']}")
            for s in rep["suppliers"]:
                n = sum(len(g["invoices"]) for g in s["groups"])
                print(f"    {s['name']:<30} {n:>3} inv  total={s['total']:>10}  tax={s['tax']:>10}")
            if rep["grand"]:
                print(f"    {'GRAND TOTAL':<30} {'':>3}     total={rep['grand']['total']:>10}  tax={rep['grand']['tax']:>10}")
        else:
            for k, val in r["fields"].items():
                print(f"    {k:<14} {val}")
        print("  rail:")
        for code, ok, detail in r["verdicts"]:
            print(f"    {'PASS' if ok else 'FAIL'} {code:<12} {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
