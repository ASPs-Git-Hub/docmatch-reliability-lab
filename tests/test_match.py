import unittest
from decimal import Decimal as D

from helpers import inv_text, make_po
from docmatch.extract import extract
from docmatch.match import MatchConfig, in_window, match, tolerance, within_tolerance, vendor_similarity


def run(text, pos, cfg=None):
    return match(extract(text), pos, cfg)


class ToleranceTests(unittest.TestCase):
    def test_percent_dominates_on_large(self):
        self.assertEqual(tolerance(D("1000.00"), MatchConfig()), D("20.0000"))

    def test_floor_dominates_on_small(self):
        self.assertEqual(tolerance(D("30.00"), MatchConfig()), D("1.00"))

    def test_boundary_inclusive(self):
        c = MatchConfig()
        self.assertTrue(within_tolerance(D("510.00"), D("500.00"), c))
        self.assertFalse(within_tolerance(D("510.01"), D("500.00"), c))

    def test_under_also_within(self):
        self.assertTrue(within_tolerance(D("490.00"), D("500.00"), MatchConfig()))
        self.assertFalse(within_tolerance(D("489.99"), D("500.00"), MatchConfig()))

    def test_none_not_within(self):
        self.assertFalse(within_tolerance(None, D("1"), MatchConfig()))

    def test_configurable(self):
        c = MatchConfig(rel=D("0.10"))
        self.assertTrue(within_tolerance(D("109.00"), D("100.00"), c))


class WindowTests(unittest.TestCase):
    def test_edges(self):
        c = MatchConfig()
        self.assertTrue(in_window("2026-03-01", "2026-03-01", c))
        self.assertTrue(in_window("2026-02-26", "2026-03-01", c))   # 3 days before
        self.assertFalse(in_window("2026-02-25", "2026-03-01", c))  # 4 days before
        self.assertTrue(in_window("2026-05-30", "2026-03-01", c))   # 90 days after
        self.assertFalse(in_window("2026-05-31", "2026-03-01", c))  # 91 days after

    def test_bad_dates(self):
        self.assertFalse(in_window(None, "2026-03-01", MatchConfig()))
        self.assertFalse(in_window("2026-03-01", "garbage", MatchConfig()))


class VendorTests(unittest.TestCase):
    def test_similarity(self):
        self.assertEqual(vendor_similarity("Acme Co.", "ACME, Inc"), 1.0)
        self.assertGreater(vendor_similarity("Brightwatr Suplies", "Brightwater Supplies"), 0.85)
        self.assertLess(vendor_similarity("Brightwater Supplies", "Mereside Logistics"), 0.5)
        self.assertEqual(vendor_similarity(None, "x"), 0.0)


class TierTests(unittest.TestCase):
    def test_tier1_match(self):
        r = run(inv_text(), [make_po()])
        self.assertEqual((r.status, r.po_id, r.tier), ("MATCH", "PO-1", 1))

    def test_tier1_unknown_ref_never_falls_through(self):
        r = run(inv_text(po="PO-404"), [make_po("PO-1")])
        self.assertEqual(r.status, "AMBIGUOUS")
        self.assertIn("po_ref_unknown", r.reasons)

    def test_tier1_duplicate_po_ids(self):
        r = run(inv_text(), [make_po(), make_po()])
        self.assertEqual(r.status, "AMBIGUOUS")
        self.assertIn("po_ref_duplicated", r.reasons)

    def test_tier1_reasons_listed(self):
        r = run(inv_text(), [make_po(vendor="Mereside Logistics", cur="EUR", total="500.00")])
        self.assertEqual(r.status, "AMBIGUOUS")
        self.assertEqual(sorted(r.reasons), ["currency_mismatch", "total_mismatch", "vendor_mismatch"])

    def test_tier2_unique(self):
        r = run(inv_text(po=None), [make_po("PO-7")])
        self.assertEqual((r.status, r.po_id, r.tier), ("MATCH", "PO-7", 2))

    def test_tier2_two_candidates_ambiguous(self):
        r = run(inv_text(po=None), [make_po("PO-7"), make_po("PO-8")])
        self.assertEqual(r.status, "AMBIGUOUS")
        self.assertEqual(sorted(r.candidates), ["PO-7", "PO-8"])

    def test_tier2_currency_filters_candidates(self):
        r = run(inv_text(po=None), [make_po("PO-7", cur="EUR"), make_po("PO-8", cur="USD")])
        self.assertEqual((r.status, r.po_id), ("MATCH", "PO-8"))

    def test_tier2_currency_mismatch_only(self):
        r = run(inv_text(po=None), [make_po("PO-7", cur="EUR")])
        self.assertEqual(r.status, "AMBIGUOUS")
        self.assertEqual(r.reasons, ["currency_mismatch"])

    def test_tier2_outside_window_goes_weak(self):
        r = run(inv_text(po=None, date="2026-12-01"), [make_po()])
        self.assertEqual((r.status, r.tier), ("AMBIGUOUS", 3))
        self.assertEqual(r.reasons, ["weak_tier_only"])

    def test_tier3_never_matches(self):
        r = run(inv_text(po=None, vendor="Brightwatr Suplies Ltd"), [make_po()])
        self.assertEqual(r.status, "AMBIGUOUS")
        self.assertIsNone(r.po_id)

    def test_unmatched(self):
        r = run(inv_text(po=None), [make_po(total="900.00")])
        self.assertEqual((r.status, r.reasons), ("UNMATCHED", ["no_candidate"]))

    def test_empty_po_list(self):
        self.assertEqual(run(inv_text(po=None), []).status, "UNMATCHED")
        self.assertEqual(run(inv_text(), None).status, "AMBIGUOUS")

    def test_insufficient_fields(self):
        self.assertEqual(run("Invoice No: A\nTotal: 5.00", [make_po()]).reasons, ["insufficient_fields"])

    def test_ref_without_vendor_is_ambiguous_not_unmatched(self):
        r = run(inv_text(vendor=None), [make_po()])
        self.assertEqual((r.status, r.reasons), ("AMBIGUOUS", ["vendor_mismatch"]))

    def test_missing_currency_does_not_auto_match(self):
        r = run(inv_text(po=None).replace("Currency: USD\n", ""), [make_po()])
        self.assertNotEqual(r.status, "MATCH")

    def test_rounding_total_within_floor(self):
        r = run(inv_text(lines=(("Pen", 3, "3.33"),)), [make_po(total="10.00")])
        self.assertEqual(r.status, "MATCH")

    def test_custom_window(self):
        cfg = MatchConfig(window_after_days=5)
        r = run(inv_text(po=None, date="2026-03-20"), [make_po(date="2026-03-01")], cfg)
        self.assertEqual(r.status, "AMBIGUOUS")


if __name__ == "__main__":
    unittest.main()
