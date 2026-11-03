# Real-data protocol v2 (written 2026-11-03, before the first run of any fixed code on real data)

Status: frozen once the "Freeze record" at the bottom is filled in. Until then only the development slice may be used to choose the values named in "How I tune". After the freeze, anything that changes goes under "Deviations", dated, and the text above stays as it was.

Author of every label in this file: me (an AI model working for the lab owner). Hand-checks are NOT independent labels.

Why a v2: the v1 real-data run (`PROTOCOL.md`, `evidence/01` to `05`) showed three weaknesses.
1. The reader refused all 193 CORD totals, because 185 of them are written in a style the strict money rule refuses (`60.000`).
2. The duplicate check flagged 14,603 of 50,583 Rochdale vouchers (28.9%), and 21 of 30 hand-checked flags were fixed recurring payments.
3. The duplicate check cleaned supplier names with `norm_vendor` (drops the legal suffix) while matching used `vendor_identity` (keeps it).

v1 files stay as they were. v2 results go to `evidence/v2-*.txt`.

## Data and split

| | Development slice (rules may be tuned here) | Frozen scoring set (looked at once, after the freeze) |
|---|---|---|
| CORD-v2 | rows returned by the datasets-server `first-rows` endpoint for the `train` split (26 receipts; the `rows` endpoint refuses `train`, so I could not get more) | the same 193 scored receipts of the `test` and `validation` splits as v1 |
| Rochdale | January, February, March 2025 vouchers | April, May, June 2025 vouchers |

The CORD development slice is small. I say so in the report. Money-format rules are mostly decided by reasoning and unit tests, not by fitting to those 26 receipts.

For the council, the detector is run over January to June in file order (a detector keeps history, as it would in use). Flags are counted only for vouchers dated in the scoring months. I also report a cold start (April to June only, no history) because the warm start can only help. "v1 on the same months" is the real v1 code (`real-data/v1/`, a copy of `src/` at commit `bcf6ab2`) run the same way.

Voucher unit, supplier filtering, decoding and amount parsing are exactly as in `PROTOCOL.md` (Deviation 2 voucher level: one document per (TRANSACTION No., supplier), total = sum of kept lines, only totals above zero are fed).

## Part A v2: money formats

`util.money()` stays strict and unchanged. It is also used for PO totals, which must not be loosened. The extractor gets a new reading step (`numfmt.py`) for the amount fields it reads: Subtotal, Tax, Total, Amount Due and item unit and amount.

### Two conventions
- US: comma groups thousands, dot is the decimal mark (`1,234.56`).
- EU: dot groups thousands, comma is the decimal mark (`1.234,56`).
Space (also no-break and narrow no-break space) and apostrophe can group thousands in either convention (`1 234,56`, `1 234.56`, `1'234.56`). A space is never a decimal mark.

### Reading one token under one convention
1. Optional sign and one currency symbol, then digits.
2. Integer part: plain digits (1 to 12), or groups: first group 1 to 3 digits not starting with 0, then groups of exactly 3, all joined by the same separator.
3. Optional fraction: the convention's decimal mark and 1 to 3 digits. Four or more digits: invalid.
4. If the currency is known (see below) and has `e` minor digits, a fraction longer than `e` digits is invalid. So `60.000` with a zero-decimal currency can only be a grouped number.
5. The value is kept exact (no rounding). A value that is not a whole number of cents is never returned as a total, see "Refuse".

Examples: `1.234,56` is valid only as EU. `1,234.56` only as US. `12,50` only EU. `12.50` only US. `1.234.567` only EU. `1,234` is US-grouped (1234) or EU-decimal (1.234). `1.234` is the mirror. `60.000` is US-decimal (60.000 = 60) or EU-grouped (60000). `1250` and `12` mean the same in both.

### Document rule
1. Each amount token has the set of conventions under which it reads. The document's convention must be one that reads every token. If no convention reads all tokens, the document mixes styles: every token written with a separator is refused and the issue `mixed_number_formats` is recorded.
2. If every token has the same value under both remaining conventions, nothing is ambiguous and the values are used as read.
3. If one convention remains, it is used. If that was decided only because another token or the currency ruled the other convention out, the reading counts as inferred (below).
4. If both conventions remain and some token's value differs between them, the token is ambiguous. It is accepted only with evidence from the same document, taken in this order:
   a. Declared currency: ISO 4217 minor-unit count `e` from the document's `Currency:` line (or the caller's `assume_currency`, which I use only for a labelled diagnostic). Zero-decimal currencies (JPY, KRW, VND, CLP, ISK and similar) have `e = 0`. IDR is listed with `e = 0` by common practice although ISO 4217 lists 2; this is a stated choice. Three-decimal currencies (KWD, BHD, OMR, JOD, TND, IQD, LYD) have `e = 3`. Everything else `e = 2`. This is applied in step 4 of "Reading one token".
   b. Declared locale: a `Locale:` or `Number format:` line holding a tag from a short allow-list (for example `de-DE`, `fr-FR`, `en-US`, `en-GB`). Unknown tags are ignored. It picks the convention.
   c. Arithmetic: for each remaining convention, check every applicable relation: quantity x unit = amount for each item row; sum of item amounts = Subtotal; (Subtotal, or the item sum if there is no Subtotal) + Tax = Total, each within one cent. If exactly one convention satisfies all of them, it wins. If both or neither do, there is no evidence from arithmetic.
   If locale and arithmetic point at different conventions, the document is refused. If the evidence does not decide, the ambiguous tokens are refused with the issue `<field>_ambiguous_format` and the document goes to the review queue. The document is never read by a default guess.
5. A reading that was inferred (steps 3 or 4) sets that field's confidence to 0.7, which the matcher already sends to review. The extractor accepts the value, the matcher does not auto-match on it.

### Refuse
A value whose exact amount is not a whole number of cents (for example `1.234` read as 1.234) is refused with `<field>_not_2dp`. An item row with an unreadable or refused unit or amount is dropped with `items_unparsed`, as before.

### What I will not change
The label rules of the extractor: a total is read only from a line `Total: <value>` (or `Amount Due:`/`Grand Total:`). CORD receipts have lines like `TOTAL 60.000`, with no colon. So the headline CORD variant R (text as built) will still refuse every receipt in v2 and the money fix is visible only in diagnostic variant C (a colon added). I report both. I do not loosen the label rule, because that is a separate decision and `Total 3 items` style lines exist.

### Part A scoring
Same as v1: per receipt CORRECT / WRONG / REFUSED for the total, same ground-truth rule (Deviation 1 of v1: a trailing two-digit cents group is stripped, then digits kept). Variants: R (text as built), C (colon added). Two C readings: C-doc (evidence only from the document; no currency passed) and C-IDR (diagnostic: the caller declares `assume_currency="IDR"` for all receipts, a deployment-level fact about this data set, not per-document evidence; labelled as such). Wilson 95% intervals from `util.wilson`. Wrong is worse than refused: the pass condition is WRONG = 0 on both the development slice and the frozen set, and CORRECT reported next to it.

Pre-stated expectation (not a result): C-doc stays almost all refused, because a CORD receipt rarely has line items in the lab's `- name | qty x unit = amt` layout, so there is no arithmetic evidence. C-IDR should read most of the dotted totals.

Unit tests (synthetic) must cover every ambiguous case, including `1.234` both ways, `1,234`, `60.000`, `0.500`, `1.000`, mixed styles, locale versus arithmetic conflict, currency evidence, and the cases where evidence does not decide.

## Part B v2: duplicates

### One vendor key
`DuplicateDetector` (and `PartTracker`, and the pipeline's queue and consumption keys) use `vendor_identity` everywhere, the same key matching uses. `Kestrel Ltd` and `Kestrel Inc` are different suppliers for duplicate purposes too.

### Recurrence-aware rules
Key `K` = (vendor_identity, total, currency). An earlier event on `K` is (date, invoice number, PO reference, context). `context` is an optional hashable label supplied by the caller (for the council data: the voucher's set of PURPOSE values). `extract()` never sets it. A pair of events is "distinct" when both have a PO reference and they differ, or both have a context and they differ.

Checked in this order for a new document:
1. Same supplier, same invoice number, same part: unchanged from v1 (`resubmission` if content is the same, `id_conflict` if not).
2. SAME_REF: some earlier event on `K` has the same PO reference and a different invoice number: `possible_duplicate`. (v1 rule, now with `vendor_identity`.)
3. Take the earlier events on `K` with a different invoice number that are not distinct from the new one. Call this set `E`. If `E` is empty: not a duplicate. (Distinct references or distinct context mean different things were paid.)
4. NEAR: if no event in `E` is dated within `W` days of the new date (both dates known; two unknown dates count as the same day): not a duplicate. (Repeats further apart are periodic or unrelated, not a re-keyed copy.)
5. RECURRING: let `U` be the sorted distinct dates of `E` plus the new date. If the new date has two neighbours in `U` on one side or one on each side whose gaps are both in the same cadence class, the key is on a cadence. Classes: weekly 5 to 9 days, fortnightly 12 to 16, monthly 26 to 35. If the new date is a date that `E` already has (a same-day repeat), the repeat is accepted as part of a batch only when the key is on a cadence AND some other date in `U` has at least as many events in `E` as the new date would have (including this one). More same-day payments than any earlier cycle had is flagged.
6. Otherwise: `possible_duplicate`.

`check()` returns the same strings as before. `check_detail()` returns (verdict, why), why being one of `same_reference`, `near_no_cadence`, `batch_surplus`, `recurring_batch`, `distinct`, `outside_window`, `first_seen`. A same-supplier, same-amount pair with one earlier event, same day, no references, flags exactly as in v1.

Known limit, stated now: a detector that reads a stream cannot know the first cycle of a batch is a batch. Every recurring key is flagged in its first cycle. A true duplicate that copies a payment inside a recurring batch pattern looks exactly like a normal batch member and will be missed. Both are measured, not hidden.

### How I tune (development slice only)
Three values are open: the window `W` in {0, 1, 3} days, whether rule 5 is on, and whether `context` is used. The other numbers (cadence classes) are fixed above and not tuned.

Metrics on January to March (vouchers fed, in order):
- Flagged share = flagged vouchers / vouchers fed.
- Planted-duplicate recall. From the development vouchers I draw 300 at random (`random.Random(20261103)`), and for each insert a copy with a new voucher number, same supplier, amount and context, dated shift days later, for shift in {0, 1, 3, 10}. Recall = copies flagged / copies, reported per shift and split by whether the key already had at least 3 distinct dates in the real data (a "recurring key") or not. This is synthetic injection and says what the rules can catch, not how many real duplicates exist. Shift 10 is a control that should NOT be flagged.

Selection, fixed now:
1. Context on or off: on only if it lowers the flagged share and the planted recall on non-recurring keys at shift 0 stays at least 95%.
2. Rule 5 on or off: on only if it lowers the flagged share by at least 5 points of the v1 share on the development months and the planted recall on non-recurring keys at shift 0 stays at least 95%.
3. `W`: the largest value in {0, 1, 3} whose flagged share is no more than 2 percentage points above the share at `W = 0` (with 1 and 2 decided). Ties go to the smaller `W`.
If a rule fails its condition it is left out and I say so.

### Frozen scoring (April to June)
Report, for v1 and v2 on the same months and the same vouchers: vouchers fed, flagged count, flagged share, reasons (v2), flags by supplier concentration, plus v2 cold start. Also the 423 flags that joined two spellings of a supplier in v1: how many remain.

Hand-check: 30 v2 `possible_duplicate` flags in April to June, drawn with `random.Random(20262611)` from the flags in file order. I read, per flag: supplier (company names only), total, both dates, the voucher numbers, purposes of both vouchers, how many other suppliers were paid that exact total, how many earlier events the key has and on how many dates. I label by judgement, not by a formula:
- LEGIT: there is a visible reason for two payments (rate card paid to many suppliers, same payment run, different purposes, regular series).
- SUSPICIOUS: nothing visible explains two payments.
- UNSURE.
These labels are the author's, not independent, and "SUSPICIOUS" does not mean a confirmed double payment. Because I tuned the rules to remove the legitimate-looking cases, the v2 hand-check is easier than v1's; I say so with the numbers. The v1 flags that v2 no longer flags are also sampled (30, same method) to see whether the rules dropped anything suspicious: label the same way.

## Gates
All 203 existing tests pass unless a behaviour changes on purpose, in which case the test is edited and the reason written in the README. New tests are added for every rule above. `scripts/mutate.py` gets mutants for the new logic and every one must be killed. `scripts/evaluate.py` is re-run on sets A, B, C and any change is reported.

## Freeze record
Filled in 2026-11-03 after the development runs (`evidence/v2-01-cord-dev.txt`, `evidence/v2-02-council-tune.txt`, and the v1 development baseline in `evidence/v2-02b-council-tune-v1.txt`), before any run on the frozen set.

Development results that decided the three open values (January to March, 29,484 vouchers fed; v1 flagged 28.7%):
- Context: on. Flagged share fell from 16.9% to 16.6% at W=0 and the planted recall on non-recurring keys stayed 172/172. (A small effect: 0.3 to 0.4 points.)
- Cadence rule: on. Flagged share fell from 28.6% to 16.9% at W=0 (about 12 points, above the 5-point bar) and non-recurring planted recall stayed 172/172.
- Window W: 3. With context and cadence on, the shares were 16.6% (W=0), 16.9% (W=1), 17.2% (W=3), all within 2 points of W=0.

Frozen configuration: `DuplicateDetector(window_days=3, use_cadence=True, use_context=True)`. Cadence classes 5 to 9, 12 to 16, 26 to 35 days, unchanged.

What the development numbers already show, written before the frozen run: the cadence rule cannot catch a planted copy that sits inside a recurring batch (non-recurring keys 172/172, recurring keys 84/128 at shift 0 with W=0). This is the stated limit, now measured.

CORD: the development slice has 26 receipts (`first-rows` endpoint). The money rules were not changed after seeing them. The one WRONG on the development slice (variant C-IDR) is a label problem, not a number-format problem: the receipt's `TOTAL` line is the pre-tax subtotal and the real total is on a `GRAND TOTAL` line. I did not change the diagnostic variant to remove it. The frozen run reports it the same way.

## Deviations

### Deviation 1 (2026-11-03, after the frozen runs)
Two edits that change how results are printed or explained, not what the extractor returns:
1. After the frozen run I added unit tests and mutants. While writing a test I found that `numfmt` returned an exact value such as `Decimal('60000.0')` instead of a two-decimal one. Equality was unaffected, but the printed value was not cents. I now quantise to two decimals before returning. All numbers (correct, wrong, refused, flagged) were re-run and are identical; only the printed text of the four WRONG examples changed (`46636.0` became `46636.00`). The evidence files `v2-01`, `v2-03`, `v2-04` were regenerated with the final code; `v2-06` was re-run and is byte-identical.
2. The WRONG-cause helper in `run_cord_v2.py` did not handle receipts whose labelled subtotal is a list. I fixed the helper so all four frozen WRONG receipts are classified. This changes only the explanation printed next to each WRONG, not any count.

### Deviation 2 (2026-11-03, before the freeze)
The development slice is 26 CORD train receipts, not the 100 or more I hoped for. The `rows` endpoint refuses the train split (scan size limit) and the `first-rows` endpoint returns 26. I did not try another source.

### Deviation 3 (2026-11-03)
Three existing tests were edited and one contract changed, because behaviour changed on purpose: with distinct PO references, two invoices with the same supplier, amount and date are two orders, not a possible duplicate (`tests/contracts.py` rekeyed_duplicate_flagged, `tests/test_pipeline.py` test_possible_duplicate_flagged_and_queued, `tests/test_round2.py` test_poisoning_is_fail_safe_and_documented). The copies in those tests now carry the same PO reference, or no reference, which still flags.
