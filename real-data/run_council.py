"""Part B of PROTOCOL.md: vendor merging and duplicate flags on real Rochdale payment lines.
Run with: python3 -I run_council.py <data_dir> <scratch_out_dir>
Evidence goes to stdout (company names only; anything else masked). The scratch dir gets the UNMASKED sample sheets
I read to label the hand-check samples; they are never committed."""
import collections
import csv
import datetime
import difflib
import glob
import json
import os
import random
import re
import sys
from decimal import Decimal, InvalidOperation

LAB = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(LAB, "src"))
from docmatch.extract import Invoice  # noqa: E402
from docmatch.util import legal_suffix, norm_vendor, vendor_identity  # noqa: E402
from docmatch.validate import DuplicateDetector  # noqa: E402

DATA, SCRATCH = sys.argv[1], sys.argv[2]
os.makedirs(SCRATCH, exist_ok=True)
SEED = 20261103
COMPANY = re.compile(r"\b(LTD|LIMITED|PLC|LLP|LLC|INC|CO|COMPANY|COUNCIL|TRUST|SERVICES|GROUP|CIC)\b", re.I)


def show(name):
    return name if COMPANY.search(name) else f"{name[:1]}***({len(name)})"


order = ["2025_JAN_Spend", "2025_FEB_Spend", "2025_MAR_Spend", "2025_APR_Spend", "2025_MAY_Spend", "2025_JUNE_SPEND"]
rows = []
stats = collections.Counter()
for stem in order:
    with open(os.path.join(DATA, "rochdale", stem + ".csv"), encoding="cp1252", newline="") as fh:
        rd = csv.reader(fh)
        next(rd)
        for r in rd:
            stats["lines_total"] += 1
            sup = r[3].strip()
            if not sup:
                stats["no_supplier"] += 1
                continue
            if sup.upper().startswith("REDACTED"):
                stats["redacted_personal"] += 1
                continue
            try:
                amt = Decimal(r[5].strip().replace(",", ""))
                dt = datetime.datetime.strptime(r[4].strip(), "%d-%b-%y").date().isoformat()
            except (InvalidOperation, ValueError):
                stats["unparseable_amount_or_date"] += 1
                continue
            stats["kept"] += 1
            rows.append({"file": stem, "sup": sup, "amt": amt, "date": dt, "dir": r[2].strip(), "purpose": r[6].strip(), "tx": r[7].strip()})
print("lines:", dict(stats))
pos = [r for r in rows if r["amt"] > 0]
print("kept rows with amount > 0:", len(pos), " amount <= 0:", len(rows) - len(pos))

# ---- B1 vendor merging
raw = sorted({r["sup"] for r in rows})
by_id = collections.defaultdict(list)
for s in raw:
    by_id[vendor_identity(s)].append(s)
empty_id = by_id.pop("", [])
groups = sorted((k, v) for k, v in by_id.items() if len(v) > 1)
print("\n== B1 vendor merging ==")
print("distinct raw supplier strings:", len(raw))
print("distinct non-empty identities:", len(by_id), "  raw strings with empty identity:", len(empty_id))
print("merge groups (identity with 2+ raw strings):", len(groups), "  raw strings inside merge groups:", sum(len(v) for _k, v in groups))
print("raw strings removed by merging (raw - identities):", len(raw) - len(empty_id) - len(by_id))
sizes = collections.Counter(len(v) for _k, v in groups)
print("group sizes:", sorted(sizes.items()))
rnd = random.Random(SEED)
samp_groups = rnd.sample(groups, min(50, len(groups)))
with open(os.path.join(SCRATCH, "sample_merge_groups.json"), "w") as fh:
    json.dump([{"i": i, "identity": k, "variants": v} for i, (k, v) in enumerate(samp_groups)], fh, indent=1)

# missed merges: different identity, same first char of normalised name, difflib ratio >= 0.85
idents = sorted(by_id)
rep = {k: by_id[k][0] for k in idents}
nv = {k: k.split("|")[0] for k in idents}
blocks = collections.defaultdict(list)
for k in idents:
    blocks[nv[k][:1]].append(k)
pairs = []
for _c, ks in blocks.items():
    for a in range(len(ks)):
        sa = difflib.SequenceMatcher(None)
        sa.set_seq2(nv[ks[a]])
        for b in range(a + 1, len(ks)):
            sa.set_seq1(nv[ks[b]])
            if sa.real_quick_ratio() >= 0.85 and sa.quick_ratio() >= 0.85 and sa.ratio() >= 0.85:
                pairs.append((ks[a], ks[b]))
pairs.sort()
same_n = sum(1 for a, b in pairs if nv[a] == nv[b])
print("\nfuzzy near-miss pairs (different identity, ratio >= 0.85, same first letter):", len(pairs), " of which same stripped name but different legal suffix:", same_n)
samp_pairs = random.Random(SEED).sample(pairs, min(30, len(pairs)))
with open(os.path.join(SCRATCH, "sample_missed_pairs.json"), "w") as fh:
    json.dump([{"i": i, "a": rep[a], "b": rep[b]} for i, (a, b) in enumerate(samp_pairs)], fh, indent=1)

# detector key vs identity: raw strings that share norm_vendor but differ in legal_suffix
byn = collections.defaultdict(set)
for s in raw:
    n = norm_vendor(s)
    if n:
        byn[n].add(s)
coll = sorted((n, v) for n, v in byn.items() if len({legal_suffix(s) for s in v}) > 1)
print("\nnorm_vendor keys (used by DuplicateDetector) that join raw strings with DIFFERENT legal suffixes:", len(coll))
for n, v in coll[:10]:
    print("   ", [show(s) for s in sorted(v)])

# ---- B2 duplicates
print("\n== B2 duplicate and near-duplicate flags ==")
det = DuplicateDetector()
outcome = collections.Counter()
flagged = []
seen_row = {}
content_row = {}
for r in pos:
    inv = Invoice(invoice_no=r["tx"], vendor=r["sup"], date=r["date"], currency="GBP", total=r["amt"])
    res = det.check(inv)
    outcome[res or "none"] += 1
    if res == "possible_duplicate":
        other = content_row.get((norm_vendor(r["sup"]), r["amt"], r["date"]))
        flagged.append((r, other))
    det.register(inv)
    content_row.setdefault((norm_vendor(r["sup"]), r["amt"], r["date"]), r)
print("rows fed:", len(pos), " outcomes:", dict(outcome))
rawdiff = sum(1 for r, o in flagged if o and o["sup"] != r["sup"])
print("flagged rows whose earlier row has a DIFFERENT raw supplier string (flag depends on normalisation):", rawdiff)
fl_sup = collections.Counter(r["sup"] for r, _o in flagged)
print("distinct suppliers among flagged rows:", len(fl_sup), "  flagged rows from the 10 busiest suppliers:", sum(c for _s, c in fl_sup.most_common(10)))
print("10 busiest flagged suppliers (counts):", [(show(s), c) for s, c in fl_sup.most_common(10)])
by_month = collections.Counter(r["file"] for r, _o in flagged)
print("flags by month:", dict(by_month))
tx_count = collections.Counter(r["tx"] for r in pos)
print("transaction numbers appearing more than once:", sum(1 for _t, c in tx_count.items() if c > 1))
# amounts of flagged: value share
tot_fl = sum(r["amt"] for r, _o in flagged)
print("sum of flagged amounts (GBP):", tot_fl)
# not flagged by design: same normalised vendor + amount on different dates within 7 days
grp = collections.defaultdict(list)
for r in pos:
    grp[(norm_vendor(r["sup"]), r["amt"])].append(datetime.date.fromisoformat(r["date"]))
near = 0
for _k, ds in grp.items():
    ds = sorted(set(ds))
    if any((b - a).days <= 7 for a, b in zip(ds, ds[1:])):
        near += 1
print("\n(count only, not scored) vendor+amount keys with the same amount on different dates within 7 days (not flagged by this detector):", near)

# ---- B2 voucher level (Deviation 2): one document per (TRANSACTION No., supplier)
print("\n== B2 voucher level (Deviation 2): one document per payment voucher ==")
vouch = collections.OrderedDict()
for r in rows:  # all kept rows, negatives included, in file order
    k = (r["tx"], r["sup"])
    v = vouch.setdefault(k, {"tx": r["tx"], "sup": r["sup"], "date": r["date"], "total": Decimal(0), "lines": 0, "dates": set(), "purposes": set(), "dirs": set(), "file": r["file"]})
    v["total"] += r["amt"]
    v["lines"] += 1
    v["dates"].add(r["date"])
    v["purposes"].add(r["purpose"])
    v["dirs"].add(r["dir"])
vl = [v for v in vouch.values() if v["total"] > 0]
print("vouchers (tx+supplier):", len(vouch), " with total > 0 (fed):", len(vl), " vouchers spanning more than one DATE PAID:", sum(1 for v in vouch.values() if len(v["dates"]) > 1))
print("vouchers by line count: 1 line:", sum(1 for v in vl if v["lines"] == 1), " 2+ lines:", sum(1 for v in vl if v["lines"] > 1))
det2 = DuplicateDetector()
out2 = collections.Counter()
flag2 = []
content_v = {}
for v in vl:
    inv = Invoice(invoice_no=v["tx"], vendor=v["sup"], date=v["date"], currency="GBP", total=v["total"])
    res = det2.check(inv)
    out2[res or "none"] += 1
    if res == "possible_duplicate":
        flag2.append((v, content_v.get((norm_vendor(v["sup"]), v["total"], v["date"]))))
    det2.register(inv)
    content_v.setdefault((norm_vendor(v["sup"]), v["total"], v["date"]), v)
print("vouchers fed:", len(vl), " outcomes:", dict(out2))
print("flagged vouchers whose earlier voucher has a DIFFERENT raw supplier string:", sum(1 for v, o in flag2 if o and o["sup"] != v["sup"]))
fs = collections.Counter(v["sup"] for v, _o in flag2)
print("distinct suppliers among flagged vouchers:", len(fs), " share of flags from the 10 busiest:", sum(c for _s, c in fs.most_common(10)))
print("10 busiest flagged suppliers:", [(show(s), c) for s, c in fs.most_common(10)])
print("flags by month:", dict(collections.Counter(v["file"] for v, _o in flag2)))
print("sum of flagged voucher totals (GBP):", sum(v["total"] for v, _o in flag2))
print("flagged vouchers that are single-line:", sum(1 for v, _o in flag2 if v["lines"] == 1), " multi-line:", sum(1 for v, _o in flag2 if v["lines"] > 1))
sup_by_total = collections.defaultdict(set)
for v in vl:
    sup_by_total[v["total"]].add(v["sup"])
samp2 = random.Random(SEED).sample(flag2, min(30, len(flag2)))
out = []
for i, (v, o) in enumerate(samp2):
    out.append({"i": i, "supplier": v["sup"], "total": str(v["total"]), "date": v["date"], "suppliers_with_same_total": len(sup_by_total[v["total"]]),
                "tx_gap": abs(int(v["tx"][1:]) - int(o["tx"][1:])),
                "this": {"tx": v["tx"], "lines": v["lines"], "purposes": sorted(v["purposes"])[:4], "dirs": sorted(v["dirs"])[:3]},
                "earlier": {"tx": o["tx"], "lines": o["lines"], "purposes": sorted(o["purposes"])[:4], "dirs": sorted(o["dirs"])[:3]}})
with open(os.path.join(SCRATCH, "sample_voucher_dup_flags.json"), "w") as fh:
    json.dump(out, fh, indent=1)
vkeys = collections.defaultdict(list)
for v in vl:
    vkeys[(norm_vendor(v["sup"]), v["total"])].append(datetime.date.fromisoformat(v["date"]))
n7 = sum(1 for ds in vkeys.values() if any((b - a).days <= 7 for a, b in zip(sorted(set(ds)), sorted(set(ds))[1:])))
print("(count only, not scored) voucher vendor+total keys with the same total on different dates within 7 days (not flagged):", n7)
