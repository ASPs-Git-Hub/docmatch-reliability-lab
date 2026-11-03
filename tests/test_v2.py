"""v2 behaviour (real-data/PROTOCOL-v2.md): number conventions with evidence, one vendor key, recurrence-aware duplicates."""
import datetime
import unittest
from decimal import Decimal as D

import helpers  # noqa: F401  (sets sys.path)
from docmatch import DocMatch
from docmatch.extract import Invoice, extract
from docmatch.numfmt import locale_convention, minor_digits, read_token, resolve
from docmatch.validate import DuplicateDetector, PartTracker, _on_cadence
from helpers import inv_text, make_po


def total_of(body, **kw):
    inv = extract("Invoice No: A1\nVendor: Acme Ltd\nDate: 2026-03-10\n" + body, **kw)
    return inv


class ReadToken(unittest.TestCase):
    def test_unambiguous_forms(self):
        cases = [("1.234,56", "EU", "1234.56"), ("1,234.56", "US", "1234.56"), ("12,50", "EU", "12.50"), ("12.50", "US", "12.50"),
                 ("1.234.567", "EU", "1234567"), ("1,234,567", "US", "1234567"), ("1 234,56", "EU", "1234.56"),
                 ("1 234.56", "US", "1234.56"), ("1 234,56", "EU", "1234.56"), ("1 234.56", "US", "1234.56"),
                 ("1'234.56", "US", "1234.56"), ("$1,250.00", "US", "1250.00"), ("€ 1.250,00", "EU", "1250.00"), ("-5", "US", "-5")]
        for tok, conv, want in cases:
            self.assertEqual(read_token(tok, conv), D(want), (tok, conv))
        for tok, conv in [("1.234,56", "US"), ("1,234.56", "EU"), ("12,50", "US"), ("12.50", "EU"), ("1.234.567", "US"),
                          ("1 234,56", "US"), ("1 234.56", "EU")]:
            self.assertIsNone(read_token(tok, conv), (tok, conv))

    def test_ambiguous_forms_read_both_ways(self):
        self.assertEqual((read_token("1.234", "US"), read_token("1.234", "EU")), (D("1.234"), D("1234")))
        self.assertEqual((read_token("1,234", "US"), read_token("1,234", "EU")), (D("1234"), D("1.234")))
        self.assertEqual((read_token("60.000", "US"), read_token("60.000", "EU")), (D("60"), D("60000")))
        self.assertEqual((read_token("1.000", "US"), read_token("1.000", "EU")), (D("1"), D("1000")))

    def test_neutral_forms(self):
        for tok in ("1250", "12", "0"):
            self.assertEqual(read_token(tok, "US"), read_token(tok, "EU"))

    def test_invalid_forms(self):
        for tok in ("1,25.00", "12.345.6", "1.2345", "1,2345", "--5", "$-$5", "1234567890123", "1 23", "1.23,45.6", "0.500x", "", "1.", ".5", "1.234 567", "12,50e3"):
            for conv in ("US", "EU"):
                self.assertIsNone(read_token(tok, conv), (tok, conv))

    def test_leading_zero_group_is_not_a_group(self):
        self.assertIsNone(read_token("0.500", "EU"))  # 0 is not a first group
        self.assertEqual(read_token("0.500", "US"), D("0.5"))
        self.assertEqual(read_token("0,500", "EU"), D("0.5"))
        self.assertIsNone(read_token("0,500", "US"))

    def test_minor_digits_limit_fraction(self):
        self.assertIsNone(read_token("60.000", "US", 0))
        self.assertEqual(read_token("60.000", "EU", 0), D("60000"))
        self.assertIsNone(read_token("1.234", "US", 2))
        self.assertEqual(read_token("1.23", "US", 2), D("1.23"))
        self.assertIsNone(read_token("1.234", "US", 0))
        self.assertEqual(read_token("1.234", "US", 3), D("1.234"))

    def test_helpers(self):
        self.assertEqual((minor_digits("jpy"), minor_digits("IDR"), minor_digits("KWD"), minor_digits("USD"), minor_digits(None)), (0, 0, 3, 2, None))
        self.assertEqual((locale_convention("de_DE"), locale_convention("de-de"), locale_convention("en-US"), locale_convention("xx-XX"), locale_convention("de-CH"), locale_convention(None)),
                         ("EU", "EU", "US", None, None, None))


class AmbiguousTokenAlone(unittest.TestCase):
    """No evidence in the document: an ambiguous token is refused, never guessed."""

    def test_each_ambiguous_total_is_refused(self):
        for tok in ("1.234", "1,234", "60.000", "60,000", "1.000", "1,000", "999.999", "12.500"):
            inv = total_of(f"Total: {tok}")
            self.assertIsNone(inv.total, tok)
            self.assertIn("total_ambiguous_format", inv.issues, tok)
            self.assertEqual(inv.conf["total"], 0.0)

    def test_unambiguous_forms_accepted_with_full_confidence(self):
        for tok, want in (("1.234,56", "1234.56"), ("12,50", "12.50"), ("1 234,56", "1234.56"), ("1,250.00", "1250.00"), ("1.234.567", "1234567.00"), ("1,234,567", "1234567.00")):
            inv = total_of(f"Total: {tok}")
            self.assertEqual(inv.total, D(want), tok)
            self.assertEqual(inv.conf["total"], 1.0, tok)
            self.assertEqual(inv.format_evidence, [], tok)

    def test_plain_integer_and_two_decimals_unchanged(self):
        self.assertEqual(total_of("Total: 1250").total, D("1250.00"))
        self.assertEqual(total_of("Total: 12.5").total, D("12.50"))


class CurrencyEvidence(unittest.TestCase):
    def test_zero_decimal_currency_makes_dotted_value_a_grouped_number(self):
        for cur in ("JPY", "IDR", "KRW", "VND"):
            inv = total_of(f"Currency: {cur}\nTotal: 60.000")
            self.assertEqual(inv.total, D("60000.00"), cur)
            self.assertEqual(inv.conf["total"], 0.7, cur)
            self.assertEqual(inv.format_evidence, ["currency"])

    def test_two_decimal_currency_makes_three_digit_tail_a_group(self):
        for cur, tok in (("USD", "1,234"), ("EUR", "1.234"), ("GBP", "1.234"), ("USD", "1.250")):
            inv = total_of(f"Currency: {cur}\nTotal: {tok}")
            self.assertEqual(inv.total, D(tok.replace(",", "").replace(".", "")) .quantize(D("0.01")), (cur, tok))
            self.assertEqual(inv.conf["total"], 0.7)

    def test_three_decimal_currency_stays_ambiguous(self):
        inv = total_of("Currency: KWD\nTotal: 1.234")
        self.assertIsNone(inv.total)
        self.assertIn("total_ambiguous_format", inv.issues)

    def test_zero_decimal_currency_refuses_two_decimals(self):
        inv = total_of("Currency: JPY\nTotal: 12.50")
        self.assertIsNone(inv.total)
        self.assertIn("total_unparseable", inv.issues)

    def test_assume_currency_is_used_for_reading_but_not_set(self):
        inv = extract("Invoice No: A1\nTotal: 60.000", assume_currency="IDR")
        self.assertEqual(inv.total, D("60000.00"))
        self.assertIsNone(inv.currency)
        self.assertEqual(inv.conf["currency"], 0.0)

    def test_declared_currency_beats_assume_currency(self):
        inv = extract("Invoice No: A1\nCurrency: USD\nTotal: 60.000", assume_currency="IDR")
        self.assertEqual(inv.total, D("60000.00"))  # USD has 2 digits: 3-digit tail is a group
        inv = extract("Invoice No: A1\nCurrency: KWD\nTotal: 60.000", assume_currency="IDR")
        self.assertIsNone(inv.total)  # the document's own currency wins: KWD allows 3 decimals, so it stays ambiguous


class LocaleEvidence(unittest.TestCase):
    def test_locale_picks_convention(self):
        inv = total_of("Locale: de-DE\nTotal: 1.234")
        self.assertEqual(inv.total, D("1234.00"))
        self.assertEqual(inv.conf["total"], 0.7)
        self.assertEqual(inv.format_evidence, ["locale"])
        inv = total_of("Locale: en-US\nTotal: 1,234")
        self.assertEqual(inv.total, D("1234.00"))

    def test_locale_us_with_three_decimals_is_refused_not_rounded(self):
        inv = total_of("Locale: en-US\nTotal: 1.234")
        self.assertIsNone(inv.total)
        self.assertIn("total_not_2dp", inv.issues)

    def test_unknown_locale_gives_no_evidence(self):
        for loc in ("xx-XX", "de-CH", "garbage"):
            inv = total_of(f"Locale: {loc}\nTotal: 1.234")
            self.assertIsNone(inv.total, loc)
            self.assertIn("total_ambiguous_format", inv.issues)

    def test_number_format_label_also_works(self):
        self.assertEqual(total_of("Number format: fr-FR\nTotal: 1,234").total, None)  # fr-FR = EU: 1,234 is 1.234, not 2dp
        self.assertEqual(total_of("Number format: fr-FR\nTotal: 1 234").total, D("1234.00"))

    def test_locale_cannot_override_what_tokens_rule_out(self):
        inv = total_of("Locale: de-DE\nTotal: 1,250.00")  # US-only token, locale says EU: the token wins, locale is not used
        self.assertEqual(inv.total, D("1250.00"))
        self.assertEqual(inv.format_evidence, [])


def doc(items, sub, tax, total, extra=""):
    lines = ["Invoice No: A1", "PO: PO-1", "Vendor: Acme Ltd", "Date: 2026-03-10", extra, "Items:"] + [f"- {d} | {q} x {u} = {a}" for d, q, u, a in items]
    lines += [f"Subtotal: {sub}", f"Tax: {tax}", f"Total: {total}"]
    return "\n".join(x for x in lines if x)


class ArithmeticEvidence(unittest.TestCase):
    def test_sum_decides_for_eu(self):
        inv = extract(doc([("A", 1, "500", "500"), ("B", 1, "500", "500")], "1.000", "0", "1.000"))
        self.assertEqual((inv.subtotal, inv.total), (D("1000.00"), D("1000.00")))
        self.assertEqual(inv.conf["total"], 0.7)
        self.assertEqual(inv.format_evidence, ["arithmetic"])
        self.assertEqual(len(inv.items), 2)

    def test_sum_decides_for_us(self):
        inv = extract(doc([("A", 1, "1", "1")], "1.000", "0", "1.000"))
        self.assertEqual((inv.subtotal, inv.total), (D("1.00"), D("1.00")))
        self.assertEqual(inv.format_evidence, ["arithmetic"])

    def test_grouped_comma_us_reading(self):
        inv = extract(doc([("A", 1, "500", "500"), ("B", 1, "500", "500")], "1,000", "0", "1,000"))
        self.assertEqual(inv.total, D("1000.00"))

    def test_one_234_resolved_both_ways(self):
        eu = extract(doc([("A", 1, "1000", "1000"), ("B", 1, "234", "234")], "1.234", "0", "1.234"))
        self.assertEqual(eu.total, D("1234.00"))
        us = extract(doc([("A", 1, "1", "1"), ("B", 1, "0.234", "0.234")], "1.234", "0", "1.234"))
        self.assertIsNone(us.total)  # the US reading is 1.234: not a whole number of cents, refused
        self.assertIn("total_not_2dp", us.issues)

    def test_scale_invariant_document_stays_ambiguous(self):
        # every token scales by 1000 together, so both readings add up: no evidence, so refuse
        inv = extract(doc([("A", 1, "1.000", "1.000"), ("B", 2, "1.500", "3.000")], "4.000", "0", "4.000"))
        self.assertIsNone(inv.total)
        self.assertIn("total_ambiguous_format", inv.issues)
        self.assertIn("subtotal_ambiguous_format", inv.issues)
        self.assertEqual(inv.items, [])  # rows with ambiguous tokens are dropped, and flagged
        self.assertIn("items_unparsed", inv.issues)

    def test_neither_reading_adds_up_stays_refused(self):
        inv = extract(doc([("A", 1, "500", "500")], "1.000", "0", "1.000"))  # lines sum to 500: neither 1 nor 1000
        self.assertIsNone(inv.total)
        self.assertIn("total_ambiguous_format", inv.issues)

    def test_total_equals_subtotal_plus_tax(self):
        inv = extract("\n".join(["Invoice No: A1", "Vendor: Acme Ltd", "Date: 2026-03-10", "Subtotal: 1.000", "Tax: 200", "Total: 1.200"]))
        self.assertEqual((inv.subtotal, inv.tax, inv.total), (D("1000.00"), D("200.00"), D("1200.00")))
        inv = extract("\n".join(["Invoice No: A1", "Vendor: Acme Ltd", "Date: 2026-03-10", "Subtotal: 1.000", "Tax: 200", "Total: 1.300"]))
        self.assertIsNone(inv.total)

    def test_locale_and_arithmetic_disagree(self):
        inv = extract(doc([("A", 1, "1", "1")], "1.000", "0", "1.000", extra="Locale: de-DE"))
        self.assertIsNone(inv.total)
        self.assertIn("locale_conflicts_arithmetic", inv.issues)

    def test_locale_and_arithmetic_agree(self):
        inv = extract(doc([("A", 1, "500", "500"), ("B", 1, "500", "500")], "1.000", "0", "1.000", extra="Locale: de-DE"))
        self.assertEqual(inv.total, D("1000.00"))
        self.assertEqual(inv.format_evidence, ["locale", "arithmetic"])

    def test_arithmetic_failing_under_locale_is_not_a_veto(self):
        inv = extract(doc([("A", 1, "999", "999")], "1.000", "0", "1.000", extra="Locale: de-DE"))
        self.assertEqual(inv.total, D("1000.00"))  # decided by the locale; check_invoice flags the sum mismatch
        self.assertIn("subtotal_mismatch", __import__("docmatch").validate.check_invoice(inv))

    def test_line_arithmetic_decides(self):
        inv = extract(doc([("A", 3, "1.000", "3.000"), ("B", 1, "2", "2")], "3.002", "0", "3.002"))
        # US: 3x1.000=3.000 ok, sum 3.000+2 = 5 vs 3.002 fails; EU: 3x1000=3000 ok, 3000+2=3002 ok
        self.assertEqual(inv.total, D("3002.00"))


class SingleRelationEvidence(unittest.TestCase):
    """Each arithmetic relation decides on its own where the others cannot."""

    def test_line_relation_alone(self):
        inv = extract("Invoice No: A1\nVendor: Acme Ltd\nDate: 2026-03-10\nItems:\n- A | 3 x 1.000 = 3\nTotal: 3")
        self.assertEqual(inv.items, [("A", D("3"), D("1.00"), D("3.00"))])  # US: 3 x 1 = 3 holds, EU: 3 x 1000 does not
        self.assertEqual(inv.issues, [])

    def test_item_sum_vs_subtotal_alone(self):
        inv = extract(doc([("A", 1, "500", "500"), ("B", 1, "500", "500")], "1.000", "0", "1.000").replace("Tax: 0\n", "").replace("Total: 1.000", ""))
        self.assertEqual(inv.subtotal, D("1000.00"))

    def test_no_tax_line_means_zero_tax(self):
        inv = extract(doc([("A", 1, "500", "500"), ("B", 1, "500", "500")], "1.000", "0", "1.000").replace("Tax: 0\n", ""))
        self.assertEqual(inv.total, D("1000.00"))

    def test_partial_item_sum_is_not_evidence(self):
        text = doc([("A", 1, "500", "500"), ("B", 1, "500", "500"), ("C", 1, "?", "?")], "1.000", "0", "1.000").replace("Tax: 0\n", "").replace("Total: 1.000", "")
        inv = extract(text)
        self.assertIsNone(inv.subtotal)  # one row unreadable: the other two cannot prove the subtotal
        self.assertIn("subtotal_ambiguous_format", inv.issues)

    def test_one_cent_tolerance_is_inclusive(self):
        inv = extract("Invoice No: A1\nVendor: Acme Ltd\nDate: 2026-03-10\nSubtotal: 1.010\nTax: 0\nTotal: 1.000")
        self.assertEqual((inv.subtotal, inv.total), (D("1.01"), D("1.00")))  # US: 1.01 + 0 is within one cent of 1.00; EU is 1010 vs 1000
        inv = extract("Invoice No: A1\nVendor: Acme Ltd\nDate: 2026-03-10\nSubtotal: 1.020\nTax: 0\nTotal: 1.000")
        self.assertIsNone(inv.total)  # two cents apart under US, a thousand apart under EU: no reading holds

    def test_garbled_total_does_not_fall_back_to_amount_due_even_when_the_other_parses(self):
        inv = total_of("Total: abc\nAmount Due: 100.00")
        self.assertIsNone(inv.total)
        self.assertIn("total_unparseable", inv.issues)

    def test_no_item_level_issue_names_leak(self):
        inv = extract(doc([("A", 1, "1.000", "1.000")], "1.000", "0", "1.000"))
        self.assertFalse([i for i in inv.issues if i.startswith("item") and i != "items_unparsed"], inv.issues)

    def test_quantised_representation(self):
        self.assertEqual(str(total_of("Currency: IDR\nTotal: 60.000").total), "60000.00")
        self.assertEqual(str(total_of("Total: 1.5").total), "1.50")

    def test_out_of_order_date_on_cadence_without_same_day_history(self):
        d = DuplicateDetector()
        feed(d, I("A1", date="2026-04-01"), I("A2", date="2026-04-08"), I("A3", date="2026-04-18"))
        self.assertEqual(d.check_detail(I("A4", date="2026-04-15")), (None, "recurring_batch"))


class MixedStyles(unittest.TestCase):
    def test_mixed_styles_refuse_every_token_with_a_separator(self):
        inv = total_of("Subtotal: 1.234,56\nTax: 12.50\nTotal: 1.247,06")
        self.assertIsNone(inv.total)
        self.assertIsNone(inv.subtotal)
        self.assertIsNone(inv.tax)
        self.assertIn("mixed_number_formats", inv.issues)
        self.assertIn("total_unparseable", inv.issues)

    def test_plain_tokens_survive_a_mixed_document(self):
        inv = total_of("Tax: 5\nSubtotal: 1.234,56\nTotal: 1,250.00")
        self.assertEqual(inv.tax, D("5.00"))
        self.assertIsNone(inv.total)
        self.assertIn("mixed_number_formats", inv.issues)

    def test_convention_set_by_another_token_resolves_ambiguous_one(self):
        inv = total_of("Subtotal: 12,50\nTotal: 1.234")  # 12,50 can only be EU, so 1.234 is 1234
        self.assertEqual(inv.total, D("1234.00"))
        self.assertEqual(inv.conf["total"], 0.7)
        self.assertEqual(inv.format_evidence, ["document_convention"])
        inv = total_of("Subtotal: 12.50\nTotal: 1.250")  # 12.50 can only be US, so 1.250 is 1.25
        self.assertEqual(inv.total, D("1.25"))

    def test_garbage_amounts_still_refused(self):
        for tok in ("12.3.4.5", "abc", "1,2,3", "12e3"):
            inv = total_of(f"Total: {tok}")
            self.assertIsNone(inv.total, tok)
            self.assertIn("total_unparseable", inv.issues)


class PipelineWithInferredAmounts(unittest.TestCase):
    def test_inferred_total_never_auto_matches(self):
        text = inv_text().replace("Total: 100.00", "Total: 100.00")  # control: unambiguous form auto-matches
        r = DocMatch([make_po()]).process([text])
        self.assertEqual(len(r["auto_matched"]), 1)
        # a document whose total was only inferred (confidence 0.7) goes to review
        t2 = "\n".join(["Invoice No: A2", "PO: PO-1", "Vendor: Brightwater Supplies Ltd", "Date: 2026-03-10", "Currency: USD", "Locale: de-DE", "Total: 1.234"])
        r = DocMatch([make_po(total="1234.00")]).process([t2])
        self.assertEqual(len(r["auto_matched"]), 0)
        self.assertIn("low_confidence_total", [x for e in r["needs_review"] for x in e["reasons"]])


class ResolveDirect(unittest.TestCase):
    def test_empty_and_unparseable(self):
        self.assertEqual(resolve({})[0], {})
        vals, issues, inferred, ev = resolve({"total": "abc"})
        self.assertEqual((vals["total"], issues, inferred, ev), (None, ["total_unparseable"], set(), []))

    def test_more_than_twelve_digits_refused(self):
        vals, issues, _i, _e = resolve({"total": "1.234.567.890.123"})
        self.assertIsNone(vals["total"])


def I(no, vendor="Kestrel Ltd", total="100.00", date="2026-03-10", po=None, cur="GBP", context=None, part=None):
    return Invoice(invoice_no=no, vendor=vendor, date=date, currency=cur, total=D(total), po_ref=po, context=context, part=part)


def feed(det, *invs):
    out = []
    for inv in invs:
        out.append(det.check_detail(inv))
        det.register(inv)
    return out


class VendorKey(unittest.TestCase):
    def test_legal_suffix_separates_suppliers_in_the_detector(self):
        d = DuplicateDetector()
        feed(d, I("A1", vendor="Kestrel Ltd"))
        self.assertIsNone(d.check(I("A1", vendor="Kestrel Inc")))  # not a resubmission of the Ltd invoice
        self.assertIsNone(d.check(I("A2", vendor="Kestrel Inc")))  # nor a same-amount duplicate
        self.assertIsNone(d.check(I("A2", vendor="Kestrel")))

    def test_ltd_and_limited_are_the_same_supplier(self):
        d = DuplicateDetector()
        feed(d, I("A1", vendor="Kestrel Ltd"))
        self.assertEqual(d.check(I("A1", vendor="KESTREL LIMITED")), "resubmission")
        self.assertEqual(d.check(I("A2", vendor="Kestrel  Limited")), "possible_duplicate")

    def test_part_tracker_uses_identity(self):
        t = PartTracker()
        a, b = I("A1", vendor="Kestrel Ltd", po="PO-1", part=(1, 2)), I("A1", vendor="Kestrel Inc", po="PO-1", part=(2, 2))
        self.assertEqual(t.add(a)[0], "incomplete")
        self.assertEqual(t.add(b)[0], "incomplete")  # a different supplier: its own group, not the completion of the first


class DuplicateRules(unittest.TestCase):
    def test_same_day_same_amount_no_references_flagged(self):
        self.assertEqual(feed(DuplicateDetector(), I("A1"), I("A2"))[1], ("possible_duplicate", "near_no_cadence"))

    def test_first_seen_and_different_amount(self):
        out = feed(DuplicateDetector(), I("A1"), I("A2", total="100.01"))
        self.assertEqual(out, [(None, "first_seen"), (None, "first_seen")])

    def test_different_currency_not_a_duplicate(self):
        self.assertEqual(feed(DuplicateDetector(), I("A1"), I("A2", cur="EUR"))[1][0], None)

    def test_same_reference_flagged_even_months_apart(self):
        out = feed(DuplicateDetector(), I("A1", po="PO-9", date="2026-01-05"), I("A2", po="PO-9", date="2026-06-20"))
        self.assertEqual(out[1], ("possible_duplicate", "same_reference"))

    def test_distinct_references_are_two_orders(self):
        out = feed(DuplicateDetector(), I("A1", po="PO-1"), I("A2", po="PO-2"))
        self.assertEqual(out[1], (None, "distinct"))

    def test_one_missing_reference_is_not_distinct(self):
        out = feed(DuplicateDetector(), I("A1", po="PO-1"), I("A2", po=None))
        self.assertEqual(out[1][0], "possible_duplicate")

    def test_distinct_context(self):
        out = feed(DuplicateDetector(), I("A1", context=("RENT",)), I("A2", context=("FUEL",)))
        self.assertEqual(out[1], (None, "distinct"))
        out = feed(DuplicateDetector(), I("A1", context=("RENT",)), I("A2", context=("RENT",)))
        self.assertEqual(out[1][0], "possible_duplicate")
        out = feed(DuplicateDetector(use_context=False), I("A1", context=("RENT",)), I("A2", context=("FUEL",)))
        self.assertEqual(out[1][0], "possible_duplicate")
        out = feed(DuplicateDetector(), I("A1", context=("RENT",)), I("A2", context=None))
        self.assertEqual(out[1][0], "possible_duplicate")

    def test_window_boundaries(self):
        for gap, want in ((0, "possible_duplicate"), (1, "possible_duplicate"), (3, "possible_duplicate"), (4, None), (10, None)):
            d2 = (datetime.date(2026, 3, 10) + datetime.timedelta(days=gap)).isoformat()
            self.assertEqual(feed(DuplicateDetector(), I("A1"), I("A2", date=d2))[1][0], want, gap)
        d2 = "2026-03-11"
        self.assertIsNone(feed(DuplicateDetector(window_days=0), I("A1"), I("A2", date=d2))[1][0])
        self.assertEqual(feed(DuplicateDetector(window_days=1), I("A1"), I("A2", date=d2))[1][0], "possible_duplicate")
        # earlier-dated copy arriving later is judged the same way
        self.assertEqual(feed(DuplicateDetector(), I("A1", date="2026-03-12"), I("A2", date="2026-03-10"))[1][0], "possible_duplicate")

    def test_missing_dates(self):
        out = feed(DuplicateDetector(), I("A1", date=None), I("A2", date=None))
        self.assertEqual(out[1][0], "possible_duplicate")
        out = feed(DuplicateDetector(), I("A1", date=None), I("A2", date="2026-03-10"))
        self.assertEqual(out[1], (None, "outside_window"))

    def test_same_number_events_are_ignored(self):
        d = DuplicateDetector()
        feed(d, I("A1", part=(1, 2)))
        self.assertIsNone(d.check(I("A1", part=(2, 2), total="100.00")))
        d = DuplicateDetector()
        feed(d, I("A1", part=(1, 2), po="PO-1"))
        self.assertIsNone(d.check(I("A1", part=(2, 2), total="100.00", po="PO-1")))  # parts of one invoice are not each other's duplicates
        d = DuplicateDetector()
        feed(d, I("A0", date="2026-01-01"), I("A1", part=(1, 2), po="PO-1"))
        self.assertIsNone(d.check(I("A1", part=(2, 2), po="PO-1")))

    def test_monthly_series_is_recurring(self):
        out = feed(DuplicateDetector(), I("A1", date="2026-01-15"), I("A2", date="2026-02-15"), I("A3", date="2026-03-15"), I("A4", date="2026-04-15"))
        self.assertEqual([r[0] for r in out], [None] * 4)

    def test_weekly_batches(self):
        d = DuplicateDetector()
        out = []
        n = 0
        for day in (1, 8, 15, 22):
            for _ in range(3):
                n += 1
                out.append(feed(d, I(f"A{n}", date=f"2026-04-{day:02d}"))[0])
        verdicts = [o[0] for o in out]
        # week 1: first is new, 2nd and 3rd flagged (no history). week 2: first new; 2nd and 3rd flagged (only two dates, no cadence yet).
        self.assertEqual(verdicts[:6], [None, "possible_duplicate", "possible_duplicate", None, "possible_duplicate", "possible_duplicate"])
        # week 3: three dates 7 days apart: a cadence; counts match the earlier cycles
        self.assertEqual(verdicts[6:], [None] * 6)
        self.assertEqual(out[7], (None, "recurring_batch"))
        n += 1
        self.assertEqual(feed(d, I(f"A{n}", date="2026-04-22"))[0], ("possible_duplicate", "batch_surplus"))  # a 4th on a day that never had 4

    def test_batch_surplus_requires_more_than_every_earlier_cycle(self):
        d = DuplicateDetector()
        n = 0
        for day, k in ((1, 2), (8, 5), (15, 1)):
            for _ in range(k):
                n += 1
                feed(d, I(f"A{n}", date=f"2026-04-{day:02d}"))
        n += 1
        # day 15 already has one, a second one: day 8 had 5 >= 2, so it is a normal batch member
        self.assertEqual(feed(d, I(f"A{n}", date="2026-04-15"))[0], (None, "recurring_batch"))

    def test_irregular_series_not_exempt(self):
        d = DuplicateDetector()
        feed(d, I("A1", date="2026-04-01"), I("A2", date="2026-04-09"), I("A3", date="2026-04-30"))
        self.assertEqual(feed(d, I("A4", date="2026-04-30"))[0][0], "possible_duplicate")

    def test_cadence_off(self):
        d = DuplicateDetector(use_cadence=False)
        out = []
        for i, day in enumerate((1, 1, 8, 8, 15, 15)):
            out.append(feed(d, I(f"A{i}", date=f"2026-04-{day:02d}"))[0][0])
        self.assertEqual(out[5], "possible_duplicate")

    def test_resubmission_and_conflict_unchanged(self):
        d = DuplicateDetector()
        feed(d, I("A1"))
        self.assertEqual(d.check(I("A1")), "resubmission")
        self.assertEqual(d.check(I("A1", total="101.00")), "id_conflict")

    def test_check_returns_verdict_only(self):
        d = DuplicateDetector()
        feed(d, I("A1"))
        self.assertEqual(d.check(I("A2")), "possible_duplicate")

    def test_bad_date_string_does_not_crash(self):
        d = DuplicateDetector()
        feed(d, I("A1", date="not-a-date"))
        self.assertEqual(d.check(I("A2", date="2026-13-45"))[0:1] and d.check(I("A2", date="2026-13-45")), "possible_duplicate")


class CadenceHelper(unittest.TestCase):
    def dates(self, *days):
        return [datetime.date(2026, 4, 1) + datetime.timedelta(days=x) for x in days]

    def test_classes(self):
        w = self.dates(0, 7)
        self.assertTrue(_on_cadence(w, w[1] + datetime.timedelta(days=7)))
        f = self.dates(0, 14)
        self.assertTrue(_on_cadence(f, f[1] + datetime.timedelta(days=14)))
        m = self.dates(0, 30)
        self.assertTrue(_on_cadence(m, m[1] + datetime.timedelta(days=31)))

    def test_class_edges(self):
        for lo, hi in ((5, 9), (12, 16), (26, 35)):
            for g, want in ((lo - 1, False), (lo, True), (hi, True), (hi + 1, False)):
                base = self.dates(0, g)
                self.assertEqual(_on_cadence(base, base[1] + datetime.timedelta(days=g)), want, (lo, hi, g))

    def test_boundaries(self):
        base = self.dates(0, 5)
        self.assertTrue(_on_cadence(base, base[1] + datetime.timedelta(days=9)))
        self.assertFalse(_on_cadence(base, base[1] + datetime.timedelta(days=10)))
        self.assertFalse(_on_cadence(self.dates(0, 4), self.dates(0, 4)[1] + datetime.timedelta(days=4)))
        self.assertTrue(_on_cadence(self.dates(0, 26), self.dates(0, 26)[1] + datetime.timedelta(days=35)))
        self.assertFalse(_on_cadence(self.dates(0, 26), self.dates(0, 26)[1] + datetime.timedelta(days=36)))
        self.assertFalse(_on_cadence(self.dates(0, 25), self.dates(0, 25)[1] + datetime.timedelta(days=25)))

    def test_mixed_classes_and_short_series(self):
        self.assertFalse(_on_cadence(self.dates(0, 7), self.dates(0, 7)[1] + datetime.timedelta(days=30)))
        self.assertFalse(_on_cadence(self.dates(0), datetime.date(2026, 4, 8)))
        self.assertFalse(_on_cadence([], datetime.date(2026, 4, 8)))

    def test_middle_and_first_position(self):
        # the new date can sit in the middle or at the start of a regular run
        mid = self.dates(0, 14)
        self.assertTrue(_on_cadence(mid, datetime.date(2026, 4, 8)))
        start = self.dates(7, 14)
        self.assertTrue(_on_cadence(start, datetime.date(2026, 4, 1)))


if __name__ == "__main__":
    unittest.main()
