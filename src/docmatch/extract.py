"""Regex extraction from synthetic invoice TEXT (no OCR, no images).

Each field gets a confidence: 1.0 labelled exactly, 0.7 weaker label, 0.5 fallback, 0.0 missing.
Extraction REFUSES instead of degrading: a recognisable-but-invalid field value (decimal-comma amount,
bad calendar date, malformed PO reference, unparsed item row, conflicting currency evidence, invalid
part declaration) is recorded in `inv.issues` and the field is left empty. validate.check_invoice turns
issues into review reasons; match() turns sub-1.0 confidence into review reasons.
"""
import datetime
import re
from dataclasses import dataclass, field
from decimal import Decimal

from .util import money, norm_ref

MAX_PARTS = 100
_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}
_NA = {"N/A", "NA", "NONE", "TBD"}
_REF_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/]*")
_DATE_OK = re.compile(r"\d{4}-\d{2}-\d{2}")
_INVNO_OK = re.compile(r"[A-Za-z0-9][\w\-/]*")


def _line_rx(label):
    """Whole-line value capture; [ \\t] (never \\s) after the label so a value cannot come from the next line."""
    return re.compile(r"^[ \t]*" + label + r"[ \t]*[:#]?[ \t]*(.*?)[ \t]*$", re.I | re.M)


_RE_INV = _line_rx(r"Invoice[ \t]*(?:No\.?|Number|#)")
_RE_INV_FALLBACK = re.compile(r"\b(INV[-/]\w[\w\-/]*)", re.I)
# PO label variants: "PO", "PO No", "PO Number", "Your PO", "Purchase Order [No]", "Order Ref/Number/No/#".
# After the label either a colon/hash or whitespace is required, so "POSTAGE: 5" is not a PO line.
_RE_PO = re.compile(
    r"^[ \t]*(?:Your[ \t]+)?(?:(?:PO|Purchase[ \t]+Order)(?:[ \t]+(?:No\.?|Ref(?:erence)?|Number|#))?"
    r"|Order[ \t]+(?:No\.?|Ref(?:erence)?|Number|#))(?:[ \t]*[:#][ \t]*|[ \t]+)(.*?)[ \t]*$", re.I | re.M)
# Any PO-shaped token anywhere in the text (needs a digit): "PO-17", "PO/A9", "PO1234".
_RE_PO_TOKEN = re.compile(r"\bPO[-/]?(?=[A-Z0-9]*\d)[A-Z0-9]+\b", re.I)
_RE_VENDOR = _line_rx(r"(?:Vendor|Supplier|From)[ \t]*:")
_RE_DATE = _line_rx(r"(?:Invoice[ \t]+)?Date[ \t]*:")
_RE_CUR = _line_rx(r"Currency[ \t]*:")
_RE_SUB = _line_rx(r"Subtotal[ \t]*:")
_RE_TAX = _line_rx(r"Tax[ \t]*:")
_RE_TOTAL = _line_rx(r"Total[ \t]*:")
_RE_TOTAL_ALT = _line_rx(r"(?:Amount Due|Grand Total)[ \t]*:")
_RE_BULLET = re.compile(r"^[ \t]*[-•*][ \t]+(.*?)[ \t]*$", re.M)
_RE_ITEM = re.compile(r"^(.+?)[ \t]*(?:\||\t)[ \t]*(\d+(?:\.\d+)?)[ \t]*[xX×][ \t]*(\S+)[ \t]*=[ \t]*(\S+)$")
_RE_ITEMS_HDR = re.compile(r"^[ \t]*Items[ \t]*:", re.I | re.M)
_RE_PART_LINE = re.compile(r"^[ \t]*Part(?:[ \t]*[:#]|[ \t]+-?\d).*$", re.I | re.M)
_RE_PART = re.compile(r"^[ \t]*Part[ \t]*[:#]?[ \t]*(\d{1,6})[ \t]*(?:of|/)[ \t]*(\d{1,6})[ \t]*$", re.I)


@dataclass
class Invoice:
    invoice_no: str = None
    po_ref: str = None
    vendor: str = None
    date: str = None
    currency: str = None
    items: list = field(default_factory=list)  # (desc, qty, unit, amount)
    subtotal: Decimal = None
    tax: Decimal = None
    total: Decimal = None
    part: tuple = None  # (i, n)
    conf: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)  # extraction refusals, become review reasons
    ref_tokens: list = field(default_factory=list)  # PO-shaped tokens seen anywhere in the text


def _all(rx, text):
    return [v for v in rx.findall(text)]


def _single(rx, text, name, issues):
    """First non-empty captured value; records `conflicting_<name>` if distinct non-empty values disagree."""
    vals = [v for v in _all(rx, text) if v]
    if len({v.upper() for v in vals}) > 1:
        issues.append(f"conflicting_{name}")
    return vals[0] if vals else None


def _amount(rx, text, name, issues):
    """Return (Decimal or None, raw). Labelled but unparseable values record `<name>_unparseable`."""
    raw = _single(rx, text, name, issues)
    if raw is None:
        return None, None
    v = money(raw)
    if v is None:
        issues.append(f"{name}_unparseable")
    return v, raw


def _symbol_codes(raw):
    return {_SYMBOLS[s] for s in _SYMBOLS if raw and s in raw}


def extract(text):
    """Never raises: non-string or garbage input yields an Invoice with missing fields."""
    inv = Invoice()
    if not isinstance(text, str):
        text = ""
    c, issues = inv.conf, inv.issues
    # invoice number
    v = _single(_RE_INV, text, "invoice_no", issues)
    if v and _INVNO_OK.fullmatch(v):
        inv.invoice_no, c["invoice_no"] = v.upper(), 1.0
    else:
        if v:
            issues.append("invoice_no_invalid")
        m = _RE_INV_FALLBACK.search(text)
        inv.invoice_no, c["invoice_no"] = (m.group(1).upper(), 0.5) if m else (None, 0.0)
    # PO reference
    refs = [r for r in _all(_RE_PO, text) if r]
    refs = [r for r in refs if r.upper() not in _NA]
    bad = [r for r in refs if not _REF_OK.fullmatch(r)]
    good = {norm_ref(r) for r in refs if _REF_OK.fullmatch(r)}
    if bad:
        issues.append("po_ref_invalid")
    if len(good) > 1:
        issues.append("conflicting_po_ref")
    if good and not bad and len(good) == 1:
        inv.po_ref, c["po_ref"] = next(iter(good)), 1.0
    else:
        c["po_ref"] = 0.0
    if inv.po_ref is None:
        inv.ref_tokens = sorted({m.group(0).upper() for m in _RE_PO_TOKEN.finditer(text)})
    # vendor
    v = _single(_RE_VENDOR, text, "vendor", issues)
    inv.vendor, c["vendor"] = (v, 1.0) if v else (None, 0.0)
    # date: labelled, ISO, real calendar date only. No free-text date fallback.
    v = _single(_RE_DATE, text, "date", issues)
    inv.date, c["date"] = None, 0.0
    if v:
        try:
            if not _DATE_OK.fullmatch(v):
                raise ValueError
            datetime.date.fromisoformat(v)
            inv.date, c["date"] = v, 1.0
        except ValueError:
            issues.append("date_invalid")
    # amounts
    inv.subtotal, raw_sub = _amount(_RE_SUB, text, "subtotal", issues)
    inv.tax, raw_tax = _amount(_RE_TAX, text, "tax", issues)
    c["subtotal"] = 1.0 if inv.subtotal is not None else 0.0
    c["tax"] = 1.0 if inv.tax is not None else 0.0
    total, raw_total = _amount(_RE_TOTAL, text, "total", issues)
    alt, raw_alt = _amount(_RE_TOTAL_ALT, text, "amount_due", issues)
    if total is not None:
        inv.total, c["total"] = total, 1.0
        if alt is not None and alt != total:
            issues.append("amount_due_differs_from_total")
    elif alt is not None and raw_total is None:
        inv.total, c["total"] = alt, 0.7  # weaker label: gated to review by match()
    else:
        c["total"] = 0.0
    # currency: explicit code only. A bare symbol is ambiguous ($ = USD/CAD/AUD...), so it is never inferred.
    v = _single(_RE_CUR, text, "currency", issues)
    inv.currency, c["currency"] = None, 0.0
    if v:
        if re.fullmatch(r"[A-Za-z]{3}", v):
            inv.currency, c["currency"] = v.upper(), 1.0
        else:
            issues.append("currency_invalid")
    sym_codes = set()
    for raw in (raw_total, raw_sub, raw_tax, raw_alt):
        sym_codes |= _symbol_codes(raw)
    if len(sym_codes) > 1:
        issues.append("conflicting_currency_symbols")
    if inv.currency is None and sym_codes:
        issues.append("currency_symbol_only")
    elif inv.currency and sym_codes and not (inv.currency == "USD" and "USD" in sym_codes) and inv.currency not in sym_codes:
        issues.append("conflicting_currency")
    # item rows
    candidates = [m.group(1) for m in _RE_BULLET.finditer(text)]
    for cand in candidates:
        m = _RE_ITEM.match(cand)
        row = None
        if m:
            d, qty, unit, amt = m.groups()
            unit_v, amt_v = money(unit), money(amt)
            if unit_v is not None and amt_v is not None:
                row = (d, Decimal(qty), unit_v, amt_v)
        if row:
            inv.items.append(row)
        else:
            issues.append("items_unparsed")
    if _RE_ITEMS_HDR.search(text) and not candidates:
        issues.append("items_unparsed")
    c["items"] = 1.0 if inv.items else 0.0
    # part declaration
    pl = _RE_PART_LINE.findall(text)
    if len(pl) > 1:
        issues.append("part_invalid")
    elif pl:
        m = _RE_PART.match(pl[0])
        if m and 1 <= int(m.group(1)) <= int(m.group(2)) <= MAX_PARTS:
            inv.part = (int(m.group(1)), int(m.group(2)))
        else:
            issues.append("part_invalid")
    inv.issues = list(dict.fromkeys(issues))
    return inv
