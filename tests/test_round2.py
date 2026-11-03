"""Round 2 regressions: each test names the review finding it closes (F = Fable, C = Codex)."""
import threading
import time
import unittest
from decimal import Decimal as D

from helpers import inv_text, make_po
from docmatch import DocMatch, MatchConfig
from docmatch.extract import Invoice, extract
from docmatch.match import match, tolerance, vendor_similarity, within_tolerance
from docmatch.util import money
from docmatch.validate import DuplicateDetector, PartTracker, check_invoice


def run(pos, *texts):
    return DocMatch(pos).process(list(texts))


def reasons(r):
    return [x for e in r["needs_review"] for x in e["reasons"]]


class PoConsumption(unittest.TestCase):  # F1 (P0), C7
    def test_second_invoice_same_po_goes_to_review(self):
        # amounts differ by 1.00 so the duplicate detector does not fire: the PO-level control is what stops it
        r = run([make_po(total="100.00")], inv_text(no="INV-1", date="2026-03-10"),
                inv_text(no="INV-2", date="2026-03-12", lines=(("w", 1, "101.00"),)))
        self.assertEqual([e["invoice_no"] for e in r["auto_matched"]], ["INV-1"])
        self.assertEqual(reasons(r), ["po_already_matched", "po_overbilled"])

    def test_overbilling_reason_is_added(self):
        r = run([make_po(total="100.00")], inv_text(no="INV-1"),
                inv_text(no="INV-2", date="2026-03-12", lines=(("w", 1, "101.00"),)))
        self.assertIn("po_overbilled", reasons(r))
        self.assertEqual(len(r["auto_matched"]), 1)

    def test_same_vendor_new_number_new_name_form(self):
        r = run([make_po(total="100.00")], inv_text(no="INV-1"),
                inv_text(no="INV-7", date="2026-03-20", vendor="Brightwater Supplies Limited"))
        self.assertEqual(len(r["auto_matched"]), 1)

    def test_consumed_across_process_calls(self):
        d = DocMatch([make_po(total="100.00")])
        d.process([inv_text(no="INV-1")])
        r = d.process([inv_text(no="INV-2", date="2026-03-12", lines=(("w", 1, "99.00"),))])
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertIn("po_already_matched", reasons(r))
        self.assertIn("po_overbilled", reasons(r))  # 100.00 + 99.00 is far beyond a 100.00 PO

    def test_rekeyed_copy_with_po_and_new_date_is_possible_duplicate(self):
        d = DuplicateDetector()
        d.register(extract(inv_text(no="INV-1", date="2026-03-10")))
        self.assertEqual(d.check(extract(inv_text(no="INV-2", date="2026-03-11"))), "possible_duplicate")

    def test_other_po_same_amount_not_duplicate(self):
        d = DuplicateDetector()
        d.register(extract(inv_text(no="INV-1", po="PO-1", date="2026-03-10")))
        self.assertIsNone(d.check(extract(inv_text(no="INV-2", po="PO-2", date="2026-03-11"))))

    def test_different_currency_not_po_duplicate(self):
        d = DuplicateDetector()
        d.register(extract(inv_text(no="INV-1", cur="USD", date="2026-03-10")))
        self.assertIsNone(d.check(extract(inv_text(no="INV-2", cur="EUR", date="2026-03-11"))))


class PoReferenceReading(unittest.TestCase):  # F2, F13, C2
    def test_label_variants(self):
        for label in ("Your PO: PO-1", "PO Number PO-1", "Order Ref: PO-1", "Purchase Order No. PO-1", "PO # PO-1", "Purchase Order PO-1"):
            inv = extract(f"Invoice No: A1\n{label}\nTotal: 1.00")
            self.assertEqual(inv.po_ref, "PO-1", label)

    def test_named_po_wins_over_twin(self):
        pos = [make_po("PO-1", date="2025-11-01"), make_po("PO-2", date="2026-03-01")]
        text = inv_text(po=None).replace("Invoice No: INV-1", "Invoice No: INV-1\nYour PO: PO-1")
        r = run(pos, text)
        self.assertEqual([(e["po_id"]) for e in r["auto_matched"]], ["PO-1"])

    def test_unlabelled_token_refuses_tier2(self):
        pos = [make_po("PO-1", date="2025-11-01"), make_po("PO-2", date="2026-03-01")]
        text = inv_text(po=None) + "\nNote: pay against PO-1 please"
        r = run(pos, text)
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertIn("unlabelled_ref_present", reasons(r))

    def test_word_postage_is_not_a_po(self):
        inv = extract("Invoice No: A1\nPOSTAGE: 5.00\nTotal: 5.00")
        self.assertIsNone(inv.po_ref)
        self.assertEqual(inv.ref_tokens, [])
        self.assertEqual(inv.issues, [])  # not even recognised as a malformed PO line

    def test_invalid_reference_value_refused(self):
        inv = extract("Invoice No: A1\nPO: PO-1.9\nTotal: 5.00")  # C2: prefix parsing used to give PO-1
        self.assertIsNone(inv.po_ref)
        self.assertIn("po_ref_invalid", inv.issues)

    def test_conflicting_references(self):
        inv = extract("Invoice No: A1\nPO: PO-1\nPurchase Order: PO-2\nTotal: 5.00")
        self.assertIsNone(inv.po_ref)
        self.assertIn("conflicting_po_ref", inv.issues)

    def test_empty_label_does_not_read_next_line(self):
        inv = extract("Invoice No:\nPO: PO-1\nVendor: Acme\nTotal: 5.00")
        self.assertIsNone(inv.invoice_no)
        self.assertEqual(inv.po_ref, "PO-1")
        inv = extract("Invoice No: A1\nPO:\nVendor: Acme Ltd\nTotal: 5.00")
        self.assertIsNone(inv.po_ref)

    def test_prefix_ref_not_matched(self):  # F6 mutant ref_prefix
        r = run([make_po("PO-10")], inv_text(po="PO-1"))
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertIn("po_ref_unknown", reasons(r))

    def test_na_variants(self):
        for v in ("N/A", "NA", "none", "TBD"):
            self.assertIsNone(extract(f"Invoice No: A1\nPO: {v}\nTotal: 1.00").po_ref, v)
        self.assertEqual(extract("Invoice No: A1\nPO: NAB-7\nTotal: 1.00").po_ref, "NAB-7")


class MoneyParsing(unittest.TestCase):  # F3, C2
    def test_decimal_comma_refused(self):
        for t in ("12,50", "1.250,00", "1.000,00", "100.00e3", "1,250", "1.000", "12.345"):
            self.assertIsNone(money(t), t)

    def test_decimal_comma_total_goes_to_review(self):
        r = run([make_po("PO-1", total="1250.00")], inv_text(lines=(("w", 1, "1"),)).replace("Total: 1.00", "Total: 12,50"))
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertTrue({"total_unparseable", "malformed"} <= set(reasons(r)))

    def test_good_formats(self):
        self.assertEqual(money("1,250.50"), D("1250.50"))
        self.assertEqual(money("$22.5"), D("22.50"))
        self.assertEqual(money("-5"), D("-5.00"))
        self.assertEqual(money("1,25.00") is None, True)
        self.assertIsNone(money("--5"))

    def test_nan_po_total_does_not_crash(self):
        r = run([make_po("PO-1", total="NaN")], inv_text())
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertEqual(len(r["needs_review"]), 1)


class ConfidenceGate(unittest.TestCase):  # F4, F14
    def test_amount_due_only_never_auto(self):
        text = inv_text().replace("Total: 100.00", "Amount Due: 100.00")
        r = run([make_po(total="100.00")], text)
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertIn("low_confidence_total", reasons(r))

    def test_garbled_total_does_not_fall_back_to_amount_due(self):
        text = inv_text().replace("Total: 100.00", "Total: 100,00\nAmount Due: 100.00")
        inv = extract(text)
        self.assertIsNone(inv.total)
        self.assertIn("total_unparseable", inv.issues)
        r = run([make_po()], text)
        self.assertEqual(len(r["auto_matched"]), 0)

    def test_amount_due_differing_from_total_flagged(self):
        text = inv_text() + "\nAmount Due: 40.00"
        inv = extract(text)
        self.assertIn("amount_due_differs_from_total", inv.issues)

    def test_match_gates_each_field_directly(self):
        pos = [make_po(total="100.00")]
        for f in ("vendor", "currency", "total", "date"):
            inv = extract(inv_text(po=None if f == "date" else "PO-1"))
            self.assertEqual(match(inv, pos).status, "MATCH", f)
            inv.conf[f] = 0.6
            res = match(inv, pos)
            self.assertEqual(res.status, "AMBIGUOUS", f)
            self.assertEqual(res.reasons, ["low_confidence_" + f])

    def test_zero_confidence_is_not_double_reported(self):
        inv = extract(inv_text())
        inv.conf["currency"] = 0.0
        inv.currency = None
        self.assertEqual(match(inv, [make_po()]).reasons, ["currency_mismatch"])

    def test_invoice_number_fallback_gated(self):
        text = inv_text().replace("Invoice No: INV-1", "Ref INV-1")
        self.assertIn("low_confidence_invoice_no", check_invoice(extract(text)))

    def test_unlabelled_date_is_malformed(self):  # F4 date fallback removed
        text = inv_text().replace("Date: 2026-03-10", "Ship ref: 2025-01-05")
        r = run([make_po()], text)
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertIn("malformed", reasons(r))

    def test_invalid_calendar_date(self):  # C13
        r = run([make_po()], inv_text(date="2026-02-31"))
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertIn("date_invalid", reasons(r))


class CurrencyEvidence(unittest.TestCase):  # C4, F4
    def test_symbol_only_is_not_usd(self):
        text = inv_text().replace("Currency: USD\n", "").replace("Total: 100.00", "Total: $100.00")
        r = run([make_po()], text)
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertIn("currency_symbol_only", reasons(r))

    def test_code_and_symbol_conflict(self):
        text = inv_text().replace("Total: 100.00", "Total: €100.00")
        r = run([make_po()], text)
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertIn("conflicting_currency", reasons(r))

    def test_code_and_matching_symbol_ok(self):
        text = inv_text().replace("Total: 100.00", "Total: $100.00")
        self.assertEqual(len(run([make_po()], text)["auto_matched"]), 1)

    def test_two_currency_lines(self):
        inv = extract(inv_text() + "\nCurrency: EUR")
        self.assertIn("conflicting_currency", inv.issues)

    def test_bad_currency_value(self):
        self.assertIn("currency_invalid", extract("Invoice No: A\nCurrency: dollars\nTotal: 5.00").issues)

    def test_symbol_set_conflict(self):
        inv = extract("Invoice No: A\nSubtotal: $5.00\nTotal: €5.00")
        self.assertIn("conflicting_currency_symbols", inv.issues)


class ItemRows(unittest.TestCase):  # F8, F12, C3
    def test_tab_separator_parses(self):
        text = inv_text().replace(" | ", "\t")
        self.assertEqual(len(extract(text).items), 1)

    def test_capital_x_parses(self):
        self.assertEqual(len(extract(inv_text().replace(" x ", " X ")).items), 1)

    def test_unparsed_row_flagged_not_dropped(self):
        text = inv_text().replace("Widget | 2 x 50.00 = 100.00", "Widget, qty 2, 100.00")
        r = run([make_po()], text)
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertIn("items_unparsed", reasons(r))

    def test_items_header_without_rows(self):
        inv = extract("Invoice No: A1\nItems:\nTotal: 5.00")
        self.assertIn("items_unparsed", inv.issues)

    def test_line_arithmetic(self):
        text = inv_text().replace("2 x 50.00 = 100.00", "2 x 500.00 = 100.00")
        r = run([make_po()], text)
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertIn("line_arithmetic", reasons(r))

    def test_line_arithmetic_one_cent_rounding_ok(self):
        text = inv_text(lines=(("Bolt", 3, "0.335"),), total=None)
        inv = extract(text)
        self.assertNotIn("line_arithmetic", check_invoice(inv))

    def test_subtotal_without_items_checked(self):
        text = "\n".join(["Invoice No: A1", "Vendor: Acme Ltd", "Date: 2026-03-10", "Currency: USD",
                          "Subtotal: 90.00", "Tax: 0.00", "Total: 100.00"])
        self.assertIn("total_mismatch_subtotal", check_invoice(extract(text)))

    def test_subtotal_tolerance_is_one_cent(self):
        text = inv_text().replace("Subtotal: 100.00", "Subtotal: 100.50")
        self.assertIn("subtotal_mismatch", check_invoice(extract(text)))

    def test_label_does_not_read_next_line(self):
        inv = extract("Invoice No: A1\nVendor:\nDate: 2026-03-10\nTotal: 5.00")
        self.assertIsNone(inv.vendor)


class VendorIdentity(unittest.TestCase):  # F7, F15, C6
    def test_inc_vs_co_no_ref_not_auto(self):
        r = run([make_po(vendor="Kestrel Co")], inv_text(po=None, vendor="Kestrel Inc"))
        self.assertEqual(len(r["auto_matched"]), 0)

    def test_suffix_vs_bare_name_not_auto(self):
        r = run([make_po(vendor="Kestrel")], inv_text(po=None, vendor="Kestrel Inc"))
        self.assertEqual(len(r["auto_matched"]), 0)

    def test_limited_equals_ltd(self):
        r = run([make_po(vendor="Kestrel Ltd")], inv_text(po=None, vendor="Kestrel Limited"))
        self.assertEqual(len(r["auto_matched"]), 1)

    def test_tier1_suffix_mismatch(self):
        r = run([make_po(vendor="Kestrel Co")], inv_text(vendor="Kestrel Inc"))
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertIn("vendor_mismatch", reasons(r))

    def test_similarity_threshold_boundary(self):
        self.assertAlmostEqual(vendor_similarity("Brightwater Supplies", "Brightwater Services"), 0.80, places=2)
        r = run([make_po(vendor="Brightwater Supplies")], inv_text(vendor="Brightwater Services"))
        self.assertIn("vendor_mismatch", reasons(r))  # 0.80 < 0.85: fails Tier 1
        r = run([make_po(vendor="Brightwater Supplies Ltd")], inv_text(vendor="Brightwater Suplies Ltd"))
        self.assertEqual(len(r["auto_matched"]), 1)  # 0.97 >= 0.85: passes Tier 1 (fuzzy, by design)
        r = run([make_po(vendor="Brightwater Supplies Ltd")], inv_text(po=None, vendor="Brightwater Supply Ltd"))
        self.assertEqual(len(r["auto_matched"]), 0)  # 0.895 passes fuzzy but only as Tier 3, never auto
        self.assertIn("weak_tier_only", reasons(r))


class MissingCurrency(unittest.TestCase):  # F6 mutant pick_no_cur_guard
    def test_no_currency_anywhere_never_auto(self):
        text = inv_text(po="PO-1").replace("Currency: USD\n", "")
        r = run([make_po(cur="")], text)
        self.assertEqual(len(r["auto_matched"]), 0)
        r = run([make_po(cur="")], inv_text(po=None).replace("Currency: USD\n", ""))
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertIn("currency_mismatch", reasons(r))


class Tolerance(unittest.TestCase):  # F11
    def test_over_billing_capped(self):
        pos = [make_po(total="10000.00")]
        r = run(pos, inv_text(lines=(("w", 1, "10100.00"),)))  # +1% but +100.00 > cap 50.00
        self.assertIn("total_mismatch", reasons(r))
        r = run(pos, inv_text(lines=(("w", 1, "10050.00"),)))  # exactly at the cap
        self.assertEqual(len(r["auto_matched"]), 1)

    def test_under_billing_uses_relative_band(self):
        r = run([make_po(total="10000.00")], inv_text(lines=(("w", 1, "9900.00"),)))  # -1%
        self.assertEqual(len(r["auto_matched"]), 1)

    def test_cap_configurable(self):
        cfg = MatchConfig(max_over=D("500.00"))
        self.assertTrue(within_tolerance(D("10100"), D("10000"), cfg))

    def test_tolerance_uses_absolute_po_total(self):
        self.assertEqual(tolerance(D("-100.00"), MatchConfig()), D("2.00"))

    def test_none_totals(self):
        self.assertFalse(within_tolerance(None, D("1"), MatchConfig()))


class WindowTwins(unittest.TestCase):  # F10
    def test_twin_outside_window_is_ambiguous(self):
        pos = [make_po("PO-OLD", date="2025-11-01"), make_po("PO-NEW", date="2026-03-01")]
        r = run(pos, inv_text(po=None, date="2026-03-10"))
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertIn("twin_outside_window", reasons(r))

    def test_other_currency_twin_outside_window_ignored(self):
        pos = [make_po("PO-OLD", cur="EUR", date="2025-11-01"), make_po("PO-NEW", date="2026-03-01")]
        self.assertEqual(len(run(pos, inv_text(po=None, date="2026-03-10"))["auto_matched"]), 1)

    def test_closer_candidate_with_ref(self):  # C7: a copied reference selecting the wrong twin
        pos = [make_po("PO-1", total="101.00"), make_po("PO-2", total="100.00")]
        r = run(pos, inv_text(po="PO-1"))
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertIn("closer_candidate_exists", reasons(r))

    def test_ref_to_closest_is_fine(self):
        pos = [make_po("PO-1", total="100.00"), make_po("PO-2", total="101.00")]
        self.assertEqual(len(run(pos, inv_text(po="PO-1"))["auto_matched"]), 1)


class PartsHardening(unittest.TestCase):  # C1, C5, C8
    def parts(self, p1_cur="USD", p2_cur="USD"):
        a = inv_text(lines=(("w", 1, "50.00"),), part=(1, 2), cur=p1_cur)
        b = inv_text(lines=(("w", 1, "50.00"),), part=(2, 2), cur=p2_cur)
        return a, b

    def test_mixed_currency_parts_conflict_either_order(self):
        for order in (0, 1):
            a, b = self.parts("EUR", "USD")
            r = run([make_po(total="100.00")], *([a, b] if order == 0 else [b, a]))
            self.assertEqual(len(r["auto_matched"]), 0, order)
            self.assertIn("part_conflict", reasons(r))

    def test_mixed_date_parts_conflict(self):
        a = inv_text(lines=(("w", 1, "50.00"),), part=(1, 2))
        b = inv_text(lines=(("w", 1, "50.00"),), part=(2, 2), date="2026-03-11")
        r = run([make_po(total="100.00")], a, b)
        self.assertEqual(len(r["auto_matched"]), 0)

    def test_part_syntax_without_colon(self):
        self.assertEqual(extract(inv_text(part=(1, 2)).replace("Part: 1 of 2", "Part 1 of 2")).part, (1, 2))
        self.assertEqual(extract(inv_text(part=(1, 2)).replace("Part: 1 of 2", "Part 1/2")).part, (1, 2))

    def test_invalid_part_declarations_flagged(self):
        for decl in ("Part: -1 of 2", "Part: 0 of 2", "Part: 3 of 2", "Part: 1 of 1000000000000000000000000000000",
                     "Part: 1 of 101", "Part: one of two"):
            inv = extract(inv_text().replace("Currency: USD", "Currency: USD\n" + decl))
            self.assertIn("part_invalid", inv.issues, decl)
            self.assertIsNone(inv.part)
            r = run([make_po()], inv_text().replace("Currency: USD", "Currency: USD\n" + decl))
            self.assertEqual(len(r["auto_matched"]), 0, decl)

    def test_two_part_lines(self):
        t = inv_text(part=(1, 2)).replace("Items:", "Part: 2 of 2\nItems:")
        self.assertIn("part_invalid", extract(t).issues)

    def test_part_boundaries(self):
        self.assertEqual(extract(inv_text().replace("Currency: USD", "Currency: USD\nPart: 100 of 100")).part, (100, 100))
        self.assertEqual(extract(inv_text().replace("Currency: USD", "Currency: USD\nPart: 1 of 1")).part, (1, 1))

    def test_large_n_tracker_refuses(self):
        inv = extract(inv_text(part=(1, 2)))
        inv.part = (1, 10 ** 30)
        self.assertEqual(PartTracker().add(inv)[0], "conflict")

    def test_aggregate_metadata_from_part_one(self):
        a, b = self.parts()
        r = run([make_po(total="100.00")], b, a)
        self.assertEqual(r["auto_matched"][0]["total"], "100.00")


class Fingerprint(unittest.TestCase):  # C9, C18
    def test_same_number_changed_subtotal_is_conflict(self):
        d = DuplicateDetector()
        d.register(extract(inv_text(lines=(("w", 1, "90.00"),))))
        self.assertEqual(d.check(extract(inv_text(lines=(("w", 1, "90.00"),), tax="0.00").replace("Tax: 0.00", "Tax: 0.01"))), "id_conflict")

    def test_same_number_changed_subtotal_only_is_conflict(self):
        base = "\n".join(["Invoice No: A1", "PO: PO-1", "Vendor: Acme Ltd", "Date: 2026-03-10", "Currency: USD",
                          "Subtotal: {}", "Tax: 0.00", "Total: 100.00"])
        d = DuplicateDetector()
        d.register(extract(base.format("100.00")))
        self.assertEqual(d.check(extract(base.format("90.00"))), "id_conflict")

    def test_same_number_changed_items_is_conflict(self):
        d = DuplicateDetector()
        d.register(extract(inv_text(lines=(("Widget", 2, "50.00"),))))
        other = inv_text(lines=(("Gadget", 4, "25.00"),))
        self.assertEqual(d.check(extract(other)), "id_conflict")

    def test_same_number_changed_currency_is_conflict(self):
        d = DuplicateDetector()
        d.register(extract(inv_text(cur="USD")))
        self.assertEqual(d.check(extract(inv_text(cur="EUR"))), "id_conflict")

    def test_correction_not_silently_skipped(self):
        d = DocMatch([make_po(total="100.00")])
        d.process([inv_text(lines=(("w", 1, "90.00"),))])
        r = d.process([inv_text(lines=(("w", 1, "100.00"),))])
        self.assertEqual(len(r["skipped"]), 0)
        self.assertIn("duplicate_id_conflict", reasons(r))


class PipelineRobustness(unittest.TestCase):  # C10 (rejected, documented), C11, C12, C13
    def test_unparsed_keys_use_full_digest(self):
        d = DocMatch([make_po()])
        r = d.process(["garbage one", "garbage two"])
        keys = {e.invoice_key for e in r["queue"]}
        self.assertEqual(len(keys), 2)
        self.assertTrue(all(len(k[1]) > 40 for k in keys))

    def test_lone_surrogate_does_not_crash(self):
        r = DocMatch([make_po()]).process(["bad \ud800 text"])
        self.assertEqual(len(r["needs_review"]), 1)

    def test_bad_po_record_isolated(self):
        r = DocMatch([make_po(), 5]).process([inv_text(no="INV-1"), inv_text(no="INV-2", date="2026-04-01")])
        self.assertEqual(len(r["needs_review"]), 2)
        self.assertTrue(any(x.startswith("processing_error") for x in reasons(r)))

    def test_concurrent_identical_submissions_one_match(self):
        d = DocMatch([make_po()])
        outs = []
        orig = d.dups.check

        def slow_check(inv):  # widen the check-then-register window so an unlocked pipeline would double-match
            r = orig(inv)
            time.sleep(0.005)
            return r
        d.dups.check = slow_check

        def go():
            outs.append(d.process([inv_text()]))
        ts = [threading.Thread(target=go) for _ in range(12)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(sum(len(o["auto_matched"]) for o in outs), 1)
        # serialised: the other 11 are clean resubmissions, not racing duplicates that only the PO control caught
        self.assertEqual(sum(len(o["skipped"]) for o in outs), 11)
        self.assertEqual(sum(len(o["needs_review"]) for o in outs), 0)

    def test_poisoning_is_fail_safe_and_documented(self):
        # C10: an earlier invoice with no PO reference makes a later same vendor/total/date invoice a possible duplicate.
        # Deliberately kept: both land in front of a human, neither is lost or paid unseen.
        # v2 change: an earlier invoice with a DIFFERENT, unknown PO reference no longer poisons it (distinct references).
        r = run([make_po()], inv_text(no="INV-1", po=None), inv_text(no="INV-2", po="PO-1"))
        self.assertNotIn("INV-2", [e["invoice_no"] for e in r["auto_matched"]])  # the second is held
        self.assertIn("possible_duplicate", reasons(r))
        r = run([make_po()], inv_text(no="INV-1", po="PO-404"), inv_text(no="INV-2", po="PO-1"))
        self.assertEqual(len(r["auto_matched"]), 1)
        self.assertNotIn("possible_duplicate", reasons(r))

    def test_extract_never_raises(self):
        for junk in (None, 5, "", "\x00\x00", "Part: " * 50, "Total: " + "9" * 5000):
            self.assertIsInstance(extract(junk), Invoice)


if __name__ == "__main__":
    unittest.main()
