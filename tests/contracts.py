"""Behaviour contracts every DocMatch implementation must honour.

Each contract is f(factory) -> None, raising AssertionError on violation.
factory(pos) builds a fresh implementation. test_contract.py asserts the fixed
implementation passes all and the naive baseline fails (assertion or crash) every one.
"""
from helpers import inv_text, make_po


def _eq(a, b, msg=""):
    if a != b:
        raise AssertionError(f"{msg} expected {b!r}, got {a!r}")


def ambiguous_twin_pos_not_auto(f):
    pos = [make_po("PO-1", total="100.00", date="2026-03-01"), make_po("PO-2", total="100.00", date="2026-03-05")]
    r = f(pos).process([inv_text(po=None)])
    _eq(len(r["auto_matched"]), 0, "twin POs must not auto-match;")
    _eq(len(r["needs_review"]), 1)


def total_mismatch_with_ref_flagged(f):
    r = f([make_po(total="100.00")]).process([inv_text(lines=(("Widget", 1, "180.00"),))])
    _eq(len(r["auto_matched"]), 0, "80 percent over;")


def currency_mismatch_flagged(f):
    r = f([make_po(cur="EUR")]).process([inv_text(cur="USD")])
    _eq(len(r["auto_matched"]), 0, "currency mismatch;")


def vendor_mismatch_with_ref_flagged(f):
    pos = [make_po("PO-1", vendor="Mereside Logistics"), make_po("PO-9")]
    r = f(pos).process([inv_text(po="PO-1")])
    _eq(len(r["auto_matched"]), 0, "ref belongs to another vendor;")


def weak_fuzzy_vendor_flagged(f):
    r = f([make_po()]).process([inv_text(po=None, vendor="Brightwatr Suplies Ltd")])
    _eq(len(r["auto_matched"]), 0, "typo vendor is a weak tier;")


def no_candidate_flagged(f):
    r = f([make_po(total="9000.00")]).process([inv_text(po=None)])
    _eq(len(r["auto_matched"]), 0, "same vendor, wildly different total;")
    _eq(len(r["needs_review"]), 1)


def resubmitted_batch_not_double_counted(f):
    impl = f([make_po()])
    batch = [inv_text()]
    first = impl.process(batch)
    second = impl.process(batch)
    _eq(len(first["auto_matched"]) + len(second["auto_matched"]), 1, "same batch twice;")


def same_invoice_twice_in_batch_once(f):
    r = f([make_po()]).process([inv_text(), inv_text()])
    _eq(len(r["auto_matched"]), 1, "identical invoice twice in one batch;")


def rekeyed_duplicate_flagged(f):
    pos = [make_po("PO-1"), make_po("PO-2")]
    r = f(pos).process([inv_text(no="INV-1", po="PO-1"), inv_text(no="INV-9", po="PO-2")])
    _eq(len(r["auto_matched"]), 1, "same vendor+total+date under a new number;")


def lines_do_not_add_up_flagged(f):
    r = f([make_po(total="100.00")]).process([inv_text(lines=(("Widget", 1, "60.00"),), total="100.00")])
    _eq(len(r["auto_matched"]), 0, "line amounts sum to 60 but total says 100;")


def zero_total_flagged(f):
    r = f([make_po(total="100.00")]).process([inv_text(lines=(("Adjustment", 1, "0.00"),))])
    _eq(len(r["auto_matched"]), 0, "zero total;")


def partial_parts_not_reconciled(f):
    pos = [make_po(total="100.00")]
    p1 = inv_text(lines=(("Widget", 1, "50.00"),), part=(1, 2))
    r = f(pos).process([p1])
    _eq(len(r["auto_matched"]), 0, "only part 1 of 2 arrived;")


def parts_reconcile_when_complete(f):
    pos = [make_po(total="100.00")]
    p1 = inv_text(lines=(("Widget", 1, "50.00"),), part=(1, 2))
    p2 = inv_text(lines=(("Widget", 1, "50.00"),), part=(2, 2))
    impl = f(pos)
    r1 = impl.process([p2])
    r2 = impl.process([p1])
    _eq(len(r1["auto_matched"]) + len(r2["auto_matched"]), 1, "both parts arrived (reordered);")


def malformed_text_flagged(f):
    r = f([make_po()]).process(["this is not an invoice"])
    _eq(len(r["auto_matched"]), 0, "garbage text;")
    _eq(len(r["needs_review"]), 1)


def exception_queue_idempotent(f):
    impl = f([make_po(total="9000.00")])
    batch = [inv_text(po=None)]
    r1 = impl.process(batch)
    if "queue" not in r1:
        raise AssertionError("no exception queue in the result")
    n1 = len(r1["queue"])
    r2 = impl.process(batch)
    _eq(len(r2["queue"]), n1, "queue size after resubmission;")
    if n1 < 1:
        raise AssertionError("queue empty for a flagged invoice")


def same_po_billed_twice_flagged(f):
    impl = f([make_po("PO-1", total="100.00")])
    r = impl.process([inv_text(no="INV-1", date="2026-03-10"), inv_text(no="INV-2", date="2026-03-12")])
    _eq(len(r["auto_matched"]), 1, "two different invoices against one 100.00 PO;")


def odd_po_label_matches_the_named_po(f):
    pos = [make_po("PO-2", date="2026-03-05"), make_po("PO-1", date="2026-03-01")]
    text = inv_text(po=None).replace("Invoice No: INV-1", "Invoice No: INV-1\nPO Number PO-1")
    r = f(pos).process([text])
    got = [e["po_id"] for e in r["auto_matched"]]
    if got and got != ["PO-1"]:
        raise AssertionError(f"matched {got}, the invoice names PO-1")
    _eq(len(got), 1, "label variant must still be read;")


def decimal_comma_total_not_read_as_whole(f):
    r = f([make_po(total="1250.00")]).process([inv_text(po=None).replace("Total: 100.00", "Total: 12,50").replace("Subtotal: 100.00", "Subtotal: 12,50").replace("- Widget | 2 x 50.00 = 100.00\n", "")])
    _eq(len(r["auto_matched"]), 0, "12,50 is not 1250.00;")


CONTRACTS = [(n, fn) for n, fn in sorted(globals().items())
             if callable(fn) and not n.startswith("_") and n not in ("inv_text", "make_po")]
