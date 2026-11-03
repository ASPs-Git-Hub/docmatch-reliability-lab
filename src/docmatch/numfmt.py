"""Reading amounts written in different number conventions, without letting a wrong amount through.

util.money() is strict and stays that way (PO totals use it). This module is used by extract() for the amounts
printed on an invoice. A token is read under two conventions:
  US: comma groups thousands, dot is the decimal mark   1,234.56
  EU: dot groups thousands, comma is the decimal mark   1.234,56
Space (also no-break and narrow no-break) and apostrophe can group thousands under either convention.

A token such as 1.234 or 60.000 reads differently under the two conventions. It is accepted only when something in
the same document decides it: another token that only one convention can read, a declared currency whose minor-unit
count rules a reading out, a declared locale, or arithmetic (the lines add up under exactly one convention).
Otherwise the token is refused. See real-data/PROTOCOL-v2.md for the exact rules.
"""
import re
from decimal import Decimal

CENT = Decimal("0.01")
CONVS = ("US", "EU")
_GROUP_CHAR = {"US": ",", "EU": "."}
_DEC_CHAR = {"US": ".", "EU": ","}
_SPACES = "   "
_SPACE_GROUPS = _SPACES + "'’"

# ISO 4217 minor-unit counts that differ from 2. IDR: ISO 4217 lists 2, but rupiah amounts are written without
# decimals in practice; listing it with 0 is a stated choice (PROTOCOL-v2.md).
_ZERO_DECIMAL = {"BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF", "IDR"}
_THREE_DECIMAL = {"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"}

# Declared locale tags that say which convention a document uses. Anything not listed is ignored (no evidence).
_LOCALE_EU = {"de-DE", "de-AT", "fr-FR", "es-ES", "it-IT", "nl-NL", "nl-BE", "pt-BR", "pt-PT", "id-ID", "tr-TR", "ru-RU",
              "pl-PL", "sv-SE", "da-DK", "fi-FI", "nb-NO", "cs-CZ", "hu-HU", "ro-RO", "vi-VN"}
_LOCALE_US = {"en-US", "en-GB", "en-AU", "en-CA", "en-IN", "en-IE", "en-NZ", "ja-JP", "zh-CN", "ko-KR", "th-TH", "he-IL"}

_SHELL = re.compile(r"^(-?)\s*([$€£]?)\s*(-?)(.+)$")
_PLAIN = re.compile(r"\d{1,12}")
_FRAC = re.compile(r"\d{1,3}")


def minor_digits(currency):
    """Number of minor-unit digits for an ISO code, or None when no currency is known."""
    if not currency:
        return None
    c = currency.upper()
    return 0 if c in _ZERO_DECIMAL else 3 if c in _THREE_DECIMAL else 2


def locale_convention(tag):
    """'US' or 'EU' for an allow-listed locale tag, else None."""
    if not tag:
        return None
    t = tag.strip().replace("_", "-")
    parts = t.split("-")
    if len(parts) == 2:
        t = parts[0].lower() + "-" + parts[1].upper()
    return "EU" if t in _LOCALE_EU else "US" if t in _LOCALE_US else None


def _group_ok(ip, group_chars):
    """ip like '1.234' or '12 345 678': first group 1-3 digits not starting with 0, then groups of exactly 3, one separator char."""
    sep = None
    for ch in ip:
        if not ch.isdigit():
            if ch not in group_chars:
                return False
            if sep is None:
                sep = ch
            elif ch != sep:
                return False
    if sep is None:
        return False
    first, *rest = ip.split(sep)
    return bool(re.fullmatch(r"[1-9]\d{0,2}", first)) and all(re.fullmatch(r"\d{3}", g) for g in rest)


def read_token(token, conv, digits=None):
    """Exact Decimal value of `token` under convention `conv` ('US'/'EU'), or None if the token is not valid there.
    `digits`: minor-unit count of the declared currency; a longer fraction is invalid."""
    if token is None:
        return None
    m = _SHELL.match(str(token).strip())
    if not m:
        return None
    s1, _sym, s2, body = m.groups()
    if s1 and s2:
        return None
    body = body.strip()
    dec = _DEC_CHAR[conv]
    if body.count(dec) > 1:
        return None
    if dec in body:
        ip, fp = body.split(dec)
        if not _FRAC.fullmatch(fp):
            return None
    else:
        ip, fp = body, ""
    if _PLAIN.fullmatch(ip):
        intdigits = ip
    elif _group_ok(ip, _GROUP_CHAR[conv] + _SPACE_GROUPS):
        intdigits = re.sub(r"\D", "", ip)
        if len(intdigits) > 12:
            return None
    else:
        return None
    if digits is not None and len(fp) > digits:
        return None
    v = Decimal(intdigits + "." + (fp or "0"))
    return -v if (s1 or s2) else v


def _reads(tokens, digits):
    """name -> {conv: value} for each convention under which the token reads."""
    out = {}
    for name, raw in tokens.items():
        d = {}
        for conv in CONVS:
            v = read_token(raw, conv, digits)
            if v is not None:
                d[conv] = v
        out[name] = d
    return out


def _close(a, b):
    return abs(a - b) <= CENT


def arithmetic_checks(values, items):
    """Applicable relations evaluated on `values` (name -> Decimal or None). Returns a list of bools.
    items: list of (index, qty) for item rows; tokens are named item<i>_unit and item<i>_amt."""
    checks = []
    amts = []
    for i, qty in items:
        unit, amt = values.get(f"item{i}_unit"), values.get(f"item{i}_amt")
        if unit is not None and amt is not None:
            checks.append(_close((qty * unit).quantize(CENT), amt))
        if amt is not None:
            amts.append(amt)
    sub, tax, tot = values.get("subtotal"), values.get("tax"), values.get("total")
    line_sum = sum(amts, Decimal(0)) if amts and len(amts) == len(items) else None
    if line_sum is not None and sub is not None:
        checks.append(_close(line_sum, sub))
    base = sub if sub is not None else line_sum
    if base is not None and tot is not None:
        checks.append(_close(base + (tax if tax is not None else Decimal(0)), tot))
    return checks


def resolve(tokens, items=(), currency=None, assume_currency=None, locale=None):
    """Read every amount token of one document under ONE convention.
    tokens: name -> raw text (names: subtotal, tax, total, amount_due, item<i>_unit, item<i>_amt).
    items: list of (i, Decimal qty) for the item rows.
    Returns (values, issues, inferred, evidence): values name -> Decimal or None (refused); issues list of strings;
    inferred set of names whose value was decided by evidence rather than read unambiguously; evidence list of the
    kinds used ('currency', 'document_convention', 'locale', 'arithmetic')."""
    cur = currency or assume_currency
    digits = minor_digits(cur)
    values = {n: None for n in tokens}
    issues = []
    inferred = set()
    evidence = []
    if not tokens:
        return values, issues, inferred, evidence
    with_cur = _reads(tokens, digits)
    no_cur = _reads(tokens, None)
    dead = [n for n, d in with_cur.items() if not d]
    if dead:
        for n in dead:
            issues.append(f"{n}_unparseable")
    live = {n: d for n, d in with_cur.items() if d}
    if not live:
        return values, issues, inferred, evidence
    common = [c for c in CONVS if all(c in d for d in live.values())]
    if not common:
        # the tokens contradict each other about the number style
        issues.append("mixed_number_formats")
        for n, d in live.items():
            if len({v for v in d.values()}) == 1 and len(d) == 2:
                values[n] = next(iter(d.values()))  # plain digits mean the same everywhere
            else:
                issues.append(f"{n}_unparseable")
        return _gate(values, issues, inferred, evidence)

    def ambiguous(name, convs):
        vs = {with_cur[name][c] for c in convs}
        return len(vs) > 1

    amb = [n for n in live if ambiguous(n, common)]
    chosen = None
    if len(common) == 1:
        chosen = common[0]
        # inferred when the token on its own (without the rest of the document or without the currency) was open
        for n in live:
            if len(no_cur[n]) == 2 and len({v for v in no_cur[n].values()}) > 1:
                inferred.add(n)
                evidence.append("currency" if len(with_cur[n]) == 1 else "document_convention")
    elif not amb:
        chosen = common[0]  # every token means the same under both conventions
    else:
        loc = locale_convention(locale)
        holds = {c: all(arithmetic_checks({n: with_cur[n].get(c) for n in live}, items)) for c in common}
        has_checks = bool(arithmetic_checks({n: with_cur[n].get(common[0]) for n in live}, items))
        arith = [c for c in common if holds[c]] if has_checks else []
        arith_pick = arith[0] if len(arith) == 1 else None
        if loc and arith_pick and loc != arith_pick:
            issues.append("locale_conflicts_arithmetic")
            for n in amb:
                values[n] = None
            for n in live:
                if n not in amb:
                    values[n] = with_cur[n][common[0]]
            return _gate(values, issues, inferred, evidence)
        chosen = loc if loc in common else arith_pick
        if chosen is None:
            for n in amb:
                issues.append(f"{n}_ambiguous_format")
            for n in live:
                if n not in amb:
                    values[n] = with_cur[n][common[0]]
            return _gate(values, issues, inferred, evidence)
        inferred.update(amb)
        evidence.extend(k for k, hit in (("locale", chosen == loc), ("arithmetic", chosen == arith_pick)) if hit)
    evidence[:] = list(dict.fromkeys(evidence))
    for n in live:
        values[n] = with_cur[n][chosen]
    return _gate(values, issues, inferred, evidence)


def _gate(values, issues, inferred, evidence):
    """A value that is not a whole number of cents is never returned."""
    for n, v in list(values.items()):
        if v is None:
            continue
        if v != v.quantize(CENT):
            values[n] = None
            issues.append(f"{n}_not_2dp")
        else:
            values[n] = v.quantize(CENT)
    return values, issues, inferred, evidence
