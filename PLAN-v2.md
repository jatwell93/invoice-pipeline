# Invoice Tracker — Revised Plan (v3)

**Date:** 4 November 2026
**Supersedes:** PLAN.md rev. 2 (kept as the record of the n8n/cloud-extraction design)
**Driver:** Fusion factory trial concluded; real-document spike proved a simpler architecture

---

## 1. What changed and why

Three findings since rev. 2 collapse most of the original design's cost:

1. **Supplier documents are born-digital.** All four sample PDFs carry a clean text layer (SAP NetWeaver, Create!form, Telerik producers). The OCR-engine question that drove the Azure DI vs Gemini bake-off mostly evaporates — text extraction is local, free and deterministic. A working spike already extracts every key field from all four samples and the monthly Fred report, with a validation rail that self-checks its own parse.
2. **Extraction is a vendor-template problem, not an engine problem.** The supplier set is bounded (~50 suppliers; big-3 wholesalers = most volume). Per-vendor regex/parser maps ("vendor packs") are auditable data files, not code. A cheap LLM call covers template misses and new suppliers while packs accrete.
3. **The orchestration overhead was the cost.** The factory trial spent ~234M tokens to land 5/36 tasks, much of it on board-state reconciliation. A single Python service replaces n8n + cloud adapters + the bake-off harness.

**Operating constraints (owner-confirmed):**
- One owner, one machine, one entity per store. The owner is non-technical: day-to-day use must be "open a file / send an email", with no commands.
- Alerts go by email to the owner.
- Xero integration is later, not in scope. Dext may be replaced; the pay-run copies its layout only for familiarity.
- Real supplier documents stay out of git. Only redacted fixtures are committed.

## 2. Target architecture (single Python service)

```
watched folder (v1 dev) / invoices mailbox (IMAP poll, every N min)
        │
        ▼
Processing log (sqlite: msg+attachment id, file hash → state; idempotent)
        │
        ▼
pdf-inspector  →  pdf_type flag + markdown text
   (scan or "mixed" → review; ODS/XLSX → table parser)
        │
        ▼
Keyword rules (line-anchored) → doc class      [v1.1: Laya runs in shadow, §7]
 ledger classes:  invoice · credit_note · statement · fred_report
 never-ledger:    remittance · reminder · proforma · payment_evidence · other
 flags: link_fetch · body_only → review queue, not built yet
        │
        ▼
Vendor match (sender addr + ABN + aliases) → vendor pack (JSON: field anchors + regexes)
        │                                    └── no pack / field miss → LLM fallback
        ▼                                        (Gemini flash, regional) → still bad → review
Deterministic extraction → typed fields (Decimal / integer cents only)
        │
        ▼
Entity match (bill-to ABN / name → store)
        │
        ▼
Validation rail: ABN checksum · GST≈10% (supplier docs only — Fred rows
carry GST-free lines) · ex+gst=inc · credit sign+ref · date sanity ·
business-key dedup (tolerate Fred's "-2" multi-part suffixes)
        │
        ├── fail → Exceptions (owner review) + email alert
        ▼
Ledger (sqlite, source of truth) → generated xlsx views + document archive
```

**Spike evidence:** 4/4 PDFs classified and fully extracted; the API "ADJUSTMENT NOTE" decoy caught by rule order + negative-total rail; Fred report parses 9 suppliers / 161 lines and reconciles all declared totals.

**Stored per ledger row:** original file hash, extracted markdown, pack id + version, `extraction_method` (`pack` | `llm`), entity. This makes any row re-runnable after a pack fix without re-fetching mail.

**Confidence score (per ledger row):** `confidence` (0–100), `confidence_band` (High / Medium / Low) and `confidence_reasons` (short text). The score is computed from deterministic evidence, not from a model's self-report:

- extraction path: pack match scores highest; LLM fallback scores lower and is capped at Medium until the owner confirms it
- classification evidence: title-anchored rule match scores higher than a weaker or multi-rule match
- vendor identification: sender address + ABN scores higher than alias-only or unknown sender
- document quality: `text` scores higher than pdf-inspector `mixed`
- extraction completeness: every required field found by the pack, with no field-level fallback
- rail margin: all rail checks pass cleanly; near-misses (for example GST at the edge of tolerance, near-duplicate business key) subtract points
- v1.1: Laya/JEV shadow agreement adds or subtracts points once the comparison shows their confidence is calibrated

A failed rail check is never a low-confidence ledger row; it is an exception. Low confidence means "passed the checks on weaker evidence". Band thresholds are set from the corpus check: the Low band must contain the errors and near-misses, otherwise the weights are adjusted before go-live. The score and reasons are recomputed when a pack is fixed and the row is re-run.

**LLM fallback:** Gemini flash (australia-southeast1) for template misses and low-confidence extractions — cents/month at this volume. Output is untrusted and accepted only through the same validation rail. **LLM-extracted rows are flagged `unconfirmed` in the ledger and exceptions view until the owner confirms them or a pack is added.** On a successful fallback the service drafts a candidate pack for the owner to approve, so the fallback shrinks over time.

**Privacy:** document text stays local except when the LLM fallback runs; then the extracted text of that one document is sent to Gemini. Redact or accept this explicitly at pilot.

## 3. Payment evidence — email, not Telegram

Owner sends/forwards to the invoices mailbox with subject convention:

```
PAID <supplier> <total> [date] [invoice-or-statement ref]
```

plus an optional screenshot (archived as evidence, not parsed). Classification `payment_evidence` → Payments record.

- **The subject line is the data; the screenshot is the evidence.** Screenshots are images, so parsing them would reintroduce the OCR problem. A vision-model read of the screenshot to cross-check the typed amount is an optional later addition, flagged if it disagrees.
- **Matching:** supplier resolved through aliases (fuzzy, with unknown supplier → exception); total matched against, in order, an exact invoice total, a statement total, then a sum of open invoices. More than one candidate, or no candidate, → exception for the owner. The optional ref removes most ambiguity (same-amount invoices, one payment covering several).
- **Authentication:** the Telegram allowlist is replaced by sender checks. Accept `payment_evidence` only from the owner's address(es) with SPF/DKIM pass (`Authentication-Results` header); anything else becomes an exception.
- **Authority:** bank match remains authoritative. PAID emails are evidence and matching hints, never proof.

## 4. Reconciliation jobs (kept from rev. 2 — this is the actual product)

- **Statement reconciliation:** extract statement header + every line → match to ledger → five flags (*Reconciled to Statement / Invoice Direct from Supplier / Missing Invoice / Possible Credit / Possible Duplicate*) + balance equation per statement (opening + new − credits − payments = closing ±$0.01).
- **Fred cross-check:** monthly Completed Invoice Summary/Credit Note Details → supplier + invoice # + total vs ledger. Spike already parses the real report; adds `-N` suffix tolerance and `$0.00` lines to the matching rules. ~85% coverage → cross-check, not source of truth.
- **Pay-run sheet:** per entity (store), generated on the 1st + on demand, Dext layout (grouped by supplier; due date, all unpaid, last month's unpaid, recommended payment, Y/N + notes, statement flags). Each invoice line shows **Confidence** (score + band) and **Why** (reasons). Each supplier header shows its lowest-confidence line. Low rows are red, Medium amber, High unshaded. The recommended payment includes Low or `unconfirmed` rows only as a separate "check first" subtotal, so a payment is not recommended on weak evidence without the owner seeing it. Owner Y/N + notes are imported back into sqlite on the next run (explicit import step; never overwrite owner edits).
- **Bank matching (deferred, still planned):** monthly NAB CSV → three modes (DD → statement total, statement EFT → total, per-invoice). Depends on statement rec being live first.

## 5. Deliverable format and running it

- **sqlite is the ledger.** Ledger, exceptions and pay-run sheet are **Excel workbooks generated from it** (openpyxl) — the format the owner already works in. The owner never edits the ledger workbook directly; only the pay-run Y/N + notes columns are read back. The ledger and exceptions workbooks carry the same Confidence, Band and Why columns with conditional formatting (red/amber/green) and a default sort of lowest confidence first, so month-end review starts with the weakest rows. Colour is always paired with the band text, not used alone.
- Single-machine, single-user: no Sheets/Drive. Revisit only if multi-device access is requested.
- **Non-technical operation:** the service runs as a systemd timer; output workbooks land in a fixed folder the owner opens; "run pay-run now" is an email subject (`PAYRUN`) or a desktop shortcut, not a command.
- **Backups:** nightly copy of the sqlite file + archive to a second location (external disk or cloud folder). ≥5-yr retention cannot rest on one disk.

## 6. Scope — what was cut from rev. 2

| Dropped / deferred | Replacement |
|---|---|
| n8n stack, workflow-as-code, canonical round-trip | single Python service + systemd timer |
| Azure DI + Vertex bake-off, pluggable engine interface | vendor packs + pdf-inspector markdown; LLM fallback only |
| M4 harness (labeller, review pack, schema contract, report gen, memos) | corpus check = run the service over 20–30 owner-pulled docs, score in a sheet |
| Telegram bot | `PAID …` email + screenshot, with sender authentication |
| Link-fetch / body-only intake | classification *flags* → review queue; build when a real supplier needs it |
| VPS hosting | runs on the existing local machine; revisit at pilot |
| Workspace decision, EzzyBills comparison | deferred — only if extraction gate fails or mail volume demands |
| Xero | later |

Kept at full rigor: supplier master (aliases, ABNs, terms — now seeding the vendor packs), validation rail, statement reconciliation, pay-run sheet, exceptions queue, ≥5-yr retention via mailbox + archive + backup, owner-as-sole-reviewer.

## 7. Validation

- **Gate (replaces the per-field 95%):** on 20–30 docs one miss is already ~4%, so a percentage gate is noise. Gate on **zero silent errors**: every document is either correct in the ledger or lands in exceptions. 100% doc-class + credit/statement classification. Report the exception rate as the cost of the design; failures → vendor pack or rule fix, re-run.
- **Corpus check (run locally, see §12):** owner pulls 20–30 real docs (invoices across the supplier mix, ≥1 big-3 statement, credit notes, the monthly Fred ODS). Include deliberate decoys (credit notes titled like invoices, "statement" in boilerplate, remittance advice in payment text). Score each key field vs the doc face in a sheet.
- **Unit tests:** the spike's four samples + Fred report become **redacted** committed fixtures (names, ABNs, bank details replaced; layout kept). Real files stay in a git-ignored folder. Rail verdicts asserted per doc.
- **Live check:** two weeks of mailbox intake vs owner's manual list — every invoice in the ledger or in exceptions; none silent.

### v1.1 — Laya (or JEV) comparison

Goal: learn what a local typed-decision model adds over the keyword rules, without putting it on the critical path.

- **Design:** put classification behind one function, `classify(markdown) -> (class, confidence)`. v1 uses the rules. v1.1 runs Laya **in shadow** on every document: it logs its class and calibrated confidence, never writes the ledger. Rules stay authoritative until the comparison says otherwise.
- **Input:** page-1 markdown trimmed to Laya's 512-token context. Choice list ≤ ~10 doc classes. Vendor routing stays deterministic; optionally a second shadow task for unknown senders only.
- **Corpus:** the §7 corpus plus the decoys. The four spike docs are not enough; the rules already score 5/5 there, so the interesting cases are the collisions.
- **Measure, per document and per class:** accuracy vs owner-confirmed class; disagreement rate with rules; whether Laya's confidence separates its errors from its hits (calibration); how many docs the rules send to review that Laya would classify correctly; latency per document; install size (~1.7 GB ONNX) and setup effort on the owner's machine.
- **Decision rule (set before running):** promote Laya to arbiter only if it resolves rule collisions or review-queue docs correctly more often than it introduces errors, and the setup is tolerable for a non-technical machine. Otherwise keep rules and record the result.
- **JEV:** a typed-decision model in the same family as Laya (article: thinkfastgroup.com/articles/typesafe-jev-ai-accounting-for-operators). It runs as a second shadow classifier behind the same `classify()` interface and is scored on the same corpus and metrics, giving a three-way comparison: rules vs Laya vs JEV. Its install method, licence and runtime requirements are still to be checked before it is added.
- **Decoys are scored separately.** Report results on the decoy set on its own, because that is where the models can show a difference. Each decoy has an expected class and an expected Low/exception outcome. A decoy that lands in the ledger as High confidence is a failure.
- **Confidence check:** for every approach, compare confidence against correctness. A useful confidence score puts the wrong or ambiguous documents in the Low band.

## 8. Build order

1. `extract` — promote spike: source dispatch (pdf/ods/xlsx), classify, vendor packs, entity match, validation rail, LLM fallback stub. Input from a watched folder.
2. `ledger` — sqlite schema (Invoices, Statements, StatementLines, Payments, Exceptions) + xlsx view generator + archive writer + processing log.
0. `bootstrap` — new repo and privacy rails (§9). **needs-user:** NU-1 to NU-4.
1a. **needs-user:** NU-5 to NU-7 produce the shared-safe fixtures that step 1 needs.
3. `statements` — statement extraction + five-flag reconciliation + balance check. **needs-user:** blocked on a real big-3 statement, anonymised (NU-5, NU-7); request it first.
4. `ingest` — IMAP poll replaces the watched folder (idempotent per msg+attachment). **needs-user:** NU-10.
5. `payrun` — monthly pay-run sheet generator + owner-notes import.
6. `evidence` — PAID email convention + sender authentication → Payments. **needs-user:** NU-10 (sending addresses).
7. `ops` — systemd timer, email heartbeat alert if poll fails, nightly backup, owner runbook. **needs-user:** NU-12.
8. `v1.1` — Laya shadow classifier + comparison report (can start after step 1; independent of 3–7).

Steps 1–2 are the thin end-to-end path; 3 is the money feature; 4–7 complete the owner's monthly loop.

## 9. Repo bootstrap (new repo; Fusion repo archived)

The Fusion-era repo (`jatwell93/invoice-tracker`) is retired, not cleaned. The service starts in a new repo and folder with no history. Tasks tagged **needs-user** are in §13.

1. **Close out the old repo.** Scan the untracked files for the store name and other buyer details (a "trentham" search of the working tree and all history was already clean). Commit `pipeline/` as the spike record without `PLAN-v2.md`. Push `main`; do not force-push. Save a `git bundle --all` of the old repo first. Remove the Fusion worktrees and local `fusion/*` branches. Archive the GitHub repo or make it private. *(needs-user: NU-1)*
2. **Create the new repo and folder.** `git init`, no history. Add a short `CLAUDE.md` carrying the project context, since a new folder starts a new assistant project.
3. **Privacy rails before any real document touches the machine** (§12): `.gitignore` entries for the private documents folder, the output workbooks folder and `.venv*/`; a read-deny rule for the private folder in the assistant's settings; the leak-scan script from §12.4. *(needs-user: NU-2, NU-4)*
4. **Copy in only what carries over:** this plan as `PLAN.md`; `pipeline/spike.py` and `pipeline/vendors/` as the seed of the service package; redacted fixtures only; useful `research/` notes after a check that no real supplier data is in them; conventions adapted to Python. Do not copy `.fusion/`, the n8n stack, `workflows/`, the `KB-*` cards or the Node plan-citation tooling.
5. **Package the spike** as a `pyproject.toml` project with tests. Link to the old repo as a read-only reference.

## 13. Tasks that need the human (`needs-user`)

**Convention.** Any task that only the owner can do is tagged `needs-user` in the task list and the build order. When an assistant reaches one it stops, states exactly what is needed and how to know it is done, and does not substitute invented or placeholder data. A `needs-user` task that blocks others is listed with what it blocks. Each task records its done-check, so it can be closed without ambiguity.

| ID | Task | Done when | Blocks |
|---|---|---|---|
| NU-1 | Close out the old repo: run the §9 scan, push `main`, remove worktrees, archive or privatise the GitHub repo | Old repo pushed, archived, and the bundle saved | Repo bootstrap |
| NU-2 | Create the private documents folder outside the project, on an encrypted disk, owner-only permissions, and add the assistant read-deny rule for it | Folder exists; an assistant read of a test file in it is refused | Every real-document step |
| NU-3 | Choose the pilot store; name the big-3 wholesalers | Written down in the new repo's `CLAUDE.md` | Vendor packs, statements |
| NU-4 | Create the leak-scan deny-list (store name, buyer ABN, bank details, staff names, street, email domains, phone numbers), kept in the private folder | File exists; the scan script runs against it | Anything entering `fixtures/` |
| NU-5 | Download the sample into the private folder: about 50 invoices across the supplier mix, statements (at least one per big-3 wholesaler), adjustment notes and credit notes, the monthly Fred ODS | Files in the private folder; file list recorded without contents | Corpus check |
| NU-6 | **Exclude** every document containing patient or customer personal information (for example prescription or dispensing data) | Confirmed none are in the sample | NU-7, all sharing |
| NU-7 | Hand-redact or anonymise the documents that will be shared, per §12.3: replace buyer name, address and ABN, customer account numbers, BSB and bank account numbers, emails, phone numbers, staff names, logos and PDF metadata; keep supplier identity, layout, numbers, dates, lines and totals | Each shared file passes the §12.4 leak scan and a visual check, with the same fake value used for the same real value across all files | Fixtures, pack design |
| NU-8 | Pick 5–10 decoys (or approve the synthetic ones) | List agreed | v1.1 comparison, corpus check |
| NU-9 | Label the corpus: confirm the expected class and key fields for each document in the scoring sheet | Sheet complete | Gate decision |
| NU-10 | Provide the Gmail app password or OAuth, stored in the git-ignored secrets file; confirm the owner's PAID sending addresses | Secrets file populated; addresses listed | `ingest`, `evidence` |
| NU-11 | Confirm a paid, Australian-region Gemini tier and check its data-use terms; create the API credentials | Terms checked and noted; key stored in secrets | LLM fallback |
| NU-12 | Choose the backup target (external disk or cloud folder) | Target chosen and writable | `ops` |
| NU-13 | During the live check, confirm `unconfirmed` LLM rows and compare the ledger with the manual list for two weeks | Every invoice is in the ledger or in exceptions; none silent | Go-live |

## 10. Open inputs needed from owner

All of these are `needs-user` tasks; the full list with done-checks is §13.

- Which store pilots; names of the big-3 wholesalers (seed packs + statement layouts)
- 20–30 doc corpus incl. ≥1 real big-3 statement PDF (real files stay out of git)
- Gmail app password (or production-status OAuth) for the invoices mailbox
- Owner's sending address(es) for PAID emails
- Supplier sender roster as it grows (new sender → alias or pack)
- Which 5–10 deliberate decoys to include in the corpus (credit notes titled like invoices, statements mentioned in boilerplate, remittance wording in payment text, proformas, duplicated or multi-part invoice numbers)

## 11. Costs

Near-zero steady state: Gemini fallback ≪ A$1/mo at ~110 docs; everything else local. Optional later: VPS ~A$15/mo.

## 12. Privacy and data handling

**Principle:** share the minimum needed to build and verify the system. Real documents are processed by code on the owner's machine. AI assistants (Claude, Gemini and similar) work from anonymised or synthetic documents and from aggregate results.

### 12.1 Where data can leak

- **AI assistants:** any file an assistant reads, or any text pasted into a chat, is sent to its provider. Assistant session transcripts are also stored locally and indexed by session-search tools.
- **Git:** anything committed, including history.
- **Production LLM fallback (§2):** the extracted text of a document that misses its pack is sent to Gemini.
- **Logs and outputs:** error messages, test output and generated workbooks can contain real values.

### 12.2 Three tiers of data

| Tier | What | Where it lives | Who may read it |
|---|---|---|---|
| Private | Real documents as downloaded, real ledger, archive | A private folder outside the project directory, on an encrypted disk, with owner-only permissions | The service and the owner only. No assistant is pointed at it; add an explicit read-deny rule for that path in the assistant's settings |
| Shared-safe | Format-preserving anonymised documents (12.3) and synthetic decoys | `fixtures/` in the repo | Assistants and git |
| Aggregate | Scoreboards: per-document pass/fail, per-field hit/miss counts, confidence-band counts, error categories | Pasted into chat when needed | Assistants |

### 12.3 What to anonymise, and what to keep

Anonymising everything would defeat sampling: the vendor packs, the ABN rail, the classification rules and the reconciliation matching all depend on real formats. Anonymise by sensitivity, not wholesale.

| Keep as-is (needed, and public or low risk) | Replace with fake values of the same shape |
|---|---|
| Supplier name, supplier ABN (public on the ABN register), layout, labels, headings, fonts | Buyer name, store address, buyer ABN, customer account numbers |
| Invoice and statement numbers, dates, due dates, payment terms | Bank BSB and account numbers, remittance emails, phone numbers, person names |
| Line descriptions, quantities, unit prices, GST, totals (arithmetic must stay consistent) | Logos or images that identify the buyer; PDF metadata (author, creator, title) |

- **Format-preserving, not tokens.** A replacement like `[PIVA_1]` breaks regex anchors and the ABN checksum check. Use fake values with the same shape: same digit count and separators, and a valid-checksum fake ABN where an ABN is replaced.
- **Consistent mapping across the whole set.** The same real buyer, invoice number or amount must map to the same fake value in every document, so statements, invoices, PAID emails and the Fred report still reconcile against each other.
- **Exclude entirely** any document that contains patient or customer personal information (for example prescription or dispensing data). Do not anonymise those; leave them out of the sample.
- **Decoys:** build most from anonymised documents by editing them (credit note titled like an invoice, "statement" in boilerplate, proforma, duplicate or `-2` suffix numbers). Real adjustment notes are only needed for layout.

### 12.4 Checks before anything enters the repo or a chat

1. Run the anonymiser on a copy in the private folder.
2. Read every output (extracted text and a visual check). Image content such as logos is not covered by text extraction.
3. Run a leak scan: grep the output for a private deny-list (store name, buyer ABN, bank details, staff names, street, email domains, phone numbers). The deny-list file lives in the private folder, not in the repo.
4. Check PDF metadata and embedded images are clean.
5. Only then copy to `fixtures/`. Track provenance in `fixtures/manifest.json` as fixture id, supplier, document type and anonymiser version, without any real values.

### 12.5 Anonymiser requirements

The current local anonymiser (`example_3_anonimizzato.pdf`) is a start, but on inspection:

- it replaces values with tokens, which breaks the ABN rail and anchors (use format-preserving values);
- it labelled the BSB as `ZIPCODE`, and the supplier ABN as an Italian VAT number (`PIVA`), so the detectors are Italian-tuned;
- the bank account number and an embedded image were still present in the output I could see;
- it replaces supplier details that are public and needed.

Required: an Australian-aware profile (ABN, BSB, account number, phone, address, email), a keep-list for supplier identity, consistent mapping across documents, and an output test: the leak scan in 12.4 must pass.

### 12.6 How the sample is used

- **Verification runs locally.** The service is run on the real sample in the private folder; the owner or the service produces the scoreboard. When a document fails, the failure is reproduced on its anonymised version or a minimal redacted excerpt, and the pack is fixed there.
- **Sample size.** Pack design needs one to two anonymised documents per supplier layout, one anonymised statement per big-3 wholesaler, a few anonymised decoys, and the Fred report. The larger real sample (about 50 invoices) is for local scoring only.
- **Production fallback.** Use a paid or enterprise Gemini tier in an Australian region, with data-use terms checked to confirm prompts are not retained or used for training. Do not use a free tier for real documents. Send only the extracted text of the failing document, with buyer details masked where practical.
- **Retention.** Keep real documents only as long as the archive requirement needs. Delete the downloaded test copies when the corpus check is finished.

---

*Spike evidence: `pipeline/spike.py` + `pipeline/vendors/` — 4/4 PDFs extracted, credit-note decoy caught, Fred report reconciles to the cent. Prior analysis and gate criteria: PLAN.md §6 (retained as targets, measured by the corpus check instead of a bake-off harness).*
