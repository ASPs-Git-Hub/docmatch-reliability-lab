"""DocMatch pipeline: extract -> validate -> dedupe -> match -> auto_matched / needs_review.

process() is idempotent on (vendor, invoice_no, part): resubmitting an identical invoice
lands in 'skipped', never twice in auto_matched or the queue.
"""
import datetime
import hashlib
import threading
from decimal import Decimal

from .extract import Invoice, extract
from .match import MatchConfig, _po_total, match, within_tolerance
from .queue import ExceptionQueue
from .util import norm_vendor
from .validate import DuplicateDetector, PartTracker, check_invoice


class DocMatch:
    def __init__(self, pos, config=None, now=None):
        self.pos = list(pos)
        self.cfg = config or MatchConfig()
        self.now = now or datetime.date.today()
        self.queue = ExceptionQueue()
        self.dups = DuplicateDetector()
        self.parts = PartTracker()
        self.consumed = {}  # po_id -> list of (vendor, invoice_no, total): a PO is billed once; later claims go to review
        self._lock = threading.Lock()  # process() is atomic per instance; there is no cross-instance or persisted state

    def process(self, batch):
        out = {"auto_matched": [], "needs_review": [], "skipped": []}
        with self._lock:
            for text in batch or []:
                try:
                    self._one(text, out)
                except Exception as exc:  # isolate one bad document from the rest of the batch
                    self._review(extract(None), ["processing_error:" + type(exc).__name__], out,
                                 text if isinstance(text, str) else repr(text))
        out["queue"] = self.queue.list_sorted(self.now)
        return out

    # -- helpers
    def _entry(self, inv, status, reasons, res=None):
        return {"invoice_no": inv.invoice_no, "vendor": inv.vendor,
                "total": None if inv.total is None else str(inv.total),
                "status": status, "po_id": res.po_id if res else None,
                "tier": res.tier if res else None, "reasons": list(reasons),
                "candidates": list(res.candidates) if res else []}

    def _review(self, inv, reasons, out, text="", res=None, status=None):
        digest = hashlib.sha256(str(text).encode("utf-8", "backslashreplace")).hexdigest()
        key = (norm_vendor(inv.vendor), inv.invoice_no or "UNPARSED-" + digest)
        for r in reasons:
            self.queue.add(key, r, inv.total or 0, inv.date)
        out["needs_review"].append(self._entry(inv, status or (res.status if res else "INVALID"), reasons, res))

    def _finish_match(self, inv, out, text):
        res = match(inv, self.pos, self.cfg)
        if res.status == "MATCH":
            prior = self.consumed.get(res.po_id)
            if prior:
                reasons = ["po_already_matched"]
                po = next(p for p in self.pos if p.get("po_id") == res.po_id)
                billed = sum((t for _v, _n, t in prior), Decimal(0)) + inv.total
                if not within_tolerance(billed, _po_total(po), self.cfg):
                    reasons.append("po_overbilled")
                res.status = "AMBIGUOUS"
                res.reasons = reasons
                res.candidates = [res.po_id]
                self._review(inv, reasons, out, text, res)
                return
            self.consumed.setdefault(res.po_id, []).append((norm_vendor(inv.vendor), inv.invoice_no, inv.total))
            out["auto_matched"].append(self._entry(inv, "MATCH", [], res))
        else:
            self._review(inv, res.reasons, out, text, res)

    def _one(self, text, out):
        inv = extract(text)
        reasons = check_invoice(inv)
        if "malformed" in reasons:
            self._review(inv, reasons, out, text if isinstance(text, str) else repr(text))
            return
        dup = self.dups.check(inv)
        if dup == "resubmission":
            out["skipped"].append(self._entry(inv, "SKIPPED", ["resubmission"]))
            return
        if dup == "id_conflict":
            self._review(inv, ["duplicate_id_conflict"], out, text)
            return
        if dup == "possible_duplicate":
            reasons.append("possible_duplicate")
        self.dups.register(inv)
        if reasons:
            self._review(inv, reasons, out, text)
            return
        if inv.part:
            self._part(inv, out, text)
        else:
            self._finish_match(inv, out, text)

    def _part(self, inv, out, text):
        if not inv.po_ref:
            self._review(inv, ["parts_without_po_ref"], out, text)
            return
        status, parts = self.parts.add(inv)
        if status == "conflict":
            self._review(inv, ["part_conflict"], out, text)
        elif status == "incomplete":
            self._review(inv, ["parts_incomplete"], out, text, status="PARTIAL")
        else:
            first = parts[1]  # consistency of vendor, PO, currency, date and part count was verified by PartTracker
            agg = Invoice(invoice_no=first.invoice_no, po_ref=first.po_ref, vendor=first.vendor, date=first.date,
                          currency=first.currency, conf=dict(first.conf))
            agg.total = sum((p.total for p in parts.values()), Decimal(0))
            key = (norm_vendor(inv.vendor), inv.invoice_no)
            self.queue.resolve(key, "parts_incomplete")
            self._finish_match(agg, out, text)
