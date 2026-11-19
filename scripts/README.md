# Scripts

Tools for turning real supplier documents into safe, redacted fixtures. Real documents stay in `~/invoice-private/`. Nothing in `fixtures/redacted/` is ever committed, but files there are visible to the agent, so every file must pass the leak scan first.

## The workflow

1. Keep the original documents in `~/invoice-private/originals` (or any private folder).
2. Make sure `~/invoice-private/leak-deny-list.txt` lists everything private (see "The deny-list").
3. Redact: `python3 scripts/redact_pdf.py ~/invoice-private/originals fixtures/redacted/invoices`
4. Scan: `python3 scripts/leak_scan.py fixtures/redacted`
5. Look at every `[check]` file by eye, especially logos and images.

For spreadsheets (`.xlsx`, `.ods`), edit the values by hand, then run `strip_metadata.sh` (below). `redact_pdf.py` handles PDFs only.

## One-time setup

- PDF tools for the scan: `sudo apt install poppler-utils`
- Metadata tools: `sudo apt install libimage-exiftool-perl qpdf`
- Redaction library, inside the project virtual environment, run from the repo folder:

```
python3 -m venv .venv
source .venv/bin/activate
pip install pymupdf
```

Run `source .venv/bin/activate` again in each new terminal before `redact_pdf.py` or `redact_diagnose.py`. `leak_scan.py` needs no virtual environment.

## The deny-list

`~/invoice-private/leak-deny-list.txt`, one private item per line: owner and staff names, the store name and address, buyer ABN, customer account numbers, bank account numbers. Lines starting with `#` are ignored. This file stays outside the repo.

- **Matching is plain text, ignoring case.** A short entry matches everywhere it appears, including inside prices and other numbers. Do not list short or common values such as a 3-digit number. Real account numbers (6 or more digits) are safe.
- **Spelling matters.** List each spelling, for example an ABN with and without spaces.
- **Line numbers change when you edit the list.** All tools report deny-list line numbers, never the terms. If you delete or insert a line, every later number shifts, so numbers from an earlier run no longer match.
- **Duplicates differing only in capitalisation are redundant.** Matching already ignores case.

## redact_pdf.py

Deletes every deny-list term from PDFs and writes a fake value of the same shape in its place. Digits become other digits, letters become other letters of the same case, and spaces and punctuation stay, so layout and field formats are kept. A term always gets the same fake value, so a name on ten invoices becomes one consistent fake name, and no fake contains any deny-list term. It also removes metadata, hidden text, attachments, links and all annotations (notes and comments can hold private text that page-text checks never see).

```
python3 scripts/redact_pdf.py SRC_DIR DEST_DIR
```

- Uses the same deny-list as the scan. Add a line for anything you want replaced.
- Creates `~/invoice-private/redact-salt` on first run (owner-only permissions). The salt makes the fake values unguessable. Keep it in your backup so later runs give the same fakes.
- Writes a file only if no deny-list term can still be found in the result. A `[FAIL]` line means the file was not written. It shows `original` (occurrences in the source), `marked` (occurrences found and redacted) and `remaining` (occurrences left), as numbers only.
- Skips files already in the destination. To rebuild, move the old outputs out of the destination first.
- A file can be refused if its PDF structure defeats text removal. In testing, 6 of about 60 files were. For those, redact by hand in a PDF editor with a real "apply redactions" step, put the result in the source folder, and run again, or leave the file out.
- Text inside images (logos, scanned pages) is not searched. The `images` count tells you where to look.

## leak_scan.py

Checks every file under a folder (default `fixtures/redacted`) for leftover private details.

```
python3 scripts/leak_scan.py [FOLDER] [--deny-list FILE]
```

- `[FAIL]` means a deny-list term is still in the file. Fix it before showing the file to the agent. The line shows the deny-list line number, where it was found (`name`, `text` or `meta`) and how often.
- `[check]` means look by eye. It lists counts of emails, phone-like numbers, BSB-like numbers, valid ABNs and images. Fake values from `redact_pdf.py` also appear here, because a fake phone still looks like a phone. Emails and ABNs should be the supplier's or fake.
- `[ok]` means nothing found.
- The summary at the end gives file counts, total findings and which deny-list lines hit most.
- Output holds counts, deny-list line numbers and metadata field names only, so it is safe to paste into a chat.
- It checks text, file names and the free-text document properties (Title, Subject, Keywords, Author, Creator, Producer). It cannot see text inside images or inside annotations, so a passing scan is not a visual check.

## strip_metadata.sh

Copies PDFs, `.xlsx` and `.ods` files to a new folder with author, company, title and other metadata removed. Originals are never changed. Existing files in the destination are skipped.

```
scripts/strip_metadata.sh SRC_DIR DEST_DIR
```

This removes metadata only. A black box drawn over text does not remove the text underneath. To test a PDF, open it, select the boxed area and copy. If text appears, the file needs `redact_pdf.py`.

## redact_diagnose.py

For a file that `redact_pdf.py` refuses. It explains why without printing any text.

```
python3 scripts/redact_diagnose.py FILE.pdf [--lines 4,12]
python3 scripts/redact_diagnose.py FILE.pdf --try-redact
```

- The first form shows page structure (boxes, annotation kinds, font kinds) and, for each deny-list line found in the page text, whether the search can locate it.
- `--try-redact` redacts the file in memory with several removal settings and reports what remains, with the position of each leftover occurrence and shapes (`A` upper, `a` lower, `9` digit) of the text at that spot before and after.
- Output is safe to paste, but shapes reveal word lengths and capitalisation.
