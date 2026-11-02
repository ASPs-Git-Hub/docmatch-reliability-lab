"""Small shared helpers: money, vendor normalisation, Wilson interval."""
import math
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

_SUFFIX_CANON = {"ltd": "ltd", "limited": "ltd", "inc": "inc", "incorporated": "inc", "co": "co", "company": "co",
                 "llc": "llc", "corp": "corp", "corporation": "corp", "plc": "plc"}
_SUFFIXES = set(_SUFFIX_CANON)

# Strict money grammar: optional sign and one currency symbol, then plain digits or comma-grouped
# thousands (groups of exactly 3, and then a ".dd" part is mandatory), at most 2 decimals, at most 12 integer digits.
# Decimal-comma ("12,50", "1.250,00"), exponents, three-decimal values and anything else return None.
_MONEY_RE = re.compile(r"^(-?)\s*([$\u20ac\u00a3]?)\s*(-?)(\d{1,12}|\d{1,3}(?:,\d{3})+(?=\.))(?:\.(\d{1,2}))?$")


def money(text):
    """Parse '1,250.00', '$22.5' or '-5' to a 2dp Decimal. None if absent or not in the strict grammar."""
    if text is None:
        return None
    m = _MONEY_RE.match(str(text).strip())
    if not m:
        return None
    if m.group(1) and m.group(3):
        return None  # double sign
    neg = bool(m.group(1) or m.group(3))
    digits = m.group(4).replace(",", "") + "." + (m.group(5) or "0")
    try:
        v = Decimal(digits).quantize(Decimal("0.01"), ROUND_HALF_UP)
    except InvalidOperation:
        return None
    return -v if neg else v


def norm_vendor(name):
    """Lowercase, '&' to 'and', drop punctuation and company suffixes. Used for similarity only."""
    if not name:
        return ""
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = [t for t in s.split() if t not in _SUFFIXES]
    return " ".join(toks)


def legal_suffix(name):
    """Canonical legal-form suffix ('ltd', 'inc', ...) of a vendor name, or '' if none."""
    if not name:
        return ""
    toks = re.sub(r"[^a-z0-9 ]", " ", name.lower().replace("&", " and ")).split()
    return next((_SUFFIX_CANON[t] for t in reversed(toks) if t in _SUFFIX_CANON), "")


def vendor_identity(name):
    """Strict identity: stripped name plus canonical legal suffix. 'Kestrel Inc' != 'Kestrel Co' != 'Kestrel'."""
    n = norm_vendor(name)
    return (n + "|" + legal_suffix(name)) if n else ""


def norm_ref(ref):
    return ref.strip().upper() if ref else None


def wilson(k, n, z=1.959964):
    """Wilson score interval for k successes in n trials. Returns (lo, hi)."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))
