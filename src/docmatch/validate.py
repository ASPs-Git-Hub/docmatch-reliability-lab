"""Invoice sanity checks, duplicate detection, multi-part tracking."""
import datetime
from decimal import Decimal, ROUND_HALF_UP

from .extract import MAX_PARTS
from .util import vendor_identity

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


# Cadence classes (days between consecutive payment dates) used by DuplicateDetector. Fixed, not tuned.
CADENCES = ((5, 9), (12, 16), (26, 35))


def _cadence_class(gap):
    return next((i for i, (lo, hi) in enumerate(CADENCES) if lo <= gap <= hi), None)


def _on_cadence(dates, d):
    """True if `d` sits in a run of three consecutive distinct dates whose two gaps fall in the same cadence class."""
    u = sorted(set(dates) | {d})
    i = u.index(d)
    for start in (i - 2, i - 1, i):
        if start < 0 or start + 2 >= len(u):
            continue
        g1, g2 = (u[start + 1] - u[start]).days, (u[start + 2] - u[start + 1]).days
        k = _cadence_class(g1)
        if k is not None and k == _cadence_class(g2):
            return True
    return False


class DuplicateDetector:
    """Identity is (vendor_identity, invoice_no, part). Possible duplicates are judged on K = (vendor_identity, total,
    currency) and are recurrence-aware: distinct references, repeats outside a short window and regular batches
    (weekly, fortnightly, monthly) are not flagged. Exact rules: real-data/PROTOCOL-v2.md."""

    def __init__(self, window_days=3, use_cadence=True, use_context=True):
        self.window_days = window_days
        self.use_cadence = use_cadence
        self.use_context = use_context
        self.by_id = {}
        self.by_key = {}  # K -> list of (date or None, invoice_no, po_ref, context)

    @staticmethod
    def id_key(inv):
        return (vendor_identity(inv.vendor), inv.invoice_no, inv.part)

    @staticmethod
    def event_key(inv):
        return (vendor_identity(inv.vendor), inv.total, inv.currency)

    @staticmethod
    def _date(inv):
        try:
            return datetime.date.fromisoformat(inv.date) if inv.date else None
        except (TypeError, ValueError):
            return None

    def _distinct(self, e, inv):
        if e[2] and inv.po_ref and e[2] != inv.po_ref:
            return True
        return bool(self.use_context and e[3] is not None and inv.context is not None and e[3] != inv.context)

    def check_detail(self, inv):
        """Return (verdict, why). verdict: 'resubmission', 'id_conflict', 'possible_duplicate' or None."""
        k = self.id_key(inv)
        if k in self.by_id:
            return ("resubmission" if self.by_id[k] == fingerprint(inv) else "id_conflict"), "same_identity"
        earlier = [e for e in self.by_key.get(self.event_key(inv), []) if e[1] != inv.invoice_no]
        if not earlier:
            return None, "first_seen"
        if inv.po_ref and any(e[2] == inv.po_ref for e in earlier):
            return "possible_duplicate", "same_reference"
        near_pool = [e for e in earlier if not self._distinct(e, inv)]
        if not near_pool:
            return None, "distinct"
        d = self._date(inv)
        near = [e for e in near_pool if (e[0] is None and d is None) or
                (e[0] is not None and d is not None and abs((e[0] - d).days) <= self.window_days)]
        if not near:
            return None, "outside_window"
        if self.use_cadence and d is not None:
            dates = [e[0] for e in near_pool if e[0] is not None]
            if _on_cadence(dates, d):
                counts = {}
                for e in near_pool:
                    counts[e[0]] = counts.get(e[0], 0) + 1
                if d not in counts:
                    return None, "recurring_batch"
                if any(n >= counts[d] + 1 for dd, n in counts.items() if dd != d):
                    return None, "recurring_batch"
                return "possible_duplicate", "batch_surplus"
        return "possible_duplicate", "near_no_cadence"

    def check(self, inv):
        """Return 'resubmission', 'id_conflict', 'possible_duplicate' or None."""
        return self.check_detail(inv)[0]

    def register(self, inv):
        self.by_id.setdefault(self.id_key(inv), fingerprint(inv))
        self.by_key.setdefault(self.event_key(inv), []).append((self._date(inv), inv.invoice_no, inv.po_ref, inv.context))


class PartTracker:
    """Collect 'part i of n' invoices per (vendor, invoice_no, po_ref); complete only when 1..n all arrived."""

    def __init__(self):
        self.groups = {}

    @staticmethod
    def group_key(inv):
        return (vendor_identity(inv.vendor), inv.invoice_no, inv.po_ref)

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
