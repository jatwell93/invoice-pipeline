# Invoice Pipeline

A single Python service that reads supplier invoices and statements from a mailbox, extracts the key fields, checks them, keeps a sqlite ledger, and produces Excel workbooks and a monthly pay-run sheet for one owner on one machine. The plan is `PLAN.md`. Read it before changing anything. It replaces an earlier n8n/Fusion design that is archived in the old `invoice-tracker` repo and must not be copied from.

## Privacy rules (non-negotiable)

- Real supplier documents, the real ledger and the archive live in `~/invoice-private/`, outside this repo. Never read, open, list the contents of, copy or commit anything from that folder. If a task seems to need a real document, stop and ask the owner for a redacted file or an aggregate scoreboard instead.
- Only redacted or synthetic files may go in `fixtures/redacted/`, and only after `python3 scripts/leak_scan.py` passes. Never commit real names, buyer ABNs, addresses, bank details, emails, phone numbers or staff names. Supplier names and supplier ABNs are public and may stay.
- Never paste real document content into a chat or an LLM call. The only production LLM call is the extraction fallback described in PLAN.md section 2, and it needs the owner's confirmation of a paid Australian-region tier first.
- Before adding any file under `fixtures/`, run the leak scan from PLAN.md section 12.4 against the deny-list kept in the private folder.
- `.gitignore` blocks `*.pdf`, `*.xlsx`, `*.ods`, `*.csv` and all of `fixtures/redacted/`. Redacted fixtures stay on this machine for the agent to read but are never committed. Do not force-add them.

## `needs-user` tasks

Some tasks only the owner can do: downloading and redacting documents, creating credentials, choosing a backup target, confirming rows. PLAN.md section 13 lists them as NU-1 to NU-15 with a done-check each. When you reach one, stop, state exactly what is needed and how you will know it is done, and do not substitute invented or placeholder data.

## Working rules

- The ledger is sqlite. Excel workbooks are generated views. Money is `Decimal` or integer cents, never float.
- A failed validation rail check is an exception, never a ledger row. Low confidence means the row passed the checks on weaker evidence.
- Vendor packs are JSON data files, not code. Add a supplier by adding a pack.
- Build in the order in PLAN.md section 8. Keep the thin path (extract, then ledger) working before adding more.
- The owner is non-technical. Anything they run daily must be a file they open or an email they send, not a command.

## Open items to resolve early

- Pilot store and the three big wholesalers (NU-3).
