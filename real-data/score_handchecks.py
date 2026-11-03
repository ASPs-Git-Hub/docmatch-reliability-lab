"""Tallies the hand-check labels of PROTOCOL.md Part B. Run: python3 -I score_handchecks.py <scratch_sample_dir>
Merge and near-miss labels are my manual judgements (typed below). Duplicate-flag labels follow a rule I wrote after
looking at the sample (stated in README.md): it is mine, not independent, and not a proof of anything."""
import json
import os
import re
import sys

D = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
COMPANY = re.compile(r"\b(LTD|LIMITED|PLC|LLP|LLC|INC|CO|COMPANY|COUNCIL|TRUST|SERVICES|GROUP|CIC)\b", re.I)


def show(n):
    return n if COMPANY.search(n) else f"{n[:1]}***({len(n)})"


merge = json.load(open(D + "/sample_merge_groups.json"))
merge_labels = {0: "CORRECT", 1: "CORRECT", 2: "CORRECT", 3: "CORRECT", 4: "CORRECT"}
print("== merge groups hand-checked (all", len(merge), "groups; fewer than 50 exist) ==")
for g in merge:
    print(g["i"], merge_labels[g["i"]], [show(v) for v in g["variants"]])
cnt = {}
for v in merge_labels.values():
    cnt[v] = cnt.get(v, 0) + 1
print("tally:", cnt)

pairs = json.load(open(D + "/sample_missed_pairs.json"))
pair_labels = {0: "SAME", 1: "UNSURE", 2: "DIFFERENT", 3: "DIFFERENT", 4: "SAME", 5: "DIFFERENT", 6: "SAME", 7: "DIFFERENT",
               8: "SAME", 9: "DIFFERENT", 10: "DIFFERENT", 11: "DIFFERENT", 12: "DIFFERENT", 13: "DIFFERENT", 14: "DIFFERENT", 15: "UNSURE"}
print("\n== near-miss pairs hand-checked (all", len(pairs), "pairs; fewer than 30 exist) ==")
for g in pairs:
    print(g["i"], pair_labels[g["i"]], "|", show(g["a"]), "|", show(g["b"]))
cnt = {}
for v in pair_labels.values():
    cnt[v] = cnt.get(v, 0) + 1
print("tally:", cnt)

flags = json.load(open(D + "/sample_voucher_dup_flags.json"))


def label(f):
    shared, gap = f["suppliers_with_same_total"], f["tx_gap"]
    if shared >= 5 and gap > 1:
        return "LEGIT"
    if shared == 1 and gap <= 3:
        return "SUSPICIOUS"
    return "UNSURE"


print("\n== voucher-level duplicate flags hand-checked (30) ==")
print("rule: LEGIT if the total is shared by >=5 distinct suppliers and voucher numbers are not adjacent (gap > 1);")
print("      SUSPICIOUS if the total is unique to this supplier and the voucher numbers are within 3 of each other; else UNSURE.")
tally = {}
rowsout = []
for f in flags:
    lab = label(f)
    tally[lab] = tally.get(lab, 0) + 1
    rowsout.append({"i": f["i"], "supplier": show(f["supplier"]), "total": f["total"], "date": f["date"], "purpose": f["this"]["purposes"][0],
                    "suppliers_with_same_total": f["suppliers_with_same_total"], "tx_gap": f["tx_gap"], "label": lab})
    print(f["i"], lab, show(f["supplier"]), f["total"], f["date"], f["this"]["purposes"][0][:28], "shared", f["suppliers_with_same_total"], "gap", f["tx_gap"])
print("tally:", tally)
json.dump({"dup_flags": rowsout, "pairs": [{"i": g["i"], "a": show(g["a"]), "b": show(g["b"]), "label": pair_labels[g["i"]]} for g in pairs],
           "merge": [{"i": g["i"], "variants": [show(v) for v in g["variants"]], "label": merge_labels[g["i"]]} for g in merge]},
          open(os.path.join(HERE, "samples", "handcheck_labels_masked.json"), "w"), indent=1)
