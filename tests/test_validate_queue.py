import datetime
import unittest
from decimal import Decimal as D

from helpers import inv_text
from docmatch.extract import extract
from docmatch.queue import ExceptionQueue
from docmatch.util import money, norm_vendor, wilson
from docmatch.validate import DuplicateDetector, PartTracker, check_invoice


class CheckInvoiceTests(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(check_invoice(extract(inv_text())), [])

    def test_tax_included_ok(self):
        self.assertEqual(check_invoice(extract(inv_text(tax="7.25"))), [])

    def test_total_mismatch(self):
        self.assertEqual(check_invoice(extract(inv_text(total="150.00"))), ["total_mismatch_lines"])

    def test_one_cent_off_tolerated_two_not(self):
        self.assertEqual(check_invoice(extract(inv_text(total="100.01"))), [])
        self.assertEqual(check_invoice(extract(inv_text(total="100.02"))), ["total_mismatch_lines"])

    def test_zero_and_negative_flagged(self):
        self.assertIn("non_positive_total", check_invoice(extract(inv_text(lines=(("x", 1, "0.00"),)))))
        self.assertIn("non_positive_total", check_invoice(extract(inv_text(lines=(("x", 1, "-5.00"),)))))

    def test_subtotal_mismatch(self):
        t = inv_text().replace("Subtotal: 100.00", "Subtotal: 90.00")
        self.assertIn("subtotal_mismatch", check_invoice(extract(t)))

    def test_malformed_missing_each_required(self):
        for drop in ("Invoice No: INV-1\n", "Vendor: Brightwater Supplies Ltd\n", "Date: 2026-03-10\n", "Total: 100.00"):
            self.assertEqual(check_invoice(extract(inv_text().replace(drop, ""))), ["malformed"], drop)


class DuplicateTests(unittest.TestCase):
    def test_resubmission_vs_conflict(self):
        d = DuplicateDetector()
        a = extract(inv_text())
        self.assertIsNone(d.check(a))
        d.register(a)
        self.assertEqual(d.check(extract(inv_text())), "resubmission")
        self.assertEqual(d.check(extract(inv_text(lines=(("Widget", 3, "50.00"),)))), "id_conflict")

    def test_possible_duplicate_other_number(self):
        d = DuplicateDetector()
        d.register(extract(inv_text(no="INV-1")))
        self.assertEqual(d.check(extract(inv_text(no="INV-2"))), "possible_duplicate")

    def test_same_total_different_date_is_not_duplicate(self):
        d = DuplicateDetector()
        d.register(extract(inv_text(no="INV-1", po="PO-1")))
        self.assertIsNone(d.check(extract(inv_text(no="INV-2", date="2026-03-11", po="PO-2"))))

    def test_vendor_formatting_irrelevant(self):
        d = DuplicateDetector()
        d.register(extract(inv_text()))
        self.assertEqual(d.check(extract(inv_text(vendor="BRIGHTWATER SUPPLIES LTD."))), "resubmission")

    def test_different_vendor_same_number_ok(self):
        d = DuplicateDetector()
        d.register(extract(inv_text()))
        self.assertIsNone(d.check(extract(inv_text(vendor="Mereside Logistics"))))


class PartTests(unittest.TestCase):
    def p(self, i, n, amt="50.00"):
        return extract(inv_text(lines=(("w", 1, amt),), part=(i, n)))

    def test_complete_only_when_all_arrive(self):
        t = PartTracker()
        self.assertEqual(t.add(self.p(1, 3))[0], "incomplete")
        self.assertEqual(t.add(self.p(3, 3))[0], "incomplete")
        status, parts = t.add(self.p(2, 3))
        self.assertEqual(status, "complete")
        self.assertEqual(sorted(parts), [1, 2, 3])

    def test_count_conflict(self):
        t = PartTracker()
        t.add(self.p(1, 2))
        self.assertEqual(t.add(self.p(2, 3))[0], "conflict")

    def test_index_out_of_range(self):
        inv = self.p(1, 2)
        inv.part = (3, 2)  # extract() refuses this declaration now; the tracker must still refuse it
        self.assertEqual(PartTracker().add(inv)[0], "conflict")
        inv.part = (0, 2)
        self.assertEqual(PartTracker().add(inv)[0], "conflict")

    def test_same_index_different_total_conflict(self):
        t = PartTracker()
        t.add(self.p(1, 2, "50.00"))
        self.assertEqual(t.add(self.p(1, 2, "60.00"))[0], "conflict")


class QueueTests(unittest.TestCase):
    def test_one_entry_per_invoice_reason(self):
        q = ExceptionQueue()
        self.assertTrue(q.add(("v", "I1"), "a", 10, "2026-01-01"))
        self.assertFalse(q.add(("v", "I1"), "a", 10, "2026-01-01"))
        self.assertTrue(q.add(("v", "I1"), "b", 10, "2026-01-01"))
        self.assertTrue(q.add(("v", "I2"), "a", 10, "2026-01-01"))
        self.assertEqual(len(q), 3)

    def test_resolve(self):
        q = ExceptionQueue()
        q.add(("v", "I1"), "a")
        self.assertTrue(q.resolve(("v", "I1"), "a"))
        self.assertFalse(q.resolve(("v", "I1"), "a"))
        self.assertEqual(len(q), 0)

    def test_priority_older_first(self):
        q = ExceptionQueue()
        q.add(("v", "new"), "r", 100, "2026-03-09")
        q.add(("v", "old"), "r", 100, "2026-01-01")
        order = [e.invoice_key[1] for e in q.list_sorted(datetime.date(2026, 3, 10))]
        self.assertEqual(order, ["old", "new"])

    def test_priority_bigger_amount_first_at_equal_age(self):
        q = ExceptionQueue()
        q.add(("v", "small"), "r", 10, "2026-03-01")
        q.add(("v", "big"), "r", 50000, "2026-03-01")
        order = [e.invoice_key[1] for e in q.list_sorted(datetime.date(2026, 3, 10))]
        self.assertEqual(order, ["big", "small"])

    def test_priority_formula_and_cap(self):
        q = ExceptionQueue()
        q.add(("v", "x"), "r", -2000, "2026-03-01")  # abs amount
        e = q.list_sorted(datetime.date(2026, 3, 11))[0]
        self.assertEqual(ExceptionQueue.priority(e, datetime.date(2026, 3, 11)), 2 * 10 + 2.0)
        q.add(("v", "y"), "r", 10**9, "2026-03-11")
        y = [e for e in q.list_sorted(datetime.date(2026, 3, 11)) if e.invoice_key[1] == "y"][0]
        self.assertEqual(ExceptionQueue.priority(y, datetime.date(2026, 3, 11)), 100.0)

    def test_missing_date_age_zero(self):
        e = ExceptionQueue()
        e.add(("v", "x"), "r", 1000, None)
        self.assertEqual(ExceptionQueue.priority(e.list_sorted(datetime.date(2026, 1, 1))[0], datetime.date(2026, 1, 1)), 1.0)

    def test_future_date_age_not_negative(self):
        e = ExceptionQueue()
        e.add(("v", "x"), "r", 0, "2027-01-01")
        self.assertEqual(ExceptionQueue.priority(e.list_sorted(datetime.date(2026, 1, 1))[0], datetime.date(2026, 1, 1)), 0.0)


class UtilTests(unittest.TestCase):
    def test_money(self):
        self.assertIsNone(money("1,250.005"))  # excess precision is refused, not rounded
        self.assertEqual(money("1,250.50"), D("1250.50"))
        self.assertEqual(money("$5"), D("5.00"))
        self.assertIsNone(money("abc"))
        self.assertIsNone(money(None))

    def test_norm_vendor(self):
        self.assertEqual(norm_vendor("Tarn & Fell Stationers"), "tarn and fell stationers")
        self.assertEqual(norm_vendor("ACME, Inc."), "acme")
        self.assertEqual(norm_vendor(None), "")

    def test_wilson_known_values(self):
        lo, hi = wilson(0, 10)
        self.assertAlmostEqual(lo, 0.0, places=6)
        self.assertAlmostEqual(hi, 0.2775, places=3)
        lo, hi = wilson(5, 10)
        self.assertAlmostEqual(lo, 0.2366, places=3)
        self.assertAlmostEqual(hi, 0.7634, places=3)
        self.assertEqual(wilson(0, 0), (0.0, 1.0))
        self.assertAlmostEqual(wilson(10, 10)[1], 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
