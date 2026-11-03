# DocMatch on real data

Status: BUILT_UNVERIFIED. I ran everything below myself. The sections up to "What this does not prove" describe the first (v1) run on the v1 code, and their statements about `src/` and the 203 tests are true of that run only. The last section, "Version 2: what I changed and what happened", covers the fixes and the re-measurement. Every hand-check label is mine (I am the author of the lab), so none of them is an independent label. Nothing here has been reviewed by a person outside this project.

## What this is

The lab's normal tests use made-up invoices that I wrote. This folder tries the same code on real documents and real payment records.

Real pairs of supplier invoice and purchase order (PO) are not public. So I cannot test the main job, matching an invoice to its PO, on real data. I tested two smaller things that real data can test:

- A. Can the lab's reader (`extract()`) get the total off a real receipt, or does it refuse, or does it read it wrong? Reading it wrong is the worst outcome.
- B. On real council payments, how does the lab's supplier-name cleaning behave, and what does its duplicate-payment check flag?

The 203 tests and the 96-mutant check in the lab are untouched. I did not edit anything in `src/`.

## What data, and the licence

| Data | What it is | Licence |
|---|---|---|
| CORD-v2 | 200 real shop receipts (the `test` and `validation` splits), with labelled text | CC BY 4.0 |
| Rochdale Borough Council payments, January to June 2025 | 154,735 payment lines to suppliers | UK Open Government Licence |

Details, links and file hashes are in `SOURCES.md` and `SHA256.txt`. The rules I wrote down before the first scored run are in `PROTOCOL.md`. I changed three things after seeing results. They are listed at the end of that file as deviations, and again below under "What went wrong".

I first tried Gateshead Council. Its files sit behind a bot check, so I skipped it and did not try to get around it. The brief asked for a "spend over £25,000" file. Rochdale's file lists all spend, so its lines are small and repetitive.

## What I ran

```
sh fetch_data.sh <dir>                        # downloads the data
python3 -I run_cord.py <dir>                  # Part A
python3 -I run_council.py <dir> <scratch>     # Part B
python3 -I score_handchecks.py <scratch>      # tallies the hand checks
```

Raw output is in `evidence/`. Files 01 and 03 are the first runs, kept as they were. Files 02 and 04 are the runs after the deviations. File 05 holds the hand-check labels and tallies.

## Part A: real receipts

I rebuilt each receipt's text from CORD's labelled lines, in reading order, one line per row of the receipt. 193 of the 200 receipts have a total in their labels and were scored. 7 have none and were left out.

CORD has no label for the shop name or the date. So only the total can be scored. The lab's reader wants lines such as `Vendor:`, `Date:` and `Total:`. Real receipts do not have those.

| Result for the total | Count (of 193) | 95% interval |
|---|---|---|
| Read correctly | 0 | 0.0% to 2.0% |
| Read wrongly | 0 | 0.0% to 2.0% |
| Refused (no value) | 193 | 98.0% to 100% |

That is the main result. The reader never guessed and never got one right. It also found no vendor and no date on any receipt, and `check_invoice()` marked all 193 as "malformed".

I also tried a second version of the text, labelled diagnostic. In it, a line like `TOTAL 60.000` becomes `Total: 60.000`. This asks whether the missing colon is the only problem.

| Diagnostic version | Correct | Wrong | Refused |
|---|---|---|---|
| Colon added | 3 | 0 | 190 |

The reason is the number format. 185 of the 193 true totals are written with a dot or comma between groups of three digits, as in `60.000` for sixty thousand rupiah. The lab's money rules accept `1,250.00` and refuse `60.000` and `60,000`. They refuse because `60.000` could also mean sixty with three decimals. For this data that refusal is the safe choice, and it is also why almost nothing is read. Only 9 of the 193 receipts contain any token the lab's money rules could read as the true total.

So the lab refuses receipts like these. A client with receipts in this style would need the reader changed first. A client with invoices in the lab's layout would not hit this.

## Part B: real payment records

Rochdale's file has one line per payment line. Payments to individuals are already replaced by the council with "REDACTED - Personal Data". I left those 45,324 lines out. 572 more lines had an amount or date I could not parse. That leaves 108,839 lines, of which 105,530 have an amount above zero.

I print a supplier name only when it contains a company word such as LTD or LIMITED. Other names appear as a first letter and a length.

### Supplier names

The lab cleans names with `vendor_identity()`. It lowercases, drops punctuation, drops the company suffix and keeps a canonical suffix, so `LTD` and `LIMITED` count as the same but `X` and `X LTD` do not.

| Measure | Count |
|---|---|
| Distinct supplier strings | 2,041 |
| Distinct identities after cleaning | 2,036 |
| Groups where two or more strings merged | 5 (10 strings) |
| Of those 5, merged correctly (my label) | 5 |
| Of those 5, merged wrongly (my label) | 0 |

I planned to check 50 merge groups. Only 5 exist, so I checked all 5. All five are `LIMITED` against `LTD`, sometimes with a doubled space. This council's supplier list was already tidy, so there was little for the cleaner to do. Five merges is too small a number to say the cleaner is accurate. It says the cleaner did not make a mistake on the few cases that were there.

Next I looked for names the cleaner keeps apart that a person might merge. The lab's weaker, fuzzy test (similarity of 0.85 or more) finds 16 such pairs. I labelled all 16.

| My label | Pairs |
|---|---|
| Same organisation | 4 |
| Different organisation | 10 |
| Unsure | 2 |

Three of the four "same" pairs differ only because one name lacks `LTD`. The lab keeps those apart on purpose. Ten of the sixteen are different organisations, for example two nurseries in different towns or two companies with names one letter apart. So a fuzzy merge would have been wrong far more often than right. That supports the lab's rule that the fuzzy tier never matches on its own and sends the case to a person.

### Duplicate payments

The lab's duplicate check flags a document when the same supplier, amount and date appear under a different document number.

My first attempt fed every payment line to the check as if each were an invoice. That was a mistake in how I mapped the data. In this file the `TRANSACTION No.` is a payment voucher that holds many lines, up to 3,630 lines in one voucher. The check reported 51,669 "same number, different content" cases and 3,278 "re-sent" cases, which come from lines sharing a voucher. I kept that output (`evidence/03-council-first-run.txt`) and did not hand-check it.

The fix was to treat one voucher as one document and add up its lines. That is a change I made after seeing results.

| Voucher-level result | Count |
|---|---|
| Vouchers | 53,064 |
| Vouchers fed to the check (total above zero) | 50,583 |
| Flagged as possible duplicate | 14,603 (28.9%) |
| Not flagged | 35,980 |
| Flagged vouchers that were a single line | 14,241 |
| Distinct suppliers among the flags | 477 |
| Flags from the ten busiest suppliers | 5,840 |
| Sum of the flagged voucher totals | £26.1 million |

I hand-checked 30 flags, drawn with a fixed random seed. The labelling rule is mine and I wrote it after looking at the sample:

- LEGIT: five or more different suppliers were paid exactly that total, and the voucher numbers of the two payments are not next to each other.
- SUSPICIOUS: that total was paid to only this supplier, and the two voucher numbers are within 3 of each other.
- UNSURE: anything else.

| My label | Flags (of 30) |
|---|---|
| LEGIT | 21 |
| SUSPICIOUS | 3 |
| UNSURE | 6 |

Almost all the flags are fixed weekly rates for care homes, such as £1,422.00, paid to dozens of different suppliers. The file has no field saying which resident or which invoice a line belongs to, so two payments of the same rate to the same home on the same day look the same as a double payment. The three SUSPICIOUS ones are only the ones that look most like a re-keyed entry. I cannot confirm any of them is a real double payment. There is no public ground truth for that.

What this shows: on a ledger with no invoice numbers and many fixed-rate payments, this check would hand a person about 29% of all vouchers to look at. The lab's own design sends flags to a person, so nothing is paid twice by the check. The cost is the person's time. The check is built for invoices that carry invoice numbers, and this is not that kind of data.

Other counts from the run:

- 423 of the 14,603 flags join two different spellings of the supplier name (for example with and without `LTD`). The duplicate check cleans names more loosely than the matching step does: it drops the company suffix entirely, while matching keeps `LTD` and `INC` apart. In this data that affected 3 name pairs. The effect is only more flags, never fewer.
- 367 supplier-and-amount combinations were paid again on a different date within 7 days. This check cannot flag those, because its key needs the same date. I did not score them.
- Of the six months, five have between 2,544 and 3,596 flags and June has 4. I did not find out why.

## What went wrong

1. My answer key for receipt totals was wrong for six receipts. I turned `365000.00` into 36500000 by keeping only digits. That made the extractor look wrong on two receipts in the diagnostic run. I fixed the rule, recorded it as Deviation 1 in `PROTOCOL.md`, and kept both outputs side by side in `evidence/02-cord-with-deviation-1.txt`. The main result did not change.
2. My first mapping of council lines to invoices was wrong, as described above (Deviation 2).
3. I did not do Part C, matched pairs built from real records (Deviation 3).
4. I found no bug in `src/`. The refusals above are the lab behaving as written.

## What this does not prove

- It says nothing about how well the lab matches real invoices to real purchase orders. No such real pairs were used.
- Receipts are not supplier invoices. The reader refused almost all of them, which shows its layout assumptions and says little about invoices that follow that layout.
- The receipt text is CORD's labelled lines, already cleaned. A real scan would be harder.
- One council and six months is one sample. 193 receipts is a small number.
- Only five names merged, so the supplier-name accuracy figure rests on very little.
- All hand-check labels are mine, made by the same author who wrote the lab. The duplicate labels follow a rule I chose after looking at the sample.
- No flagged payment was confirmed as a real double payment.
- Nothing here was tuned or changed in `src/`, and the 203 tests were re-run once at the end and passed (203 tests, OK).

## Version 2: what I changed and what happened

The first run found three weak spots. I fixed them in the lab's code, wrote the rules down before running the fixed code on real data (`PROTOCOL-v2.md`), tuned only on data I then set aside, and ran once on the same receipts and the same payments as before. All numbers come from commands I ran; the output is in `evidence/v2-*.txt`. Every hand-check label is mine, so none is independent.

### What was wrong, in plain words

1. **Prices like `60.000`.** In Indonesia `60.000` means sixty thousand rupiah. In the UK `60.000` could mean sixty with three decimals. The reader refused it, which is safe, but it refused almost every receipt.
2. **Too many duplicate flags.** The duplicate check raised its hand for 29 of every 100 council payments. Most were care homes paid the same fixed weekly rate on the same day, which is normal.
3. **Two ideas of "the same supplier".** The duplicate check dropped the company ending (`LTD`, `INC`) when comparing names. The matching step kept it. So the two parts of the lab disagreed about who a supplier was.

### What I changed

**Reading amounts (`src/docmatch/numfmt.py`, used by `extract()`).** A number is read under two habits. US habit: comma between thousands, dot for decimals (`1,234.56`). EU habit: dot between thousands, comma for decimals (`1.234,56`). A space between thousands is accepted in both.

- Some numbers only fit one habit: `1.234,56`, `12,50`, `1.234.567`. These are read.
- Some fit both and mean different things: `1.234`, `1,234`, `60.000`, `1.000`. These are "ambiguous". The lab accepts one only if the same document settles it, in this order: the currency (a zero-decimal currency such as yen or rupiah has no cents, so `60.000` must be sixty thousand; a two-decimal currency never writes three decimals, so `1.234` must be 1234), a `Locale:` line such as `de-DE`, or the sums (the item rows add up to the subtotal under exactly one habit).
- Another number in the same document can also settle it: if the document has `12,50`, it uses the EU habit, so `1.234` there is 1234.
- If nothing settles it, the number is refused and the invoice goes to a person. If a document mixes habits, every number with a separator is refused. A value that would not be a whole number of cents (`1.234` read as 1.234) is refused.
- A number that was decided by evidence rather than read directly gets confidence 0.7, so the matcher still sends it to a person instead of paying on it.
- `util.money()`, the strict reader used for purchase order totals, is unchanged.

**Duplicates (`src/docmatch/validate.py`).** The duplicate check and the multi-part tracker now use the same supplier key as matching (`vendor_identity`: name plus company ending). The check looks at the same supplier, amount and currency, and judges as follows:

- Same purchase order reference: flag it (as before).
- Different purchase order references, or different purpose labels: these are different things being paid, so do not flag.
- Further apart than 3 days: do not flag.
- Close together with no pattern: flag it.
- Close together, but the supplier and amount repeat every week, two weeks or month, and no more payments land on one day than on an earlier cycle: it is a standing arrangement, do not flag.

Exact rules, the values I tuned and the order I tuned them in are in `PROTOCOL-v2.md`. I tried 12 settings on January to March only (window 0, 1 or 3 days; pattern rule on or off; purpose label on or off). The pattern rule cut the flagged share from 28.6% to 16.9% on those months. The window of 3 days cost 0.6 points over a window of 0, so I kept 3. The purpose label helped by 0.3 points. I froze the settings and then looked at April to June once.

### What happened: receipts (193 scored receipts, total field)

| Text given to the reader | v1 correct / wrong / refused | v2 correct / wrong / refused |
|---|---|---|
| As built (no colon after `TOTAL`) | 0 / 0 / 193 | 0 / 0 / 193 |
| Colon added, document is the only evidence | 3 / 0 / 190 | 4 / 0 / 189 |
| Colon added, and I tell the reader the currency is rupiah (my declaration, not in the receipts) | not possible | 118 / 4 / 71 |
| As built, and I declare rupiah | not possible | 13 / 0 / 180 |

Vendor and date: still empty on all 193, because receipts have no `Vendor:` or `Date:` lines. `check_invoice()` still calls all of them malformed.

What this says:

- The headline row does not move. The reader only takes a total from a line like `Total: 60.000`, and receipts say `TOTAL 60.000`. I did not loosen that, because it is a separate decision.
- Without outside help the reader mostly still refuses. A receipt carries nothing that settles `60.000`: no currency line, no locale line, and item rows that are not in the lab's `- name | 2 x 5.00 = 10.00` layout.
- When I declare rupiah, the number fix works: 117 of the 118 correct totals are written with a thousands dot or comma. That row rests on a fact I supplied for the whole data set, so it shows the most the fix can do. It does not show what the reader does on its own.
- The 4 wrong ones all have the same cause, and it is not the number format. On those receipts the line called `TOTAL` is the amount before tax, and the real total sits on a `GRAND TOTAL` line. The reader took the first. In v1 these four were refused only because the number could not be read. This is a risk to know about before any receipt-style input is used. The development slice (26 receipts) had the same problem once.

### What happened: council payments (April to June, 21,099 payment vouchers)

Both versions saw January to March first as history, and only April to June flags are counted. The "before" is the v1 code run the same way (a copy of it is in `real-data/v1/`).

| Measure | v1 | v2 |
|---|---|---|
| Flagged as possible duplicate | 6,144 (29.1%) | 4,184 (19.8%) |
| Same, with no history (April to June alone) | 6,144 (29.1%) | 5,254 (24.9%) |
| Flags that joined two different supplier endings (for example `X` and `X LTD`) | 181 | 0 |
| Sum of flagged voucher totals | £9.49m | £7.06m |

Of v1's 6,144 flags, v2 no longer raises 2,051 (1,873 because of a weekly or monthly pattern, 97 because the repeat is more than 3 days away, 77 because the purpose labels differ, 4 because the supplier key changed). v2 raises 91 that v1 did not, all repeats one to three days apart.

Hand check, fresh sample of 30 v2 flags (my labels, from the supplier, amount, dates, purposes, how many other suppliers got the same amount, and the history of that supplier and amount):

| My label | Flags (of 30) | v1 check (different sample and rule, January to June) |
|---|---|---|
| Looks legitimate | 19 | 21 |
| Looks suspicious | 5 | 3 |
| Unsure | 6 | 6 |

Second check: 30 of the flags v2 dropped. 28 look legitimate, 2 unsure, none suspicious. So the rules dropped fixed-rate payments and did not drop anything that looked wrong.

Test with planted copies (synthetic, April to June, 300 copies of real payments inserted with a new voucher number): copies on the same day were flagged 283 of 300; copies 1 or 3 days later 300 of 300; copies 10 days later 12 of 300, as intended. The 17 missed same-day copies were all of payments that already repeat in a pattern (60 of 77 caught there; 223 of 223 caught elsewhere).

### What still fails

- About one payment in five is still flagged, and the hand check says most flagged payments still look legitimate (19 of 30). The pattern rule needs three dates before it trusts a pattern, so the first two cycles of every fixed-rate arrangement are flagged. Care homes that start a run in the scoring months show up as flags. A smarter rule, for example treating a known payment-run day as a batch, would remove more, but I would have to tune it on a new set of months. I did not, because I had already looked at April to June.
- A real double payment that sits inside a standing pattern looks like one more normal payment and is not flagged. The planted test shows this: 17 of 77.
- This data has no invoice or reference number per payment, only a voucher number. The "different references" rule can only use the purpose label (239 cases in the scoring months).
- The "different purpose" rule and the 3-day window were chosen on the development months and checked once on the scoring months. I have no independent record of which payments were really paid twice, so no flag here is a confirmed double payment.
- Receipts: nothing here fixes the label problem (`TOTAL` before tax) or the missing colon.
- June 2025 is a short file (74 vouchers), so the three-month figure is mostly April and May.

### Checks on the code

- Existing tests: the 203 old tests still pass. Three tests and one contract were edited, because behaviour changed on purpose: two invoices with the same supplier, amount and date but different purchase order references used to be flagged, and now are not. The edited copies carry the same reference, or none, and are still flagged. Reasons are in `PROTOCOL-v2.md`, Deviation 3.
- New tests: 74, in `tests/test_v2.py`, covering both readings of `1.234`, `1,234`, `60.000`, `1.000`, `0.500`, the evidence in each order, evidence that conflicts, mixed styles, and each duplicate rule and its edges. Total now 277, all passing (`evidence/v2-09-unittest-v.txt`).
- Mutation check: 148 planted one-line bugs (96 old, 52 new), 148 caught (`evidence/v2-08-mutate.txt`). Three old mutants were re-pointed at the new duplicate code because the code they targeted was replaced. All are hand-written by me.
- The synthetic evaluation (`scripts/evaluate.py`, sets A, B, C) gives byte-identical output before and after (`evidence/v2-10-evaluate.txt`).

### Files added

`PROTOCOL-v2.md` (rules, tuning method, freeze record, deviations), `run_cord_v2.py`, `run_council_v2.py`, `score_handchecks_v2.py`, `fetch_dev_cord.sh`, `v1/` (a read-only copy of the v1 code for the "before" numbers), `samples/handcheck_v2_labels_masked.json`, `evidence/v2-*.txt`.
