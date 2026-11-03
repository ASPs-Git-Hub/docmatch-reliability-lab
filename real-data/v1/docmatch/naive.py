"""NaiveDocMatch: the usual defects, kept on purpose as the baseline.

Defects: first PO whose vendor name merely contains the first 5 letters of the invoice vendor; no duplicate
detection; ignores totals and currency; auto-matches ambiguous candidates; processes the
same invoice every time it is submitted; no exception queue.
"""
from .extract import extract


class NaiveDocMatch:
    def __init__(self, pos, config=None, now=None):
        self.pos = list(pos)

    def process(self, batch):
        out = {"auto_matched": [], "needs_review": [], "skipped": []}
        for text in batch or []:
            inv = extract(text)
            vendor = (inv.vendor or "").lower()
            hit = next((p for p in self.pos if vendor[:5] in p["vendor"].lower()), None)
            entry = {"invoice_no": inv.invoice_no, "vendor": inv.vendor, "po_id": hit["po_id"] if hit else None}
            (out["auto_matched"] if hit else out["needs_review"]).append(entry)
        return out
