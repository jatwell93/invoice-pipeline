# Scripts

## leak_scan.py

Checks redacted fixtures for leftover private details before they are committed.

One-time setup:

1. Install poppler (gives the PDF tools): `sudo apt install poppler-utils`
2. Create `~/invoice-private/leak-deny-list.txt`. Put one private item per line: owner and staff names, the store name and address, buyer ABN, customer account numbers, bank account numbers. Lines starting with `#` are ignored. This file stays outside the repo.

Run it from the repo folder:

```
python3 scripts/leak_scan.py
```

To scan a different folder or deny-list:

```
python3 scripts/leak_scan.py some/folder --deny-list /path/to/list.txt
```

Reading the result:

- `[FAIL]` means a deny-list term, phone number or BSB-like number was found. Fix the file and run again. The output shows deny-list line numbers, never the term itself, so it is safe to paste into a chat.
- `[check]` means look by eye: emails and ABNs should be the supplier's only, and any images should show no buyer details.
- `[ok]` means nothing found.

Run it every time a file is added to `fixtures/redacted/`. The commit is clean only when no line says `FAIL` and every `check` has been looked at.
