# Real-data protocol (written 2026-11-03 before the first scored run)

Status: frozen. If something changes after the first scored run, it goes in a "deviations" section at the end of this file with the date, and the original text above stays as it was.

Author of every label in this file: me (the author, an AI model working for the lab owner). The hand-checks are NOT independent labels.

## What can and cannot be tested

Real supplier invoice to purchase-order pairs are not public. So this protocol tests two things real data can test:

- (A) Extraction on real receipt text: does the lab's `extract()` read the total correctly, refuse, or read it wrongly?
- (B) Vendor-name merging and duplicate-payment flags on real council payment records.

Part (C), pairs built from real records, is optional and is only done if time is left. If done it is labelled "pairs built from real records, not real PO/invoice pairs".

## Part A: CORD receipts

- Source: CORD-v2, `naver-clova-ix/cord-v2` on Hugging Face, licence CC BY 4.0 (card and API both say `cc-by-4.0`; the upstream repo `clovaai/cord` on GitHub also reports CC-BY-4.0). Fetched through the official Hugging Face datasets-server `rows` API, splits `test` (100 receipts) and `validation` (100 receipts). `train` is not used. 200 receipts in all.
- The text given to the extractor is rebuilt from the dataset's `valid_line` annotation: words grouped by `row_id`, rows sorted by the top y of the first word, words inside a row sorted by left x, words joined with one space, rows joined with a newline. Only lines CORD labelled are present. Lines CORD marked "dontcare" are absent, so this text is cleaner than a raw scan.
- The receipts are real documents but they are shop receipts, not supplier invoices. They carry no "Vendor:", "Date:" or "Invoice No:" lines. CORD has no store-name or date labels, so only the total can be scored.
- Ground truth for the total: `gt_parse.total.total_price`, keep only the digits, read as a whole number (Indonesian rupiah has no minor unit; "60.000" means 60000). A receipt with no `total_price`, or a value with no digits, is left out and counted.
- Outcome per receipt for the total field (primary variant R, the text as built):
  - CORRECT: `extract().total` equals the ground-truth whole number.
  - WRONG: `extract().total` is not None and differs.
  - REFUSED: `extract().total` is None.
- Wrong is worse than refused. The headline numbers are the WRONG count and the CORRECT count out of the scored receipts, with Wilson 95% intervals from the lab's own `wilson()`.
- Vendor and date: no ground truth. Report only how many receipts produced a non-empty value. If any do, I hand-check up to 30 and report how many are real vendor names or dates.
- Also reported: how many receipts `check_invoice()` finds clean (expected: none, since receipts have no invoice number), and the top refusal reasons.
- Diagnostic variant C (declared now, reported separately, not the headline): the same text, but a line whose first word is "total" (any case) and whose remaining text is one token is rewritten to `Total: <token>`. This asks whether the only barrier is the missing colon.
- Readable ceiling (diagnostic): for each receipt, does any token in the text equal the ground-truth digits written in a form the lab's strict `money()` grammar accepts? This says how many totals the extractor could ever read without a grammar change.

## Part B: Rochdale Borough Council payments

- Source: Rochdale Borough Council "Council Spending over £500" dataset, files `2025_JAN_Spend.csv` to `2025_JUNE_SPEND.csv` (six months, January to June 2025), from the council's open-data site `data.rochdale.gov.uk/files/`, listed on data.gov.uk with licence `uk-ogl` (UK Open Government Licence). The council says that from 1 October 2018 the file holds all spend, not only spend over £500, and that payments to individuals are replaced by "Redacted - Personal Data".
- Deviation from the brief, decided before the first run: the brief asked for a "spend over £25,000" file. Gateshead's page was tried first and its files sit behind a bot challenge (HTTP 403, `cf-mitigated: challenge`), which I did not bypass. Rochdale's files download plainly and are all-spend, so the lines are much smaller and more repetitive than a £25,000 file would be.
- Decoding: Windows-1252. Rows are kept when the supplier field is non-empty and does not begin with "REDACTED". Amounts are parsed by removing spaces and thousands commas. Rows with amount <= 0 are counted but left out of the duplicate analysis.
- Outputs are counts. Individuals are not named. A supplier string is printed in evidence only when it contains a company word (LTD, LIMITED, PLC, LLP, LLC, INC, CO, COMPANY, COUNCIL, TRUST, SERVICES, GROUP, CIC); otherwise it is shown masked.

### B1: vendor-name merging

- Unit: the distinct raw supplier strings (exact text, trimmed).
- The lab's merge rule is `util.vendor_identity()` (normalised name plus canonical legal suffix). Two raw strings are "merged" when they have the same non-empty identity.
- Counts: distinct raw strings, distinct identities, identity groups with 2 or more raw strings ("merge groups"), raw strings inside merge groups.
- Correctness of merges: from the merge groups, `random.Random(20261103).sample` of 50 groups (all of them if fewer than 50), taken from the groups sorted by identity. For each, I judge: CORRECT if every raw string in the group is plausibly the same organisation; WRONG if any string is a different organisation. If a group is too ambiguous to call from the text alone I mark it UNSURE and report UNSURE separately; it counts as neither.
- Missed merges: distinct identities that are different but whose `norm_vendor` strings share the first character and have `difflib` ratio of at least 0.85 (the lab's own fuzzy threshold). Count them. Sample 30 pairs with `random.Random(20261103)` from the sorted pair list and judge each SAME / DIFFERENT / UNSURE. In the lab this tier never auto-matches, it goes to a person; this check says how much work such a person would be handed.
- Detector/identity inconsistency count: groups of raw strings that share `norm_vendor` (what `DuplicateDetector` keys on) but have different `legal_suffix` values (what matching treats as different vendors). Reported as a count with 10 redacted examples.

### B2: duplicate and near-duplicate payments

- Each kept row with amount > 0 becomes an `Invoice`: vendor = raw supplier string, invoice_no = TRANSACTION No., total = amount, date = DATE PAID as ISO, currency GBP, no PO reference. Rows are fed to the lab's `DuplicateDetector` in file order, months in order: `check()` then `register()`, the same order `pipeline._one` uses.
- Counts by outcome: `resubmission` (same vendor, transaction number, and content), `id_conflict`, `possible_duplicate` (same normalised vendor, same amount, same date, different transaction number), none.
- Hand-check: 30 rows flagged `possible_duplicate`, sampled with `random.Random(20261103)` from the flagged rows in file order. I read the purpose, directorate, amount and transaction numbers (not printed) and label:
  - LEGIT: a recurring or batch payment with a plausible reason (different purpose or directorate, many small lines to one supplier on a payment run, regular scheduled amount).
  - SUSPICIOUS: same supplier, amount, date, purpose and directorate with no visible reason for two payments.
  - UNSURE.
  SUSPICIOUS is not "confirmed double payment". There is no ground truth for that in public data.
- Not scored, count only: pairs with the same normalised vendor and amount on different dates within 7 days, which this detector does not flag by design (its content key needs the same date).

## Part C

Only if time is left. Not started at the time of writing this protocol.

## Frozen files and reproducibility

`fetch_data.sh` downloads the files. `SHA256.txt` holds their hashes. The runners are `run_cord.py` and `run_council.py`, run with `python3 -I`. Raw stdout goes to `evidence/`. The lab's `src/` is read, never edited.

## Deviations

(none yet)

### Deviation 1 (2026-11-03, after the first scored run of Part A)

The first run (`evidence/01-cord-first-run.txt`) scored two receipts WRONG in diagnostic variant C. Looking at them showed the mistake was mine, not the extractor's: my ground-truth rule "keep only the digits" turned the label "365000.00" into 36500000. Six of the 193 labels end in a two-digit cents group (".00" or ",00"). The corrected rule strips a trailing `[.,]\d{2}` before taking digits. I report both rules side by side in `evidence/02-cord-with-deviation-1.txt`. Nothing else was changed. The primary variant R result (0 correct, 0 wrong, 193 refused) is identical under both rules.

### Deviation 2 (2026-11-03, after the first scored run of Part B)

The first Part B run (`evidence/03-council-first-run.txt`) fed every payment line to `DuplicateDetector` as if it were an invoice, with TRANSACTION No. as the invoice number. That gave 51,669 `id_conflict` and 3,278 `resubmission` outcomes out of 105,530 lines, which is absurd for six months of one council. The cause is my mapping, not the detector: in this file a TRANSACTION No. is a payment voucher that holds many lines (up to 3,630 lines in one voucher), always one supplier. The lab's duplicate identity is (vendor, invoice number), so repeated lines under one voucher look like re-sent invoices.

The right unit is one voucher = one document: supplier, TRANSACTION No., total = sum of all kept lines of that voucher (negative lines included), date = DATE PAID of its first line; only vouchers with total > 0 are fed. The headline duplicate numbers are voucher-level. The line-level numbers stay in the evidence as the first, wrongly mapped run, and are not hand-checked. The 30-row hand-check described above is drawn from the voucher-level `possible_duplicate` flags instead, with the same seed and method. I changed this after seeing results, so it is a post-hoc fix, and I say so in the README.

### Deviation 3 (2026-11-03)

Part C (pairs built from real records) was not done. The brief made it conditional on time and the work above used the budget.
