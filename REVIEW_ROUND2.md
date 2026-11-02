# Review round 2: findings and decisions

Inputs: `fable-docmatch.md` (Claude, 17 findings) and `codex-docmatch.md` (ChatGPT, 20 numbered findings plus 8 verdict lines). One row per numbered finding: **37 findings, 37 rows**.

Row count check: Fable 17 rows (F1 to F17), Codex 20 rows (C1 to C20). Decisions: ACCEPT 31, PARTIAL 4 (F11, C6, C7, C11), REJECT 2 (F17, C10).

Method: I traced every finding to the code at HEAD 466018f before changing anything. Nothing here is VERIFIED. All results are my own local runs; the README says what they cover.

| # | Sev | Finding | Decision | What changed or why not |
|---|---|---|---|---|
| F1 | P0 | Same PO paid twice through fresh invoice numbers | ACCEPT | PO consumption in pipeline (`po_already_matched`, `po_overbilled`); extra duplicate key (vendor, total, currency, PO); contract `same_po_billed_twice_flagged`; set C C-B01, C-B02, C-B08, C-B09, C-B10; tests PoConsumption |
| F2 | P1 | PO reference lost by colon-sensitive regex, wrong twin auto-matched | ACCEPT | Tolerant label grammar (Your PO, PO Number, Order Ref, Purchase Order No); PO-shaped token anywhere with no readable reference refuses Tier 2 (`unlabelled_ref_present`); contract `odd_po_label_matches_the_named_po`; C-N01..N03, C-N12, C-T02 |
| F3 | P1 | Decimal-comma totals read at 100x | ACCEPT | Strict money grammar: decimal-comma, exponent, 3-decimal and ungrouped-comma values are refused (`total_unparseable`); contract `decimal_comma_total_not_read_as_whole`; C-T03, C-T04 |
| F4 | P1 | Confidence scores gate nothing | ACCEPT | match() refuses auto-match on 0 < confidence < 1 for vendor, currency, total, date; invoice-number fallback gated; free-text date fallback and symbol-inferred currency removed; mutants confidence_gate_* |
| F5 | P1 | README claim 'frozen before the thresholds were written' is false | ACCEPT | README section 'How the sets were handled' states what git shows (3cedf49 then b875dd5, six minutes apart, rules already in the set meta); claim withdrawn |
| F6 | P1 | 31/31 mutants hand-picked; 9 of 18 unplanned mutants survived | ACCEPT | 8 of the 9 survivors re-applied as killed mutants (the 9th, po_colon_optional, mutates code that no longer exists); 49 new round 2 mutants; score reported in three groups with the hand-picked caveat; 96/96 killed |
| F7 | P2 | Suffix stripping makes different legal entities identical at Tier 2 | ACCEPT | vendor_identity = name + canonical legal suffix at Tier 2; suffix disagreement fails Tier 1; Limited equals Ltd; tests VendorIdentity; C-T12 |
| F8 | P2 | Line-sum control skipped when no item line parses | ACCEPT | Every bullet row must parse or `items_unparsed`; Items header with no rows flagged; tab and capital X accepted; subtotal+tax checked without items; C-T10, C-T18, C-N09 |
| F9 | P2 | 0/36 measured on single-invoice batches only | ACCEPT | Labelled batch cases (10 cases, 20 invoices) in set C, scored in evaluate.py with a 'POs matched more than once' count; README table labels single-invoice rows |
| F10 | P2 | Label encodes a risky rule as correct (B-N07) | ACCEPT | `twin_outside_window` makes it ambiguous. A-N07 relabelled (tuned set). B-N07 NOT edited (set B stays byte-identical): B now shows 19/20 correct auto-match, reported in the README |
| F11 | P2 | Tolerance symmetric and unbounded in absolute terms | PARTIAL | Absolute over-billing cap max_over 50.00 and directional rule added with boundary tests. Residual: a 1.00 PO still accepts a 2.00 invoice (floor 1.00); documented, not fixed |
| F12 | P3 | Quantity x unit never compared with line amount | ACCEPT | `line_arithmetic` check (1 cent, half-up); C-T09 |
| F13 | P3 | `\s*` after labels crosses the newline | ACCEPT | All label regexes use [ \t]*; tests label_does_not_read_next_line; C-T25 |
| F14 | P3 | Amount Due auto-matches like Total | ACCEPT | Amount Due only ever 0.7 confidence and gated; never used when a Total line exists but is unparseable; differs-from-total flagged; C-T07 |
| F15 | P3 | Vendor fuzzy threshold untested; README claim loose | ACCEPT | Boundary test pair (0.80 fails, 0.97 passes, 0.895 is Tier 3 only); fuzzy_0.5 mutant killed; README states the fuzzy test is not identity |
| F16 | P3 | CI workflow never executed; working-directory wrong for standalone repo | ACCEPT | Workflow at the lab root without working-directory, matrix 3.9 to 3.13; README says it runs only when the lab is its own repository. Not executed here |
| F17 | P3 | check-confidential.sh at repository root names the employer vocabulary | REJECT | The file is outside this lab folder (task scope forbids touching it). Recommendation stands: publish only the lab folder or move the pattern list to an untracked file. Lab folder re-scanned clean |
| C1 | P1 | Mixed currency across parts aggregates under last arrival's currency | ACCEPT | PartTracker rejects parts that disagree on currency or date; aggregate built from part 1 explicitly; C-B05, tests PartsHardening |
| C2 | P1 | Prefix parsing: 1.000,00 read as 1.00, 100.00e3, PO-1.9 read as PO-1 | ACCEPT | Whole-value grammar for amounts and references; `po_ref_invalid`; C-T03, C-T14 |
| C3 | P1 | Quantity x unit unchecked; capital X drops row and bypasses validation | ACCEPT | Same fixes as F8 and F12 |
| C4 | P1 | Conflicting currency evidence; bare $ treated as USD | ACCEPT | `conflicting_currency`, `conflicting_currency_symbols`, `currency_symbol_only`, `currency_invalid`; C-T05, C-T06 |
| C5 | P1 | 'Part 1 of 2' and 'Part: -1 of 2' ignored | ACCEPT | Part grammar with optional colon and slash form; every recognisable-but-invalid declaration is `part_invalid`; C-T17, C-B06 |
| C6 | P1 | Same-name different legal entities auto-match | PARTIAL | Legal suffix now part of identity (see F7). Supplier IDs / approved alias mapping not added: the synthetic data model has no vendor ID field. Residual stated in the README |
| C7 | P1 | Two invoices match the same PO; copied reference selects the wrong twin | PARTIAL | PO allocation tracked (F1) and `closer_candidate_exists` refuses a worse-fitting reference when a closer same-vendor PO exists. Residual: tolerance and uniqueness cannot prove order identity; a copied reference to an unbilled PO still matches. Stated in the README |
| C8 | P1 | Huge part count stalls completion check | ACCEPT | n <= 100 enforced in extract and in the tracker; completeness is a count compare, not set(range(n)); test large_n_tracker_refuses |
| C9 | P2 | Fingerprint ignores goods and subtotal; corrections silently skipped | ACCEPT | Fingerprint covers total, date, PO, currency, subtotal, tax, item rows; changed content is `duplicate_id_conflict`; C-B04 |
| C10 | P2 | Registering before success lets an unknown-ref invoice poison duplicate detection | REJECT | Failing toward a human is the safe direction: the later invoice is flagged, never lost or paid unseen. Registering only after success would let both a reviewed and an auto-matched copy be paid. Arrival-order dependence is documented in the README and pinned by test poisoning_is_fail_safe_and_documented |
| C11 | P2 | Concurrent check/register interleaving; new instance reprocesses | PARTIAL | process() now serialised by a lock (test forces the interleaving; mutant lock_removed killed). Persistence and cross-instance atomicity not added: documented as in-memory, single-instance scope |
| C12 | P2 | 8-char SHA1 prefix collides; lone surrogate crashes | ACCEPT | Full SHA-256 over backslashreplace-encoded text; tests unparsed_keys_use_full_digest, lone_surrogate_does_not_crash |
| C13 | P2 | 2026-02-31 auto-matches; NaN PO total aborts processing | ACCEPT | Calendar-validated dates (`date_invalid`); money() refuses NaN; per-document `processing_error` isolation; C-T08 |
| C14 | P2 | Population-rate bound claimed from hand-selected cases | ACCEPT | README: intervals described as a description of these cases only, sampling assumption stated, both denominators reported |
| C15 | P2 | Git cannot prove writing order or no consultation | ACCEPT | README says 'committed before the code commit', rules already in the set meta, same author; independent set still absent (C is same-model) |
| C16 | P2 | set_a meta says thresholds were tuned; README denies it | ACCEPT | README and HANDOFF withdraw the no-tuning claim; A treated as tuned, defaults as author choices |
| C17 | P2 | Evaluation counts any non-MATCH as flagged, even silent drops | ACCEPT | evaluate.py requires exactly one disposition and a queue entry for flagged DocMatch cases; `dropped` reported (0 in all sets) |
| C18 | P2 | Dropping currency from the fingerprint survives all tests | ACCEPT | Test same_number_changed_currency_is_conflict; mutant fingerprint_drops_currency killed |
| C19 | P2 | Mutation harness treats every nonzero result as killed | ACCEPT | mutate.py classifies KILLED (tests ran and failed) vs CRASH (timeout, import error, zero tests ran) vs SURVIVED, prints the first failing test; 0 crashes in the final run |
| C20 | P3 | Workflow working-directory breaks a standalone repository | ACCEPT | Same fix as F16 |

## Verdict lines of the Codex review (not numbered findings)
- Tests INSUFFICIENT, naive contract tests accept arbitrary crashes: accepted. The naive check now counts only assertion failures; the naive baseline lacked a queue and now fails that contract by explicit assertion.
- 'T13/T14/T16 actually return INVALID': cosmetic status label for reasons raised by validation; the case still ends in needs_review. Unchanged.
- Privacy note (commit metadata carries the author's name and email): out of this lab's control; not changed.
- Shared scenario templates between A and B prevent an independence claim: accepted, the README makes no independence claim.
- OWASP-style whole-field validation gap: addressed by the whole-value grammar for amounts, dates, references and parts.

## Order of work and first-run record
I wrote set C after the code fixes and before its first run. First run (saved in `evidence/evaluate-set-c-first-run.txt`): DocMatch 0 false auto-matches of 39, 25/25 traps flagged, 14/14 correct auto, 20/20 batch invoices right. No source file changed after that run (only tests and the mutation list), so the first run equals the final run. The cases were written knowing the fixes, so a perfect score was expected and is not evidence of discovery power.
Mutation: the first full run of the new list had 4 survivors (amount due fallback after a garbled total, fingerprint without subtotal, aggregate currency from the wrong part, lock removed). Three got tests. The aggregate-currency mutant is equivalent (the tracker already forces one currency), so I removed it from the list.
