"""Exception queue: one entry per (invoice, reason), idempotent, ordered by age and amount.

Priority score = 2 * age_days + min(amount, 100000) / 1000. The weights are a stated
judgement call, not a tuned or validated value.
"""
import datetime
from dataclasses import dataclass


@dataclass
class QueueEntry:
    invoice_key: tuple
    reason: str
    amount: float
    invoice_date: str
    detail: str = ""


class ExceptionQueue:
    def __init__(self):
        self._entries = {}

    def add(self, invoice_key, reason, amount=0.0, invoice_date=None, detail=""):
        """Return True if a new entry was created, False if it already existed."""
        k = (invoice_key, reason)
        if k in self._entries:
            return False
        self._entries[k] = QueueEntry(invoice_key, reason, float(abs(amount)), invoice_date, detail)
        return True

    def resolve(self, invoice_key, reason):
        return self._entries.pop((invoice_key, reason), None) is not None

    def __len__(self):
        return len(self._entries)

    @staticmethod
    def priority(entry, now):
        try:
            age = max(0, (now - datetime.date.fromisoformat(entry.invoice_date)).days)
        except (TypeError, ValueError):
            age = 0
        return 2 * age + min(entry.amount, 100000.0) / 1000.0

    def list_sorted(self, now):
        """Highest priority first; ties broken by key for a stable order."""
        return sorted(self._entries.values(), key=lambda e: (-self.priority(e, now), str(e.invoice_key), e.reason))
