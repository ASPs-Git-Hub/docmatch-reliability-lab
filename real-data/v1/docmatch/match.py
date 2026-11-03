"""Strict tiered invoice-to-PO matching. Auto-match only on a unique, strong, same-currency hit.

Tiers:
  1  exact PO ref, vendor agrees (similarity AND same legal suffix), total within tolerance,
     currency equal, no closer same-vendor candidate                       -> MATCH
  2  exact vendor identity (name + legal suffix) + total within tolerance + date window,
     only when the invoice shows no PO-shaped token anywhere and no same-total twin sits
     outside the window                                                     -> MATCH if unique
  3  fuzzy vendor + total within tolerance (no date test)                   -> never MATCH
Anything else is AMBIGUOUS (a human decides) or UNMATCHED (nothing plausible).
A field with 0 < confidence < 1 (weaker label) on a field the tier relies on is never auto-matched.
Tolerance rule: under-billing |invoice - po| <= max(rel * po_total, floor), inclusive; over-billing is
additionally capped at max_over (absolute). Defaults rel 2%, floor 1.00, max_over 50.00.
"""
import datetime
import difflib
from dataclasses import dataclass, field
from decimal import Decimal

from .util import legal_suffix, money, norm_ref, norm_vendor, vendor_identity


@dataclass
class MatchConfig:
    rel: Decimal = Decimal("0.02")
    floor: Decimal = Decimal("1.00")
    window_before_days: int = 3
    window_after_days: int = 90
    fuzzy_threshold: float = 0.85
    max_over: Decimal = Decimal("50.00")


@dataclass
class MatchResult:
    status: str  # MATCH | AMBIGUOUS | UNMATCHED
    po_id: str = None
    tier: int = None
    candidates: list = field(default_factory=list)
    reasons: list = field(default_factory=list)


def _d(s):
    try:
        return datetime.date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def tolerance(po_total, cfg):
    return max(abs(po_total) * cfg.rel, cfg.floor)


def within_tolerance(inv_total, po_total, cfg):
    if inv_total is None or po_total is None:
        return False
    diff = inv_total - po_total
    if diff > 0:  # over-billing: relative band, but never more than the absolute cap
        return diff <= min(tolerance(po_total, cfg), cfg.max_over)
    return -diff <= tolerance(po_total, cfg)


def vendor_similarity(a, b):
    a, b = norm_vendor(a), norm_vendor(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def in_window(inv_date, po_date, cfg):
    i, p = _d(inv_date), _d(po_date)
    if i is None or p is None:
        return False
    return -cfg.window_before_days <= (i - p).days <= cfg.window_after_days


def _po_total(po):
    return money(po.get("total"))


def _pick(cands, inv, tier, reasons_if_many):
    """Resolve a candidate list at a MATCH-capable tier."""
    same_cur = [p for p in cands if (p.get("currency") or "").upper() == (inv.currency or "").upper() and inv.currency]
    if same_cur:
        if len(same_cur) == 1:
            return MatchResult("MATCH", same_cur[0]["po_id"], tier, [same_cur[0]["po_id"]])
        return MatchResult("AMBIGUOUS", None, tier, [p["po_id"] for p in same_cur], [reasons_if_many])
    return MatchResult("AMBIGUOUS", None, tier, [p["po_id"] for p in cands], ["currency_mismatch"])


def _low_conf(inv, fields):
    return ["low_confidence_" + f for f in fields if 0.0 < inv.conf.get(f, 0.0) < 1.0]


def _vendor_agrees(inv_vendor, po_vendor, cfg):
    if vendor_similarity(inv_vendor, po_vendor) < cfg.fuzzy_threshold:
        return False
    a, b = legal_suffix(inv_vendor), legal_suffix(po_vendor)
    return not (a and b and a != b)


def match(inv, pos, cfg=None):
    cfg = cfg or MatchConfig()
    pos = pos or []
    if inv.total is None or (inv.vendor is None and inv.po_ref is None):
        return MatchResult("UNMATCHED", reasons=["insufficient_fields"])
    weak = _low_conf(inv, ("vendor", "currency", "total", "date"))
    if weak:
        return MatchResult("AMBIGUOUS", tier=None, reasons=weak)
    # Tier 1: PO ref
    if inv.po_ref:
        found = [p for p in pos if norm_ref(p.get("po_id")) == inv.po_ref]
        if not found:
            return MatchResult("AMBIGUOUS", tier=1, reasons=["po_ref_unknown"])
        if len(found) > 1:
            return MatchResult("AMBIGUOUS", tier=1, candidates=[p["po_id"] for p in found], reasons=["po_ref_duplicated"])
        p = found[0]
        reasons = []
        if not _vendor_agrees(inv.vendor, p.get("vendor"), cfg):
            reasons.append("vendor_mismatch")
        if not within_tolerance(inv.total, _po_total(p), cfg):
            reasons.append("total_mismatch")
        if not inv.currency or inv.currency.upper() != (p.get("currency") or "").upper():
            reasons.append("currency_mismatch")
        if not reasons and inv.total is not None:
            pt = _po_total(p)
            closer = [q["po_id"] for q in pos if q is not p
                      and _vendor_agrees(inv.vendor, q.get("vendor"), cfg)
                      and (q.get("currency") or "").upper() == inv.currency.upper()
                      and within_tolerance(inv.total, _po_total(q), cfg)
                      and abs(inv.total - _po_total(q)) < abs(inv.total - pt)]
            if closer:
                return MatchResult("AMBIGUOUS", tier=1, candidates=[p["po_id"]] + closer, reasons=["closer_candidate_exists"])
        if reasons:
            return MatchResult("AMBIGUOUS", tier=1, candidates=[p["po_id"]], reasons=reasons)
        return MatchResult("MATCH", p["po_id"], 1, [p["po_id"]])
    # A PO-shaped token somewhere in the text means a reference exists that we could not read as the
    # labelled reference. Guessing a PO by vendor+amount then is how the wrong twin gets paid.
    if inv.ref_tokens:
        return MatchResult("AMBIGUOUS", tier=2, reasons=["unlabelled_ref_present"])
    # Tier 2: exact vendor identity + total + window
    vi = vendor_identity(inv.vendor)
    t2_all = [p for p in pos if vi and vendor_identity(p.get("vendor")) == vi
              and within_tolerance(inv.total, _po_total(p), cfg)
              and (p.get("currency") or "").upper() == (inv.currency or "").upper()]
    t2 = [p for p in t2_all if in_window(inv.date, p.get("date"), cfg)]
    if t2:
        if len(t2_all) > len(t2):
            return MatchResult("AMBIGUOUS", None, 2, [p["po_id"] for p in t2_all], ["twin_outside_window"])
        return _pick(t2, inv, 2, "multiple_candidates")
    t2_any_cur = [p for p in pos if vi and vendor_identity(p.get("vendor")) == vi
                  and within_tolerance(inv.total, _po_total(p), cfg) and in_window(inv.date, p.get("date"), cfg)]
    if t2_any_cur:
        return _pick(t2_any_cur, inv, 2, "multiple_candidates")
    # Tier 3: fuzzy vendor + total, weak: never auto
    t3 = [p for p in pos if vendor_similarity(inv.vendor, p.get("vendor")) >= cfg.fuzzy_threshold
          and within_tolerance(inv.total, _po_total(p), cfg)]
    if t3:
        return MatchResult("AMBIGUOUS", None, 3, [p["po_id"] for p in t3], ["weak_tier_only"])
    return MatchResult("UNMATCHED", reasons=["no_candidate"])
