import datetime
import json
import os
import unittest

from helpers import inv_text, make_po
from docmatch import DocMatch, MatchConfig

NOW = datetime.date(2026, 4, 1)


def dm(pos=None):
    return DocMatch(pos if pos is not None else [make_po()], now=NOW)


class PipelineTests(unittest.TestCase):
    def test_empty_batch(self):
        r = dm().process([])
        self.assertEqual((r["auto_matched"], r["needs_review"], r["skipped"], r["queue"]), ([], [], [], []))

    def test_none_batch(self):
        self.assertEqual(dm().process(None)["auto_matched"], [])

    def test_auto_entry_fields(self):
        e = dm().process([inv_text()])["auto_matched"][0]
        self.assertEqual((e["invoice_no"], e["po_id"], e["tier"], e["status"], e["total"]), ("INV-1", "PO-1", 1, "MATCH", "100.00"))

    def test_malformed_queued(self):
        r = dm().process(["garbage", "garbage"])
        self.assertEqual(len(r["needs_review"]), 2)
        self.assertEqual(len(r["queue"]), 1)  # same text, same reason, one entry

    def test_non_string_item(self):
        r = dm().process([None])
        self.assertEqual(len(r["needs_review"]), 1)

    def test_resubmission_skipped_not_requeued(self):
        d = dm([make_po(total="9000.00")])
        d.process([inv_text(po=None)])
        r = d.process([inv_text(po=None)])
        self.assertEqual((len(r["needs_review"]), len(r["skipped"]), len(r["queue"])), (0, 1, 1))

    def test_id_conflict_flagged(self):
        d = dm()
        d.process([inv_text()])
        r = d.process([inv_text(lines=(("Widget", 3, "50.00"),))])
        self.assertEqual(r["needs_review"][0]["reasons"], ["duplicate_id_conflict"])

    def test_possible_duplicate_flagged_and_queued(self):
        d = dm([make_po("PO-1"), make_po("PO-2")])
        r = d.process([inv_text(no="INV-1", po="PO-1"), inv_text(no="INV-2", po="PO-2")])
        self.assertEqual(r["needs_review"][0]["reasons"], ["possible_duplicate"])
        self.assertEqual(r["queue"][0].reason, "possible_duplicate")

    def test_invalid_totals_flagged(self):
        r = dm().process([inv_text(total="150.00")])
        self.assertEqual(r["needs_review"][0]["reasons"], ["total_mismatch_lines"])
        self.assertEqual(r["needs_review"][0]["status"], "INVALID")

    def test_multiple_reasons_one_queue_entry_each(self):
        r = dm().process([inv_text(lines=(("x", 1, "-5.00"),), total="-3.00")])
        self.assertEqual(sorted(r["needs_review"][0]["reasons"]), ["non_positive_total", "total_mismatch_lines"])
        self.assertEqual(sorted(e.reason for e in r["queue"]), ["non_positive_total", "total_mismatch_lines"])

    def test_ambiguous_entry_carries_candidates(self):
        r = dm([make_po("PO-1"), make_po("PO-2")]).process([inv_text(po=None)])
        e = r["needs_review"][0]
        self.assertEqual((e["status"], sorted(e["candidates"]), e["po_id"]), ("AMBIGUOUS", ["PO-1", "PO-2"], None))

    def test_queue_sorted_by_priority(self):
        d = dm([make_po(total="9000.00")])
        r = d.process([inv_text(no="NEW", po=None, date="2026-03-30", lines=(("a", 1, "10.00"),)),
                       inv_text(no="OLD", po=None, date="2026-01-02", lines=(("b", 1, "20.00"),))])
        self.assertEqual([e.invoice_key[1] for e in r["queue"]], ["OLD", "NEW"])

    def test_custom_config_changes_outcome(self):
        pos = [make_po(total="100.00")]
        text = inv_text(lines=(("w", 1, "104.00"),))
        self.assertEqual(len(DocMatch(pos, now=NOW).process([text])["auto_matched"]), 0)
        loose = DocMatch(pos, MatchConfig(rel=MatchConfig().rel * 3), now=NOW)
        self.assertEqual(len(loose.process([text])["auto_matched"]), 1)


class PartsTests(unittest.TestCase):
    def part(self, i, n, amt="50.00", po="PO-1"):
        return inv_text(lines=(("w", 1, amt),), part=(i, n), po=po)

    def test_incomplete_then_complete_resolves_queue(self):
        d = dm()
        r1 = d.process([self.part(1, 2)])
        self.assertEqual(r1["needs_review"][0]["reasons"], ["parts_incomplete"])
        self.assertEqual(r1["needs_review"][0]["status"], "PARTIAL")
        self.assertEqual(len(r1["queue"]), 1)
        r2 = d.process([self.part(2, 2)])
        self.assertEqual(len(r2["auto_matched"]), 1)
        self.assertEqual(r2["auto_matched"][0]["total"], "100.00")
        self.assertEqual(r2["queue"], [])

    def test_reordered_three_parts(self):
        d = dm([make_po(total="150.00")])
        r = d.process([self.part(3, 3), self.part(1, 3), self.part(2, 3)])
        self.assertEqual(len(r["auto_matched"]), 1)
        self.assertEqual(len(r["needs_review"]), 2)

    def test_parts_sum_must_match_po(self):
        d = dm()
        d.process([self.part(1, 2, "50.00")])
        r = d.process([self.part(2, 2, "500.00")])
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertIn("total_mismatch", r["needs_review"][0]["reasons"])

    def test_part_resubmission_skipped(self):
        d = dm()
        d.process([self.part(1, 2)])
        r = d.process([self.part(1, 2)])
        self.assertEqual(len(r["skipped"]), 1)

    def test_part_count_conflict(self):
        d = dm()
        d.process([self.part(1, 2)])
        r = d.process([self.part(2, 3)])
        self.assertEqual(r["needs_review"][0]["reasons"], ["part_conflict"])

    def test_parts_without_po_ref(self):
        r = dm().process([self.part(1, 2, po=None)])
        self.assertEqual(r["needs_review"][0]["reasons"], ["parts_without_po_ref"])

    def test_parts_not_flagged_as_duplicates_of_each_other(self):
        d = dm()
        r = d.process([self.part(1, 2), self.part(2, 2)])
        self.assertNotIn("possible_duplicate", [x for e in r["needs_review"] for x in e["reasons"]])


class DataShapeTests(unittest.TestCase):
    def load(self, name):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "data", name)) as f:
            return json.load(f)["cases"]

    def test_set_b_shape(self):
        cases = self.load("set_b.json")
        self.assertGreaterEqual(len(cases), 30)
        self.assertGreaterEqual(sum(c["kind"] == "trap" for c in cases), 10)
        for c in cases:
            self.assertIn(c["expected"], ("MATCH", "AMBIGUOUS", "UNMATCHED"))
            self.assertEqual(c["kind"] == "normal", c["expected"] == "MATCH")

    def test_set_a_and_b_disjoint_ids(self):
        a = {c["id"] for c in self.load("set_a.json")}
        b = {c["id"] for c in self.load("set_b.json")}
        self.assertFalse(a & b)


if __name__ == "__main__":
    unittest.main()
