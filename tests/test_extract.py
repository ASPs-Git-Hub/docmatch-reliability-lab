import unittest
from decimal import Decimal as D

from helpers import inv_text
from docmatch.extract import extract


class ExtractTests(unittest.TestCase):
    def test_full_invoice(self):
        inv = extract(inv_text(no="inv-77", po="po-5", lines=(("A", 3, "19.99"), ("B", 1, "5.00")), tax="1.50"))
        self.assertEqual(inv.invoice_no, "INV-77")
        self.assertEqual(inv.po_ref, "PO-5")
        self.assertEqual(inv.vendor, "Brightwater Supplies Ltd")
        self.assertEqual(inv.date, "2026-03-10")
        self.assertEqual(inv.currency, "USD")
        self.assertEqual(len(inv.items), 2)
        self.assertEqual(inv.items[0][3], D("59.97"))
        self.assertEqual(inv.subtotal, D("64.97"))
        self.assertEqual(inv.tax, D("1.50"))
        self.assertEqual(inv.total, D("66.47"))

    def test_confidence_labelled_is_one(self):
        c = extract(inv_text()).conf
        for k in ("invoice_no", "po_ref", "vendor", "date", "currency", "total"):
            self.assertEqual(c[k], 1.0, k)

    def test_po_optional(self):
        inv = extract(inv_text(po=None))
        self.assertIsNone(inv.po_ref)
        self.assertEqual(inv.conf["po_ref"], 0.0)

    def test_po_na_is_none(self):
        self.assertIsNone(extract("Invoice No: X1\nPO: N/A\nTotal: 5.00").po_ref)

    def test_missing_fields_zero_confidence(self):
        inv = extract("hello world")
        self.assertIsNone(inv.invoice_no)
        self.assertIsNone(inv.vendor)
        self.assertIsNone(inv.total)
        self.assertEqual(inv.conf["vendor"], 0.0)
        self.assertEqual(inv.conf["total"], 0.0)

    def test_non_string_input_does_not_crash(self):
        self.assertIsNone(extract(None).total)
        self.assertIsNone(extract(12345).vendor)

    def test_thousands_separator(self):
        self.assertEqual(extract("Invoice No: A1\nTotal: 1,250.50").total, D("1250.50"))

    def test_negative_total(self):
        self.assertEqual(extract("Invoice No: A1\nTotal: -120.00").total, D("-120.00"))

    def test_amount_due_fallback_lower_confidence(self):
        inv = extract("Invoice No: A1\nAmount Due: 80.00")
        self.assertEqual(inv.total, D("80.00"))
        self.assertEqual(inv.conf["total"], 0.7)

    def test_currency_never_inferred_from_symbol(self):
        inv = extract("Invoice No: A1\nTotal: €80.00")
        self.assertIsNone(inv.currency)
        self.assertIn("currency_symbol_only", inv.issues)

    def test_invoice_no_fallback_confidence(self):
        inv = extract("Ref INV-9 something\nTotal: 5.00")
        self.assertEqual(inv.invoice_no, "INV-9")
        self.assertEqual(inv.conf["invoice_no"], 0.5)

    def test_unlabelled_date_not_used(self):
        inv = extract("Invoice No: A1\nIssued on 2026-05-06\nTotal: 5.00")
        self.assertIsNone(inv.date)
        self.assertEqual(inv.conf["date"], 0.0)

    def test_part_parsed(self):
        self.assertEqual(extract(inv_text(part=(2, 3))).part, (2, 3))
        self.assertIsNone(extract(inv_text()).part)

    def test_po_label_variants(self):
        for label in ("PO", "PO Ref", "PO No", "Purchase Order"):
            self.assertEqual(extract(f"Invoice No: A1\n{label}: PO-42\nTotal: 1.00").po_ref, "PO-42", label)

    def test_subtotal_not_mistaken_for_total(self):
        inv = extract("Invoice No: A1\nSubtotal: 10.00\nTax: 1.00")
        self.assertIsNone(inv.total)


if __name__ == "__main__":
    unittest.main()
