"""Invoice sanity checks, duplicate detection, multi-part tracking."""
from decimal import Decimal, ROUND_HALF_UP

from .extract import MAX_PARTS
from .util import norm_vendor

CENT = Decimal("0.01")


def check_invoice(inv):
    """Return a list of reason strings; empty means the invoice is internally sound."""
    reasons = list(inv.issues)
    if not inv.invoice_no or not inv.vendor or inv.total is None or not inv.date:
        reasons.append("malformed")
        return reasons
    if 0.0 < inv.conf.get("invoice_no", 0.0) < 1.0:
        reasons.append("low_confidence_invoice_no")
    if inv.total <= 0:
        reasons.append("non_positive_total")
    for _d, qty, unit, amt in inv.items:
        if abs((qty * unit).quantize(CENT, ROUND_HALF_UP) - amt) > CENT:
            reasons.append("line_arithmetic")
            break
    if inv.items:
        line_sum = sum((it[3] for it in inv.items), Decimal(0))
        if inv.subtotal is not None and abs(line_sum - inv.subtotal) > CENT:
            reasons.append("subtotal_mismatch")
        expected = line_sum + (inv.tax or Decimal(0))
        if abs(expected - inv.total) > CENT:
            reasons.append("total_mismatch_lines")
    elif inv.subtotal is not None and abs(inv.subtotal + (inv.tax or Decimal(0)) - inv.total) > CENT:
        reasons.append("total_mismatch_subtotal")
    return reasons


def fingerprint(inv):
    """All canonical content: a same-number invoice with any changed content is a conflict, not a resubmission."""
    return (inv.total, inv.date, inv.po_ref, inv.currency, inv.subtotal, inv.tax, tuple(inv.items))


class DuplicateDetector:
    """Keys: (vendor, invoice_no, part) is identity; (vendor, total, date) catches re-keyed copies."""

    def __init__(self):
        self.by_id = {}
        self.by_content = {}
        self.by_po = {}

    @staticmethod
    def id_key(inv):
        return (norm_vendor(inv.vendor), inv.invoice_no, inv.part)

    def check(self, inv):
        """Return 'resubmission', 'id_conflict', 'possible_duplicate' or None."""
        k = self.id_key(inv)
        if k in self.by_id:
            return "resubmission" if self.by_id[k] == fingerprint(inv) else "id_conflict"
        ck = (norm_vendor(inv.vendor), inv.total, inv.date)
        other = self.by_content.get(ck)
        if other is not None and other != inv.invoice_no:
            return "possible_duplicate"
        # same vendor + amount + currency + PO under a different number and date (re-keyed copy)
        if inv.po_ref:
            other = self.by_po.get((norm_vendor(inv.vendor), inv.total, inv.currency, inv.po_ref))
            if other is not None and other != inv.invoice_no:
                return "possible_duplicate"
        return None

    def register(self, inv):
        self.by_id.setdefault(self.id_key(inv), fingerprint(inv))
        self.by_content.setdefault((norm_vendor(inv.vendor), inv.total, inv.date), inv.invoice_no)
        if inv.po_ref:
            self.by_po.setdefault((norm_vendor(inv.vendor), inv.total, inv.currency, inv.po_ref), inv.invoice_no)


class PartTracker:
    """Collect 'part i of n' invoices per (vendor, invoice_no, po_ref); complete only when 1..n all arrived."""

    def __init__(self):
        self.groups = {}

    @staticmethod
    def group_key(inv):
        return (norm_vendor(inv.vendor), inv.invoice_no, inv.po_ref)

    def add(self, inv):
        """Return ('incomplete'|'complete'|'conflict', parts_dict_or_None)."""
        i, n = inv.part
        if not (1 <= i <= n <= MAX_PARTS):
            return "conflict", None
        g = self.groups.setdefault(self.group_key(inv), {"n": n, "parts": {}, "cur": inv.currency, "date": inv.date})
        if g["n"] != n or g["cur"] != inv.currency or g["date"] != inv.date:
            return "conflict", None
        if i in g["parts"] and g["parts"][i].total != inv.total:
            return "conflict", None
        g["parts"][i] = inv
        if len(g["parts"]) == n:  # keys are validated unique ints in 1..n, so count equality is completeness
            return "complete", g["parts"]
        return "incomplete", None
