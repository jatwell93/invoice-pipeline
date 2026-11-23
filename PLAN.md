# Invoice Tracker — Revised Plan (v4)

**Date:** 24 November 2026
**Supersedes:** PLAN.md rev. 3; rev. 2 remains the record of the n8n/cloud-extraction design
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
- Real supplier documents stay out of git. Redacted real-layout fixtures stay out of git too: they live in `fixtures/redacted/` on the owner's machine and are covered by the backup. Synthetic fixtures contain no real document content and are committed so CI can defend the core behaviour.

## 2. Target architecture (single Python service)

```
watched folder (v1 dev) / invoices mailbox (IMAP poll, every N min)
        │
        ▼
Processing log (sqlite: msg+attachment id, file hash → state; idempotent)
 states: discovered → archived → ledgered | non_ledger | exception   (retryable_failure = in flight, retried)
        │
        ▼
pdf-inspector  →  pdf_type flag + markdown text
   (text layer usable → continue; "mixed" with usable text → continue, flagged;
    no usable text layer → local OCR stage, §2 OCR; ODS/XLSX → table parser)
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
business-key dedup: entity + supplier + normalised invoice number
(same key with a changed total → exception; tolerate Fred's "-2" multi-part suffixes)
        │
        ├── fail → Exceptions (owner review) + email alert
        ▼
Ledger (sqlite, source of truth) → generated xlsx views + document archive
```

**Spike evidence:** 4/4 PDFs classified and fully extracted; the API "ADJUSTMENT NOTE" decoy caught by rule order + negative-total rail; Fred report parses 9 suppliers / 161 lines and reconciles all declared totals.

**Stored per ledger row:** original file hash, extracted markdown, pack id + version, `extraction_method` (`pack` | `llm`), entity. This makes any row re-runnable after a pack fix without re-fetching mail. Owner Y/N and notes are keyed to the business key, not an extraction attempt, so a re-run does not lose them. The promoted code replaces the spike's float money parsing with `Decimal` or integer cents, and every vendor pack gains an explicit version.

**Processing and recovery:** each attachment moves from `discovered` to `archived`, then exactly one terminal state: `ledgered`, `non_ledger` (classified as a statement, remittance, reminder, proforma, `payment_evidence` or other never-ledger class, and handled by its own path), or `exception`. `retryable_failure` is a temporary state that is retried until it becomes one of those three. State transitions and ledger writes are transactional. On restart, the service retries non-terminal and retryable work from the archive; message/attachment identity, file hash and business-key constraints prevent a crash between archive and ledger writes from losing or duplicating a document. Per poll, record counts for messages seen, eligible attachments found, documents archived, ledger rows written, non-ledger documents, exceptions and retryable failures. Eligible attachments must equal `ledgered + non_ledger + exception` once no retryable failures remain. Logs and alert emails use document IDs and safe error categories only, never extracted text or document content.

**Confidence score (per ledger row):** `confidence` (0–100), `confidence_band` (High / Medium / Low) and `confidence_reasons` (short text). The score is computed from deterministic evidence, not from a model's self-report:

- extraction path: pack match scores highest; LLM fallback scores lower and is capped at Medium until the owner confirms it
- text source: a native text layer scores highest; OCR text is capped at Medium until the owner confirms the row, and the OCR engine's per-line scores lower the score further when any key field comes from a low-scoring line
- classification evidence: title-anchored rule match scores higher than a weaker or multi-rule match
- vendor identification: sender address + ABN scores higher than alias-only or unknown sender
- document quality: `text` scores higher than pdf-inspector `mixed`
- extraction completeness: every required field found by the pack, with no field-level fallback
- rail margin: all rail checks pass cleanly; near-misses (for example GST at the edge of tolerance, near-duplicate business key) subtract points
- v1.1: Laya/JEV shadow agreement adds or subtracts points once the comparison shows their confidence is calibrated

A failed rail check is never a low-confidence ledger row; it is an exception. Low confidence means "passed the checks on weaker evidence". Band thresholds are set from the corpus check: the Low band must contain the errors and near-misses, otherwise the weights are adjusted before go-live. The score and reasons are recomputed when a pack is fixed and the row is re-run.

**LLM fallback:** Gemini flash (australia-southeast1) for template misses and low-confidence extractions — cents/month at this volume. Output is untrusted and accepted only through the same validation rail. **LLM-extracted rows are flagged `unconfirmed` in the ledger and exceptions view until the owner confirms them or a pack is added.** On a successful fallback the service drafts a candidate pack for the owner to approve, so the fallback shrinks over time.

**OCR stage (image-only PDFs, after the native-text thin path):** one main supplier sends invoices as image-only PDFs, roughly 10–15% of volume. Until NU-14 and the §7 engine comparison are complete, image-only documents go to exceptions without blocking native-text go-live. The images are clean renders of the same layout as the supplier's text PDFs, with no scan degradation, so OCR accuracy should be high once enabled.

- **When it runs:** only when pdf-inspector finds no usable text layer. Documents with a usable text layer never go through OCR, including `mixed` ones such as `example_1`.
- **Engine:** local only, so nothing leaves the machine. Candidates are PaddleOCR (`PaddleOCR().predict()` returns `rec_texts` and `rec_scores`; needs the `paddlepaddle` runtime and a first-run model download) and Tesseract (lighter to install). v1 ships one of them behind a single `ocr(image) -> lines + scores` function, chosen by the comparison in §7.
- **Output:** the OCR text is turned into the same markdown shape as the text path, then goes through the same vendor pack, entity match and validation rail. Packs for OCR-only suppliers use anchors tolerant of OCR confusions (`O`/`0`, `l`/`1`, `S`/`5`, stray spaces in numbers).
- **Safety net:** the arithmetic rail (ex + GST = inc, line sum = total) and the ABN checksum are the checks that catch a misread digit. An OCR-path row that fails any check is an exception, never a ledger row.
- **Flags:** each row stores `text_source` (`native` | `ocr`) and the OCR engine and version, next to `extraction_method`. The owner sees `OCR` in the ledger and pay-run alongside the confidence band.
- **Owner confirmation:** OCR rows stay `unconfirmed` (capped at Medium) until confirmed. Once the supplier has a measured clean record, the owner may choose to lift the cap for that supplier; this is a deliberate setting, never automatic.
- **Not used:** sending the image to a cloud vision model. It would put buyer details outside the machine, so it is excluded unless the owner decides otherwise after §12 review.

**Privacy:** document text stays local except when the LLM fallback runs; then the extracted text of that one document is sent to Gemini. Redact or accept this explicitly at pilot.

## 3. Payment evidence — email, not Telegram

Owner sends/forwards to the invoices mailbox with subject convention:

```
PAID <supplier> <total> [date] [invoice-or-statement ref]
```

plus an optional screenshot (archived as evidence, not parsed). Classification `payment_evidence` → Payments record.

- **The subject line is the data; the screenshot is the evidence.** Screenshots are images, so parsing them would reintroduce the OCR problem. A vision-model read of the screenshot to cross-check the typed amount is an optional later addition, flagged if it disagrees.
- **Matching:** supplier resolved through aliases (fuzzy, with unknown supplier → exception); total matched against, in order, an exact invoice total, a statement total, then a sum of open invoices. More than one candidate, or no candidate, → exception for the owner. The optional ref removes most ambiguity (same-amount invoices, one payment covering several).
- **Authentication:** the Telegram allowlist is replaced by sender checks. Accept `payment_evidence` only from the owner's address(es) with SPF/DKIM pass in the `Authentication-Results` header added by the receiving mailbox provider. Never trust a sender-supplied or forwarded copy of that header; anything else becomes an exception.
- **Lifecycle:** an invoice payment state is `unpaid`, `owner-evidenced`, `bank-confirmed`, `partial`, or `disputed`. A PAID email may move a matched invoice to `owner-evidenced`; only allocated bank transactions move it to `bank-confirmed` or `partial`. Ambiguous, reversed or conflicting evidence becomes `disputed`. Payments may allocate across multiple invoices, and an invoice may receive multiple allocations.
- **Authority:** bank match remains authoritative. PAID emails are evidence and matching hints, never proof.

## 4. Reconciliation jobs (kept from rev. 2 — this is the actual product)

- **Statement reconciliation:** extract statement header + every line → match to ledger → five flags (*Reconciled to Statement / Invoice Direct from Supplier / Missing Invoice / Possible Credit / Possible Duplicate*) + balance equation per statement (opening + new − credits − payments = closing ±$0.01).
- **Fred cross-check:** monthly Completed Invoice Summary/Credit Note Details → supplier + invoice # + total vs ledger. Spike already parses the real report; adds `-N` suffix tolerance and `$0.00` lines to the matching rules. ~85% coverage → cross-check, not source of truth. Fred places each document in the month of its **invoice date**, not its due date or terms (an invoice dated the 17th with end-of-month terms appears under the 17th). The cut-off is therefore the invoice date. The output also records received date, so an invoice dated in the report month but received after the report ran is reason-coded `not yet received` rather than treated as missing. Every variance receives one reason: missing invoice, not yet received, amount mismatch, credit mismatch, possible duplicate, supplier mismatch, split `-N` line, or unresolved.
- **Bank matching (required before pay-run):** import the monthly NAB CSV (the parser is built and tested against a redacted sample, NU-16) and support the two pilot modes: exact per-invoice amount/reference and one payment allocated across a selected set of open invoices. Direct debits, statement-total matching, reversals and ambiguous candidates go to exceptions until evidence justifies another deterministic mode. Bank transaction identity is account + posted date + amount + bank reference + a per-file occurrence number, so two identical same-day payments stay distinct and re-importing the same file adds nothing. Imported transactions are never silently reallocated.
- **Pay-run sheet:** per entity (store), generated on the 1st + on demand, Dext layout (grouped by supplier; due date, all unpaid, last month's unpaid, recommended payment, Y/N + notes, statement flags). Each workbook has a unique immutable pay-run ID; import is accepted only for the latest open run with that exact ID, otherwise it is rejected as stale. Each invoice line shows **Confidence** (score + band) and **Why** (reasons). Each supplier header shows its lowest-confidence line. Low rows are red, Medium amber, High unshaded. Low, `unconfirmed`, duplicate-suspected and disputed rows are excluded from the normal recommended total and shown in a separate "check first" subtotal. `owner-evidenced` rows (owner says paid, bank not yet confirmed) are not payment candidates: they are listed separately as "paid, awaiting bank" and counted in neither total. Owner Y/N + notes are imported back into sqlite on the next run (explicit import step; never overwrite owner edits).

## 5. Deliverable format and running it

- **sqlite is the ledger.** Ledger, exceptions and pay-run sheet are **Excel workbooks generated from it** (openpyxl) — the format the owner already works in. The owner never edits the ledger workbook directly; only the pay-run Y/N + notes columns are read back. Exceptions store their created time and expose their age; no heavier severity or owner-decision workflow is required. The ledger and exceptions workbooks carry the same Confidence, Band and Why columns with conditional formatting (red/amber/green) and a default sort of lowest confidence first, so month-end review starts with the weakest rows. Colour is always paired with the band text, not used alone.
- Single-machine, single-user: no Sheets/Drive. Revisit only if multi-device access is requested.
- **Non-technical operation:** the service runs as a systemd timer; output workbooks land in a fixed folder the owner opens; "run pay-run now" is an email subject (`PAYRUN`) or a desktop shortcut, not a command.
- **Backups:** nightly consistent SQLite snapshot using the SQLite backup API or `VACUUM INTO`, plus the archive and required configuration, to a second location (external disk or encrypted cloud folder). Retain the records and documents required for ≥5 years with a documented rotation; alert the owner when a backup fails and perform a recorded restore test at least quarterly. Recovery target: restore last night's snapshot and re-poll at most one day of mailbox data.
- **Monitoring:** send a daily positive digest with last successful poll, attachment disposition counts, unresolved exception count and oldest exception age. A missing digest is the alarm. An optional external dead-man ping may carry only an alive timestamp and no document content.
- **Secrets:** v1 uses a Gmail app password in a git-ignored owner-only file (`0600` permissions). Record setup and rotation in the runbook and rotate it after suspected exposure or mailbox/security changes.

## 6. Scope — what was cut from rev. 2

| Dropped / deferred | Replacement |
|---|---|
| n8n stack, workflow-as-code, canonical round-trip | single Python service + systemd timer |
| Azure DI + Vertex bake-off, pluggable engine interface | vendor packs + pdf-inspector markdown; LLM fallback only |
| M4 harness (labeller, review pack, schema contract, report gen, memos) | corpus check = run the service over the ~50-document acceptance corpus, score in a sheet |
| Telegram bot | `PAID …` email + screenshot, with sender authentication |
| Link-fetch / body-only intake | classification *flags* → review queue; build when a real supplier needs it |
| VPS hosting | runs on the existing local machine; revisit at pilot |
| Workspace decision, EzzyBills comparison | deferred — only if extraction gate fails or mail volume demands |
| Xero | later |

Kept at full rigor: supplier master (aliases, ABNs, terms — now seeding the vendor packs), validation rail, statement reconciliation, pay-run sheet, exceptions queue, ≥5-yr retention via mailbox + archive + backup, owner-as-sole-reviewer.

## 7. Validation

- **Gate:** use one frozen local acceptance corpus of about 50 documents (the manifest is the definition), selected by coverage rather than a percentage alone: every pilot supplier layout; at least one statement from each big-3 wholesaler; invoices, credit/adjustment notes and the monthly Fred ODS; image-only documents when OCR is evaluated; and 5–10 deliberate decoys. Gate on **zero silent errors**: every eligible attachment is either correct in the ledger, correctly classified as non-ledger, or in exceptions, with 100% invoice/credit/statement classification. The per-poll counts for eligible attachments must equal `ledgered + non_ledger + exception`, and no retryable failure may remain at the gate. Report the exception rate as the operating cost; failures → vendor pack or rule fix, then re-run.
- **Corpus check (run locally, see §12):** score each key field against the document face in a sheet. There is one corpus, not 50 invoices plus another set: enough invoices to cover every pilot layout, one statement per big-3 wholesaler, representative credits/adjustments, one Fred report and the deliberate decoys. If full layout coverage needs more than 50, the manifest grows; it is frozen before the acceptance run. A supplier without a pack is routed to exceptions and listed as unsupported at go-live.
- **Automated tests:** committed synthetic fixtures defend classification, validation, deduplication, ledger and reconciliation contracts in CI. Redacted real-layout fixtures remain git-ignored in `fixtures/redacted/`, pass `scripts/leak_scan.py`, metadata/image checks and recorded visual review before local use. Tests that specifically need local fixtures may skip clearly, but the equivalent core contract must remain covered by synthetic CI fixtures.
- **End-to-end matrix:** exercise the same invoice attached twice; the same invoice regenerated with different bytes; the same invoice number from two suppliers; a changed total under an existing business key; partial and combined payments; one credit applied to several invoices; a late invoice after month close; a stale pay-run import; and a crash after archiving followed by retry. Also cover corrupt, encrypted, unsupported and multi-attachment inputs as exception/disposition cases.
- **Go-live check:** run mailbox intake against the owner's manual list for at least two weeks **and through one complete month-end Fred reconciliation, NAB import and pay-run cycle**. Every eligible attachment must have one terminal disposition; there must be no silent miss, duplicate payable row or unresolved stale import. The owner confirms all `unconfirmed` rows.

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

### OCR engine comparison (v1 decision)

Choose the OCR engine on the image-only supplier's real documents, run locally.

- **Corpus:** at least 10 image-only invoices from that supplier, spanning different totals, line counts and any credit notes or statements they send as images.
- **Measure per engine:** key-field exact-match (invoice number, date, ABN, ex-GST, GST, total); digit-level misreads; how often the arithmetic rail rejects a misread; how often a wrong value passes the rail (this must be zero); run time per document; install size and setup effort on the owner's machine.
- **Decision rule (set before running):** pick the engine with zero rail-passing wrong values on the corpus. If both pass, pick the one that is easier to install and run. If neither does, those documents go to exceptions for manual entry and the plan is revisited.
- **Fallback to native text:** if the supplier can be asked to send the original PDF with a text layer, that removes the OCR path for them entirely. This is a `needs-user` request (NU-15), not a dependency.

## 8. Build order

Bootstrap and privacy rails are complete; §9 remains as their record. Owner-supplied inputs retain their `needs-user` gates and are requested before the step they block.

1. `extract` — promote the native-text spike: source dispatch (PDF/ODS/XLSX), classify, versioned vendor packs, entity match, validation rail and LLM fallback stub. Input comes from a watched folder. Image-only documents go to exceptions for now. **needs-user:** NU-3, NU-5 to NU-9 for pilot coverage and acceptance fixtures.
2. `ledger` — SQLite schema (Invoices, Statements, StatementLines, Payments, PaymentAllocations, Exceptions) + xlsx view generator + archive writer + transactional processing states and crash recovery.
3. `statements` — statement extraction, five-flag reconciliation, balance check and reason-coded Fred month-end variances. **needs-user:** NU-5 and NU-7 for one anonymised statement per big-3 wholesaler.
4. `ingest` — IMAP poll replaces the watched folder; idempotent per message + attachment, with disposition counts. **needs-user:** NU-10.
5. `bank` — minimal NAB CSV import, exact per-invoice matching and selected multi-invoice allocation; ambiguous rows become exceptions. **needs-user:** NU-16.
6. `payrun` — monthly pay-run generator, immutable run ID, stale-import rejection and owner Y/N + notes import.
7. `evidence` — PAID email convention and receiving-provider authentication checks → owner-evidenced Payments. **needs-user:** NU-10.
8. `ocr` — choose and add the local OCR engine through the §7 comparison; until then image-only files remain exceptions. **needs-user:** NU-14; NU-15 may retire this path for the supplier.
9. `ops` — systemd timer, daily positive digest, consistent nightly backup, failed-backup alert, restore test and owner runbook. **needs-user:** NU-12.
10. `v1.1` — Laya shadow classifier + comparison report; may start after step 1 and remains outside the v1 critical path.

Steps 1–2 are the thin end-to-end path. Steps 3–7 complete the authoritative monthly payment loop before pay-run go-live; steps 8–9 add input coverage and unattended operation.

## 9. Repo bootstrap (new repo; Fusion repo archived)

The Fusion-era repo (`jatwell93/invoice-tracker`) is retired, not cleaned. The service starts in a new repo and folder with no history. Tasks tagged **needs-user** are in §13.

1. **Close out the old repo.** Scan the untracked files for the store name and other buyer details (a "trentham" search of the working tree and all history was already clean). Commit `pipeline/` as the spike record without `PLAN-v2.md`. Push `main`; do not force-push. Save a `git bundle --all` of the old repo first. Remove the Fusion worktrees and local `fusion/*` branches. Archive the GitHub repo or make it private. *(needs-user: NU-1)*
2. **Create the new repo and folder.** `git init`, no history. Add a short `CLAUDE.md` carrying the project context, since a new folder starts a new assistant project.
3. **Privacy rails before any real document touches the machine** (§12): `.gitignore` entries for the private documents folder, the output workbooks folder and `.venv*/`; a read-deny rule for the private folder in the assistant's settings; the leak-scan script from §12.4. *(needs-user: NU-2, NU-4)*
4. **Copy in only what carries over:** this plan as `PLAN.md`; `pipeline/spike.py` and `pipeline/vendors/` as the seed of the service package; committed synthetic fixtures and local-only redacted fixtures; useful `research/` notes after a check that no real supplier data is in them; conventions adapted to Python. Do not copy `.fusion/`, the n8n stack, `workflows/`, the `KB-*` cards or the Node plan-citation tooling.
5. **Package the spike** as a `pyproject.toml` project with tests. Link to the old repo as a read-only reference.

## 13. Tasks that need the human (`needs-user`)

**Convention.** Any task that only the owner can do is tagged `needs-user` in the task list and the build order. When an assistant reaches one it stops, states exactly what is needed and how to know it is done, and does not substitute invented or placeholder data. A `needs-user` task that blocks others is listed with what it blocks. Each task records its done-check, so it can be closed without ambiguity.

| ID | Task | Done when | Blocks |
|---|---|---|---|
| NU-1 | Close out the old repo: run the §9 scan, push `main`, remove worktrees, archive or privatise the GitHub repo | Old repo pushed, archived, and the bundle saved | Repo bootstrap |
| NU-2 | Create the private documents folder outside the project, on an encrypted disk, owner-only permissions, and add the assistant read-deny rule for it | Folder exists; an assistant read of a test file in it is refused | Every real-document step |
| NU-3 | Choose the pilot store; name the big-3 wholesalers | Written down in the new repo's `CLAUDE.md` | Vendor packs, statements |
| NU-4 | Create the leak-scan deny-list (store name, buyer ABN, bank details, staff names, street, email domains, phone numbers), kept in the private folder | File exists; the scan script runs against it | Anything entering `fixtures/` |
| NU-5 | Assemble the acceptance corpus (about 50 documents) in the private folder: enough invoices to cover every pilot supplier layout, at least one statement per big-3 wholesaler, adjustment/credit notes, the monthly Fred ODS and the agreed decoys | Corpus manifest is frozen, listing each entry by safe ID and document class, with every pilot layout and required class represented and no document contents exposed | Corpus check |
| NU-6 | **Exclude** every document containing patient or customer personal information (for example prescription or dispensing data) | Confirmed none are in the sample | NU-7, all sharing |
| NU-7 | Hand-redact or anonymise the documents that will be shared, per §12.3: replace buyer name, address and ABN, customer account numbers, BSB and bank account numbers, emails, phone numbers, staff names, logos and PDF metadata; keep supplier identity, layout, numbers, dates, lines and totals | Each shared file passes the §12.4 leak scan and a visual check, with the same fake value used for the same real value across all files | Fixtures, pack design |
| NU-8 | Pick 5–10 decoys (or approve the synthetic ones) | List agreed | v1.1 comparison, corpus check |
| NU-9 | Label the corpus: confirm the expected class and key fields for each document in the scoring sheet | Sheet complete | Gate decision |
| NU-10 | Create a Gmail app password, store it in the git-ignored owner-only secrets file, and confirm the owner's PAID sending addresses | Secrets file exists with `0600` permissions; mailbox connection succeeds; addresses are listed | `ingest`, `evidence` |
| NU-11 | Confirm a paid, Australian-region Gemini tier and check its data-use terms; create the API credentials | Terms checked and noted; key stored in secrets | LLM fallback |
| NU-12 | Choose the backup target (external disk or cloud folder) | Target chosen and writable | `ops` |
| NU-14 | Provide image-only invoices from the main image-sending supplier: at least 10 real files in the private folder, plus two redacted by black boxes for the shared fixtures (see §12.3: text-based anonymisers cannot edit image content, so redact the image itself, check no buyer text remains under or beside the boxes, and strip PDF metadata) | Real files in the private folder; two redacted files pass the §12.4 leak scan and a visual check | OCR stage, engine comparison |
| NU-15 | Ask that supplier whether they can send the original PDF with a text layer instead of an image | Answer recorded; if yes, the OCR path for that supplier is retired | Nothing (optional) |
| NU-13 | During the live check, confirm `unconfirmed` rows and compare the ledger with the manual list through at least two weeks and one full month-end Fred/NAB/pay-run cycle | Every eligible attachment has one terminal disposition; no silent miss or duplicate payable row; month-end variances are reason-coded | Go-live |
| NU-16 | Provide a redacted NAB transaction CSV that preserves headers, date/amount/reference formats and includes synthetic or redacted examples of one invoice payment and one combined payment | Local fixture passes §12.4 review; expected allocations are recorded by safe ID | `bank`, `payrun` |

## 10. Open inputs needed from owner

All of these are `needs-user` tasks; the full list with done-checks is §13.

- Which store pilots; names of the big-3 wholesalers (seed packs + statement layouts)
- Acceptance corpus (about 50 documents) covering every pilot supplier layout and document class, including one statement per big-3 wholesaler (real files stay out of git)
- Gmail app password for the invoices mailbox, stored in an owner-only `0600` secrets file
- Owner's sending address(es) for PAID emails
- Supplier sender roster as it grows (new sender → alias or pack)
- Which 5–10 deliberate decoys to include in the corpus (credit notes titled like invoices, statements mentioned in boilerplate, remittance wording in payment text, proformas, duplicated or multi-part invoice numbers)
- One redacted NAB CSV preserving the pilot's real column and reference formats

## 11. Costs

Near-zero steady state: Gemini fallback ≪ A$1/mo at ~110 docs; everything else local. Optional later: VPS ~A$15/mo.

## 12. Privacy and data handling

**Principle:** share the minimum needed to build and verify the system. Real documents are processed by code on the owner's machine. AI assistants (Claude, Gemini and similar) work from anonymised or synthetic documents and from aggregate results.

### 12.1 Where data can leak

- **AI assistants:** any file an assistant reads, or any text pasted into a chat, is sent to its provider. Assistant session transcripts are also stored locally and indexed by session-search tools.
- **Git:** anything committed, including history.
- **Production LLM fallback (§2):** the extracted text of a document that misses its pack is sent to Gemini.
- **Logs and outputs:** error messages, test output and generated workbooks can contain real values.

### 12.2 Four tiers of data

| Tier | What | Where it lives | Who may read it |
|---|---|---|---|
| Private | Real documents as downloaded, real ledger, archive | A private folder outside the project directory, on an encrypted disk, with owner-only permissions | The service and the owner only. No assistant is pointed at it; add an explicit read-deny rule for that path in the assistant's settings |
| Local redacted | Format-preserving anonymised copies derived from real layouts | Git-ignored `fixtures/redacted/` on the owner's machine, covered by backup | Owner and assistants working locally after §12.4 approval; never git |
| Committed synthetic | Documents created wholly from invented values, including CI contract fixtures and decoys | `fixtures/synthetic/` in the repo | Assistants, git and CI |
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
- **Image-only documents:** a text anonymiser cannot edit them. Redact by drawing opaque boxes over buyer details on the image, flatten the file so the boxes cannot be removed, and strip metadata. Then run OCR on the redacted file and confirm none of the deny-list values come back out. Layout and supplier details stay visible so the pack can still be built.
- **Decoys:** build most from anonymised documents by editing them (credit note titled like an invoice, "statement" in boilerplate, proforma, duplicate or `-2` suffix numbers). Real adjustment notes are only needed for layout.

### 12.4 Checks before a local redacted fixture is used or anything enters the repo/chat

1. Run the anonymiser on a copy in the private folder.
2. Read every output: inspect extracted text and every rendered page. Image content such as logos is not covered by text extraction.
3. Run `scripts/leak_scan.py` against the private deny-list (store name, buyer ABN, bank details, staff names, street, email domains, phone numbers). The deny-list stays in the private folder.
4. Check PDF metadata and embedded images are clean.
5. Record fixture safe ID, supplier, document type, anonymiser version, reviewer and review date in git-ignored `fixtures/redacted/manifest.json`. `leak_scan.py` exit 0 is necessary but does not approve a fixture without this visual-review record.
6. Keep redacted real-layout fixtures and their manifest local and git-ignored. Only wholly synthetic fixtures may enter `fixtures/synthetic/` and git; inspect them before commit and run both `python3 scripts/leak_scan.py` and `python3 scripts/leak_scan.py fixtures/synthetic` as the repository privacy gate (the script scans `fixtures/redacted` by default).

### 12.5 Anonymiser requirements

The current local anonymiser (`example_3_anonimizzato.pdf`) is a start, but on inspection:

- it replaces values with tokens, which breaks the ABN rail and anchors (use format-preserving values);
- it labelled the BSB as `ZIPCODE`, and the supplier ABN as an Italian VAT number (`PIVA`), so the detectors are Italian-tuned;
- the bank account number and an embedded image were still present in the output I could see;
- it replaces supplier details that are public and needed.

Required: an Australian-aware profile (ABN, BSB, account number, phone, address, email), a keep-list for supplier identity, consistent mapping across documents, and an output test: the leak scan in 12.4 must pass.

### 12.6 How the sample is used

- **Verification runs locally.** The service is run on the real sample in the private folder; the owner or the service produces the scoreboard. When a document fails, the failure is reproduced on its anonymised version or a minimal redacted excerpt, and the pack is fixed there.
- **Sample size.** The acceptance corpus (about 50 documents, one frozen manifest) is scored locally. It contains enough invoices to cover every pilot supplier layout, one statement per big-3 wholesaler, representative credit/adjustment notes, the Fred report and 5–10 decoys. Pack design uses one to two local redacted documents per supplier layout; CI uses synthetic equivalents for the core contracts.
- **Production fallback.** Use a paid or enterprise Gemini tier in an Australian region, with data-use terms checked to confirm prompts are not retained or used for training. Do not use a free tier for real documents. Send only the extracted text of the failing document, with buyer details masked where practical.
- **Retention.** Keep real documents only as long as the archive requirement needs. Delete the downloaded test copies when the corpus check is finished.

---

*Spike evidence: `pipeline/spike.py` + `pipeline/vendors/` — 4/4 PDFs extracted, credit-note decoy caught, Fred report reconciles to the cent. Prior analysis and gate criteria: PLAN.md §6 (retained as targets, measured by the corpus check instead of a bake-off harness).*
