import os
import sys
from decimal import Decimal as D, ROUND_HALF_UP

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

VENDOR = "Brightwater Supplies Ltd"


def _q(x):
    return D(str(x)).quantize(D("0.01"), ROUND_HALF_UP)


def inv_text(no="INV-1", po="PO-1", vendor=VENDOR, date="2026-03-10", cur="USD",
             lines=(("Widget", 2, "50.00"),), tax="0.00", total=None, part=None):
    out = ["INVOICE", f"Invoice No: {no}"]
    if po:
        out.append(f"PO: {po}")
    if vendor:
        out.append(f"Vendor: {vendor}")
    out += [f"Date: {date}", f"Currency: {cur}"]
    if part:
        out.append(f"Part: {part[0]} of {part[1]}")
    out.append("Items:")
    sub = D(0)
    for d, qty, unit in lines:
        amt = _q(D(str(qty)) * D(str(unit)))
        sub += amt
        out.append(f"- {d} | {qty} x {_q(unit)} = {amt}")
    out += [f"Subtotal: {sub}", f"Tax: {_q(tax)}"]
    out.append(f"Total: {_q(sub + D(tax)) if total is None else _q(total)}")
    return "\n".join(out)


def make_po(po_id="PO-1", vendor=VENDOR, cur="USD", total="100.00", date="2026-03-01"):
    return {"po_id": po_id, "vendor": vendor, "currency": cur, "total": total, "date": date}
