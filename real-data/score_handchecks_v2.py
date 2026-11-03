"""PROTOCOL-v2.md hand-check tallies. Run: python3 -I score_handchecks_v2.py <scratch_dir>
The labels below are my (the author's) judgement after reading each sample row in the unmasked scratch sheets. They are NOT independent.
Criteria I applied (written here so the reader can see them; they are mine, chosen after reading):
  LEGIT       a visible reason for the repeat: the amount is a rate paid to many suppliers (about 10 or more others), or the key repeats
              on many dates, or the two vouchers carry different purposes.
  SUSPICIOUS  nothing visible explains it: an amount paid only to this supplier (0 or 1 others), at most 2 earlier same-day vouchers,
              no regular series, often consecutive voucher numbers.
  UNSURE      anything else (for example an amount unique to the supplier but repeated many times the same day)."""
import json
import os
import re
import sys

D = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
COMPANY = re.compile(r"\b(LTD|LIMITED|PLC|LLP|LLC|INC|CO|COMPANY|COUNCIL|TRUST|SERVICES|GROUP|CIC)\b", re.I)


def show(n):
    return n if COMPANY.search(n) else f"{n[:1]}***({len(n)})"


L, S, U = "LEGIT", "SUSPICIOUS", "UNSURE"
v2_labels = {0: L, 1: L, 2: L, 3: L, 4: L, 5: U, 6: L, 7: L, 8: L, 9: U, 10: S, 11: S, 12: U, 13: L, 14: S, 15: L, 16: L, 17: L, 18: S, 19: U,
             20: L, 21: U, 22: L, 23: U, 24: L, 25: L, 26: L, 27: L, 28: L, 29: S}
dropped_labels = {i: L for i in range(30)}
dropped_labels[17] = U
dropped_labels[28] = U
out = {}
for title, fname, labels in (("30 v2 flags (April to June)", "sample_v2_flags.json", v2_labels),
                             ("30 v1 flags that v2 no longer flags (April to June)", "sample_v1_only_flags.json", dropped_labels)):
    rows = json.load(open(os.path.join(D, fname)))
    assert len(rows) == len(labels) == 30
    print(f"\n== {title} ==")
    tally = {}
    masked = []
    for r in rows:
        lab = labels[r["i"]]
        tally[lab] = tally.get(lab, 0) + 1
        m = {"i": r["i"], "supplier": show(r["supplier"]), "total": r["total"], "date": r["date"], "purpose": r["purposes"][0] if r["purposes"] else "",
             "why": r["why"], "other_suppliers_paid_this_total": r["other_suppliers_paid_this_total"], "key_earlier_events": r["key_earlier_events"],
             "key_distinct_dates": r["key_distinct_dates"], "label": lab}
        masked.append(m)
        print(m["i"], lab, m["supplier"], m["total"], m["date"], m["purpose"][:30], m["why"], "others", m["other_suppliers_paid_this_total"],
              "events", m["key_earlier_events"], "dates", m["key_distinct_dates"])
    print("tally:", tally)
    out[title] = masked
json.dump(out, open(os.path.join(HERE, "samples", "handcheck_v2_labels_masked.json"), "w"), indent=1)
