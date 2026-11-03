# DocMatch Reliability Lab

**Independent technical demonstration. The tests use made-up invoices on purpose; the main results use real public data (see `real-data/`). Not client work.**

Status: **CI-PASSING**, independent evaluation pending. Last full remote CI run: commit `2cfc7e5`, [run 41601100997](https://github.com/ASPs-Git-Hub/docmatch-reliability-lab/actions/runs/41601100997), Python 3.9, 3.10, 3.12 and 3.13: unit tests, the evaluation script and the planted-defect check. I also ran everything locally on 2026-11-03. No outside person has checked the results. The confidentiality gate (`check-confidential.sh`) was run locally by me, not in CI. Every made-up test set was written by me with an AI model, so none is independent human labelling.

Details of what I ran: I ran the tests and scripts below myself. Two independent model reviews have been answered (round 1 and round 2, see `REVIEW_ROUND2.md`). There is no human review.

## Real-data results
Full write-up, rules and raw output: [`real-data/README.md`](real-data/README.md). Real invoice and purchase-order pairs are not public, so I could not test the main job (matching an invoice to its order). I tested two smaller things on real data: reading the total off a receipt (200 CORD-v2 receipts, 193 with a labelled total) and the duplicate-payment check on Rochdale Council payments (about 50,600 vouchers, January to June 2025).

| Test | Before the fix (v1) | After the fix (v2) |
|---|---|---|
| Receipt totals as written: right / wrong / refused | 0 / 0 / 193 | 0 / 0 / 193 |
| Receipt totals, with the currency declared by me as rupiah: right / wrong / refused | not possible | 118 / 4 / 71 |
| Council vouchers flagged as possible duplicates (April to June) | 29.1% | 19.8% |

- The reader never guessed on receipts as written. It refused all 193. That is safe, and also useless for this style of receipt.
- The number fix (`60.000` can mean sixty thousand) works only when the document or I say which currency it is.
- The 4 wrong totals read the "before tax" line, not the "grand total" line.
- Most flagged council payments still look normal on a hand check (19 of 30). No flag is a confirmed double payment.

A small, standard-library-only demonstration of supplier invoice to purchase-order reconciliation for a fictional company, using synthetic text invoices. Most of the work is in the reliability engineering around the matching: strict tiers, "never auto-match when unsure", refusing instead of degrading at extraction, PO-level consumption so one order is paid once, duplicate and multi-part handling, and an exception queue. The evaluation reports the number that matters (false auto-matches) with confidence intervals.

## Problem

Automatic matching is only useful if a wrong match is rarer than a human mistake. A matcher that guesses silently moves money against the wrong order. So the design rule is to auto-match only a unique, strong, same-currency candidate that nobody has billed before; send everything else to a human queue with the reason attached.

## Layout

```
src/docmatch/extract.py    regex extraction with per-field confidence; refuses invalid values (issues list)
src/docmatch/match.py      tiered matching, directional tolerance, date window, vendor identity, confidence gate
src/docmatch/validate.py   totals and line arithmetic, duplicates, multi-part tracking
src/docmatch/queue.py      exception queue (one entry per invoice+reason, idempotent, priority)
src/docmatch/pipeline.py   process(batch) -> auto_matched / needs_review / skipped / queue; PO consumption
src/docmatch/naive.py      baseline with the usual defects (kept on purpose)
src/docmatch/util.py       strict money grammar, vendor normalisation, Wilson interval
tests/                     277 unittest tests (203 older, 74 new in test_v2.py; 18 contracts run against both implementations)
data/set_a.json            tuning set (20 cases)
data/set_b.json            set B (36 cases, 16 traps), byte-identical to its freeze commit
data/set_c.json            set C (39 single-invoice cases + 10 labelled batch cases), round 2
scripts/evaluate.py        counts + Wilson 95% intervals, strict single-disposition check, batch scoring
scripts/mutate.py          148 planted one-line defects (96 older in three groups, 52 for v2)
evidence/                  real saved output of the commands below
.github/workflows/test.yml CI definition (lab root; runs when the lab is its own repository, see below)
REVIEW_ROUND2.md           one accept/reject row per finding of the two round 1 reviews
```

Run: `python3 -B -m unittest discover -s tests`, `python3 -B scripts/evaluate.py`, `python3 -B scripts/mutate.py`.

## Matching rules (stated, not tuned beyond what is noted)

Extraction refuses rather than degrades. A labelled field whose value is not in the strict grammar is left empty and the reason is recorded: decimal-comma or three-decimal or exponent amounts, impossible calendar dates, PO references with trailing fragments, item rows in an unknown layout, conflicting currency evidence, invalid or repeated "Part" declarations, two different PO lines. A currency is taken only from an explicit `Currency: XXX` line; a bare `$` is never read as USD. There is no free-text date fallback. Labels cannot capture a value from the next line.

- Confidence gate: a field the tier relies on (vendor, currency, total, date) with 0 < confidence < 1 (for example a total read only from an "Amount Due" line, 0.7) is never auto-matched (`low_confidence_<field>`). Invoice number read only by the INV- fallback (0.5) goes to review.
- Tier 1: exact PO reference. Needs vendor agreement (similarity >= 0.85 AND the same legal suffix when both names carry one), total within tolerance, equal currency, and no closer same-vendor, same-currency PO (`closer_candidate_exists`). An unknown or failing reference goes to review; it never falls through to a weaker tier. Label variants read: PO, PO No/Number/Ref, Your PO, Purchase Order [No], Order Ref/No/Number.
- Tier 2: no reference. Refused outright if a PO-shaped token appears anywhere in the text (`unlabelled_ref_present`). Otherwise exact vendor identity (normalised name plus canonical legal suffix: "Kestrel Inc", "Kestrel Co" and bare "Kestrel" are three different vendors; "Ltd" equals "Limited") + total within tolerance + same currency + invoice date from 3 days before to 90 days after the PO date. Auto-match only if exactly one PO qualifies; a same-vendor, same-amount twin outside the window makes it ambiguous (`twin_outside_window`).
- Tier 3: fuzzy vendor (difflib ratio >= 0.85) + total within tolerance. Weak: always AMBIGUOUS, never auto. Note the 0.85 fuzzy test is not an identity test: "Northern Tool Co" vs "Northern Tools Inc" scores 0.96 on name similarity but is stopped at Tier 1 by the legal-suffix disagreement (Co vs Inc); "Brightwater Suplies Ltd" vs "Brightwater Supplies Ltd" (0.97) passes at Tier 1 with a reference. The boundary is pinned by tests (0.80 fails, 0.97 passes).
- Tolerance: under-billing `|invoice - PO| <= max(2% of PO total, 1.00)` inclusive; over-billing the same band but capped at an absolute 50.00. Configurable. Known limit: on a tiny PO the 1.00 floor still allows a large relative over-bill (a 1.00 PO accepts a 2.00 invoice).
- Currency mismatch or missing currency never auto-matches.
- Validation: line quantity x unit must equal the stated amount (1 cent), lines + tax must equal the total, subtotal + tax must equal the total even when no item rows exist, every bullet row must parse.
- PO consumption: a PO is billed once. The first auto-matched invoice consumes it; any later MATCH against the same PO goes to review as `po_already_matched` (plus `po_overbilled` when the cumulative amount exceeds the PO). Partial billing against one PO is therefore not supported and always needs a human.
- Duplicates: identity is (vendor, invoice number, part); the fingerprint covers total, date, PO, currency, subtotal, tax and all item rows, so a same-number invoice with changed content is `duplicate_id_conflict`, never a silent skip. Content keys also flag a re-keyed copy: (vendor, total, date) and (vendor, total, currency, PO) under a new number.
- Multi-part invoices ("Part i of n", `Part: 1 of 2`, `Part 1 of 2` or `Part 1/2`, n <= 100) must carry a PO reference; parts must agree on vendor, PO, currency, date and n; they reconcile only when all n parts have arrived, in any order.
- Scope: one `DocMatch` instance, sequential or threaded (process() is serialised by a lock). State is in memory; a new instance forgets everything. A bad document or PO record becomes a `processing_error` review entry instead of aborting the batch.

## Results

Counts, not bare percentages. Intervals are Wilson 95%. Full output: `evidence/evaluate.txt`. Single-invoice cases only unless a row says batch.

| Set | Status | System | False auto-match | Traps flagged | Correct auto-match |
|---|---|---|---|---|---|
| C (39 single) | NEW round 2, same author model labelled it | DocMatch | 0/39, [0.0%, 9.0%] | 25/25, [86.7%, 100%] | 14/14, [78.5%, 100%] |
| C | | Naive baseline | 24/39, [45.9%, 75.1%] | 1/25, [0.7%, 19.5%] | 14/14 |
| C batch (10 cases, 20 invoices) | | DocMatch | 0/20, [0.0%, 16.1%], 0 POs matched twice | | |
| C batch | | Naive baseline | 11/20, [34.2%, 74.2%], 10 POs matched more than once | | |
| B (36 cases, 16 traps) | **regression-checked, not clean** (see below) | DocMatch | 0/36, [0.0%, 9.6%] | 16/16, [80.6%, 100%] | **19/20**, [76.4%, 99.1%] |
| B | | Naive baseline | 16/36, [29.5%, 60.4%] | 2/16, [3.5%, 36.0%] | 18/20, [69.9%, 97.2%] |
| A (20 cases, 8 traps) | TUNED, not clean | DocMatch | 0/20, [0.0%, 16.1%] | 8/8, [67.6%, 100%] | 12/12, [75.8%, 100%] |
| A | | Naive baseline | 5/20, [11.2%, 46.9%] | 3/8, [13.7%, 69.4%] | 12/12 |

Definitions: false auto-match = the system auto-matched where the label says the case must be flagged, or auto-matched to the wrong PO (counted over all cases of the set). Trap = a case built to look matchable but which must not be auto-matched. Correct auto-match = a normal case auto-matched to the labelled PO. A flagged trap counts only if the case ends with exactly one disposition and, for DocMatch, a queue entry; a silently dropped case is counted as `dropped` (0 everywhere). The batch rows compare each invoice's outcome (MATCH:po, FLAG, SKIP) with the label, and count POs auto-matched more than once.

Changes since the round 1 numbers:
- B-N07 (correct auto 20/20 became 19/20) is now flagged on purpose. Round 1 labelled "older same-amount twin outside the window, no reference" as MATCH; the Fable review argued a client's AP team would call that a wrong-PO match, and the rule was changed (`twin_outside_window`). Set B is not edited in place, so the label stays and the miss is reported. The same case in set A (A-N07) was relabelled from normal to trap, because A is a tuned set; that is why A has 8 traps now instead of 7.
- Set A/B false auto-match stay 0, trap flagged stay all.

Other results:
- Tests: 277 run now (203 at round 2), all pass; the 203 figure below is from the round 2 evidence: all pass on 3.14 (`evidence/unittest-v.txt`), 3.12 and 3.9 (`evidence/unittest-other-pythons.txt`). 18 contracts run against both implementations: fixed passes all, naive fails all 18.
- Mutation: 148 planted defects now, 148 caught (`real-data/evidence/v2-08-mutate.txt`). At round 2 it was 96 planted, 96 killed, 0 survived, 0 crashes, plus a no-op control that correctly survives (`evidence/mutate.txt`). Reported in three groups, never as one clean percentage: 32 from the round 1 list of 31 (one split in two) re-pointed at the new code; 15 of the 18 mutants the Fable reviewer planted (9 of the 18 had survived round 1, and 8 of those 9 are re-applied here and now killed; 3 of the 18, one of them a round 1 survivor, are retired because the fixes removed the code they mutated); 49 written for the round 2 behaviours. All 96 are hand-picked and were written after the code and the tests, so this is a property of the chosen mutants, not a random-operator mutation score. One mutant (aggregate currency taken from the wrong part) was dropped as equivalent: the tracker already forces all parts to share a currency. Four of the round 2 mutants survived their first run: three got a new or stronger test (amount due fallback after a garbled total, fingerprint subtotal, lock) and the fourth was dropped as equivalent.

## How the sets were handled, honestly

- Set B was committed alone (commit 3cedf49 "Freeze docmatch evaluation set B before code") BEFORE the code commit b875dd5 that contained `match.py`. The git timestamps are 00:28:45 and 00:35:00, six minutes apart, in one authoring session. The set's meta block already stated the tier rules and the 2% / 1.00 tolerance, so the rules and thresholds were fixed at freeze, by the same author as the labels. Commit order shows the cases were committed before the code. It does not show that the rules came after them. The earlier README sentence "frozen before the thresholds were written" was wrong and is withdrawn.
- **The code changed after set B was measured.** Round 2 rewrote extraction, matching, validation and the pipeline. Set B's numbers are therefore a regression check that the old behaviour on old cases still holds (with the single B-N07 exception above), not a clean out-of-sample result. `data/set_b.json` is byte-identical to its freeze commit.
- Set A was used while building and is tuned. Its own meta block says thresholds were adjusted while looking at these cases. An earlier README and HANDOFF said no threshold was changed by looking at set A; git has no history between the build steps (one commit), so that claim cannot be verified and is withdrawn. Treat A as tuned and the defaults (2%, 1.00, 3/90 days, 0.85) as author choices.
- Set C was written in round 2, by the same author model that fixed the code, after reading the review findings, and its labels were fixed from the README rules before it was first run. It covers the traps those findings named (reused PO, label variants, decimal commas, symbol-only currency, parts in two currencies, twins outside the window, cap boundary and so on) with new vendors and new wording. Its first run scored 0 false auto-matches and 25/25, 14/14, and 20/20 batch outcomes right. That was expected. The cases were written knowing the fixes, so set C checks that the specification is implemented and cannot discover anything the author did not think of. It is the new regression test, not an independent test.
- **The labeller is the same author model in every set (Claude), not an independent human.** Fable (also a model) re-labelled ten B cases blind and agreed 10/10, which supports label consistency only.
- A bug found by the unit tests during the first build: the invoice-number fallback regex matched the word "INVOICE" in the header. Fixed before any evidence output was saved.

## What this does NOT prove

- The sets are tiny, hand-selected and synthetic. 0/36 or 0/39 false auto-matches does not bound a population rate: the Wilson interval assumes independent random draws from the population of invoices, which these are not. Read the intervals as "the most these particular cases can distinguish". They give no assurance about real invoices. Conditional on auto-matched cases (the only ones that can be wrong) the sample is 20 on B and 14 on C; a Wilson upper bound for 0 errors in 20 is 16.1%.
- The same author model wrote the rules, the code and every set's labels. A perfect score shows the code follows the rules as written. It says nothing about whether the rules are right. No independent human labelled anything.
- The code changed after B was measured; B is not clean. C was written after the fixes and checks them.
- No OCR and no images: input is clean generated text in one layout family. Real invoices vary far more.
- Extraction is regex; the per-field confidence is a hand-set label (1.0, 0.7, 0.5, 0.0), not a calibrated probability.
- Tolerance and uniqueness cannot establish that an invoice is for a particular order. The system can only refuse when evidence conflicts. A copied PO reference on a fresh invoice for the same amount and vendor still matches if the PO has not been billed.
- Vendor identity is name based (normalised name + legal suffix). There are no supplier IDs or approved alias lists; two legal entities with the same name string are the same vendor here.
- In-memory state only: a new `DocMatch` forgets consumed POs and seen invoices; no persistence, no cross-process atomicity.
- No real ERP, no real PO feed, no currency conversion, no tax-rule handling, no partial-delivery or partial-billing logic beyond "part i of n".
- Queue priority weights (2 per day of age, 1 per 1000 of amount, capped) are a judgement call, never validated.
- Duplicate detection can make outcomes arrival-order dependent: an earlier invoice that went to review (for example an unknown PO) can mark a later same vendor/amount/date invoice as a possible duplicate. This is kept on purpose (it fails toward a human), see REVIEW_ROUND2.md.
- CI ran once on commit `47750bc` in the standalone public repository and passed (unit tests, evaluation script, mutation check). Inside a monorepo GitHub ignores the workflow unless it is copied to the repository root with a `working-directory`. The evidence files in `evidence/` are my own local output; the CI run is a second, remote execution of the same scripts, not independent validation.
- The naive baseline is a deliberately crude strawman; beating it says little about beating a good production system.
- Real-data limits: no real invoice and purchase-order pairs were used. Receipts are not supplier invoices. One council and six months is one sample. Hand-check labels are mine, made with a rule I wrote after seeing the sample. No flagged payment was confirmed as a real double payment, and the fixes were tuned on January to March data only. I ran the test once.
