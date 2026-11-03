"""PROTOCOL-v2.md Part B: duplicate flags on Rochdale vouchers, v1 detector (real-data/v1) or v2 detector (src).
Run: python3 -I run_council_v2.py <data_dir> <scratch_dir> --impl v1|v2 --mode tune|frozen [--w N] [--no-cadence] [--no-context]
tune   = development months (Jan to Mar) only: flagged share and planted-duplicate recall for a grid of settings.
frozen = scoring months (Apr to Jun), warm start (Jan to Mar fed as history) and cold start (Apr to Jun only).
Evidence goes to stdout: supplier names only when they contain a company word, otherwise masked. UNMASKED sample sheets go to
<scratch_dir> only and are never committed."""
import collections
import csv
import datetime
import json
import os
import random
import re
import sys
from decimal import Decimal, InvalidOperation

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.abspath(os.path.join(HERE, ".."))
DATA, SCRATCH = sys.argv[1], sys.argv[2]
IMPL = sys.argv[sys.argv.index("--impl") + 1]
MODE = sys.argv[sys.argv.index("--mode") + 1]
sys.path.insert(0, os.path.join(HERE, "v1") if IMPL == "v1" else os.path.join(LAB, "src"))
from docmatch.extract import Invoice  # noqa: E402
from docmatch.util import vendor_identity  # noqa: E402
from docmatch.validate import DuplicateDetector  # noqa: E402

os.makedirs(SCRATCH, exist_ok=True)
COMPANY = re.compile(r"\b(LTD|LIMITED|PLC|LLP|LLC|INC|CO|COMPANY|COUNCIL|TRUST|SERVICES|GROUP|CIC)\b", re.I)
ORDER = ["2025_JAN_Spend", "2025_FEB_Spend", "2025_MAR_Spend", "2025_APR_Spend", "2025_MAY_Spend", "2025_JUNE_SPEND"]
DEV, SCORE = ORDER[:3], ORDER[3:]


def show(name):
    return name if COMPANY.search(name) else f"{name[:1]}***({len(name)})"


def argval(flag, default):
    return type(default)(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default


# ---- load vouchers exactly as run_council.py did (Deviation 2 of PROTOCOL.md)
vouch = collections.OrderedDict()
for stem in ORDER:
    with open(os.path.join(DATA, "rochdale", stem + ".csv"), encoding="cp1252", newline="") as fh:
        rd = csv.reader(fh)
        next(rd)
        for r in rd:
            sup = r[3].strip()
            if not sup or sup.upper().startswith("REDACTED"):
                continue
            try:
                amt = Decimal(r[5].strip().replace(",", ""))
                dt = datetime.datetime.strptime(r[4].strip(), "%d-%b-%y").date().isoformat()
            except (InvalidOperation, ValueError):
                continue
            k = (r[7].strip(), sup)
            v = vouch.setdefault(k, {"tx": k[0], "sup": sup, "date": dt, "total": Decimal(0), "lines": 0, "purposes": set(), "dirs": set(), "file": stem})
            v["total"] += amt
            v["lines"] += 1
            v["purposes"].add(r[6].strip())
            v["dirs"].add(r[2].strip())
FED = [v for v in vouch.values() if v["total"] > 0]
print(f"impl={IMPL} mode={MODE}  vouchers (tx+supplier): {len(vouch)}  fed (total > 0): {len(FED)}")
print("fed by month:", {m: sum(1 for v in FED if v["file"] == m) for m in ORDER})


def mk(v, tx=None, date=None):
    kw = {"invoice_no": tx or v["tx"], "vendor": v["sup"], "date": date or v["date"], "currency": "GBP", "total": v["total"]}
    if IMPL == "v2":
        kw["context"] = tuple(sorted(v["purposes"]))
    return Invoice(**kw)


def new_detector(w=3, cadence=True, context=True):
    return DuplicateDetector(window_days=w, use_cadence=cadence, use_context=context) if IMPL == "v2" else DuplicateDetector()


def run_stream(stream, **cfg):
    """stream: list of (voucher, tx, date) -> list of (verdict, why). check() then register(), as pipeline._one does."""
    det = new_detector(**cfg)
    out = []
    for v, tx, date in stream:
        inv = mk(v, tx, date)
        if IMPL == "v2":
            res, why = det.check_detail(inv)
        else:
            res, why = det.check(inv), "v1"
        out.append((res, why))
        det.register(inv)
    return out, det


def plain(vs):
    return [(v, None, None) for v in vs]


def planted(vs, shift, n=300):
    """Insert a copy (new voucher number, same supplier/amount/context) `shift` days later after each of n random vouchers."""
    picks = set(random.Random(20261103).sample(range(len(vs)), min(n, len(vs))))
    stream, copies = [], []
    for i, v in enumerate(vs):
        stream.append((v, None, None))
        if i in picks:
            d = (datetime.date.fromisoformat(v["date"]) + datetime.timedelta(days=shift)).isoformat()
            copies.append(len(stream))
            stream.append((v, f"DUP{i}", d))
    return stream, copies


def recurring_keys(vs):
    dates = collections.defaultdict(set)
    for v in vs:
        dates[(vendor_identity(v["sup"]), v["total"])].add(v["date"])
    return {k for k, d in dates.items() if len(d) >= 3}


def pct(a, b):
    return f"{100*a/b:.1f}%" if b else "n/a"


if MODE == "tune":
    vs = [v for v in FED if v["file"] in DEV]
    rec = recurring_keys(vs)
    print(f"development vouchers: {len(vs)}; vouchers on a recurring key (>= 3 distinct dates for supplier+amount): {sum(1 for v in vs if (vendor_identity(v['sup']), v['total']) in rec)}")
    grid = [dict()] if IMPL == "v1" else [dict(w=w, cadence=c, context=x) for w in (0, 1, 3) for c in (True, False) for x in (True, False)]
    for cfg in grid:
        res, _d = run_stream(plain(vs), **cfg)
        fl = sum(1 for r, _w in res if r == "possible_duplicate")
        row = [f"cfg={cfg or 'v1'}", f"flagged {fl}/{len(vs)} = {pct(fl, len(vs))}"]
        for shift in (0, 1, 3, 10):
            stream, copies = planted(vs, shift)
            out, _d = run_stream(stream, **cfg)
            hit_all = sum(1 for i in copies if out[i][0] == "possible_duplicate")
            keys = [(vendor_identity(stream[i][0]["sup"]), stream[i][0]["total"]) for i in copies]
            nonrec = [j for j, k in enumerate(keys) if k not in rec]
            hit_non = sum(1 for j in nonrec if out[copies[j]][0] == "possible_duplicate")
            recj = [j for j, k in enumerate(keys) if k in rec]
            hit_rec = sum(1 for j in recj if out[copies[j]][0] == "possible_duplicate")
            row.append(f"shift{shift}: all {hit_all}/{len(copies)} nonrec {hit_non}/{len(nonrec)} rec {hit_rec}/{len(recj)}")
        print(" | ".join(row))
    sys.exit(0)

# ---------------- frozen
def summarize(label, stream_vs, count_months):
    res, det = run_stream(plain(stream_vs), **CFG)
    flagged = [(v, r) for v, r in zip(stream_vs, res) if r[0] == "possible_duplicate" and v["file"] in count_months]
    fed_n = sum(1 for v in stream_vs if v["file"] in count_months)
    print(f"\n== {label} ==")
    print(f"vouchers fed in scoring months: {fed_n}  flagged possible_duplicate: {len(flagged)}  share {pct(len(flagged), fed_n)}")
    print("flags by month:", dict(collections.Counter(v["file"] for v, _r in flagged)))
    if IMPL == "v2":
        print("verdict reasons over scoring months:", dict(collections.Counter(r[1] for v, r in zip(stream_vs, res) if v["file"] in count_months)))
    fs = collections.Counter(v["sup"] for v, _r in flagged)
    print(f"distinct suppliers among flags: {len(fs)}  flags from the 10 busiest: {sum(c for _s, c in fs.most_common(10))}")
    print("10 busiest flagged suppliers:", [(show(s), c) for s, c in fs.most_common(10)])
    print("sum of flagged voucher totals (GBP):", sum(v["total"] for v, _r in flagged))
    return flagged, res


CFG = dict(w=argval("--w", 3), cadence="--no-cadence" not in sys.argv, context="--no-context" not in sys.argv) if IMPL == "v2" else {}
print("config:", CFG or "v1 (as committed at bcf6ab2)")
stream_all = [v for v in FED]
flagged_warm, res_warm = summarize("WARM START: January to June fed in order, flags counted for April to June", stream_all, SCORE)
flagged_cold, _ = summarize("COLD START: April to June only", [v for v in FED if v["file"] in SCORE], SCORE)

# different-identity joins: flags whose earlier voucher is another supplier spelling with a different vendor_identity
if IMPL == "v1":
    from docmatch.util import norm_vendor  # noqa: E402
    cross = 0
    seen = {}
    flagged_ids = {(v["tx"], v["sup"]) for v, _r in flagged_warm}
    for v in FED:
        k = (norm_vendor(v["sup"]), v["total"], v["date"])
        if (v["tx"], v["sup"]) in flagged_ids and k in seen and vendor_identity(seen[k]["sup"]) != vendor_identity(v["sup"]):
            cross += 1
        seen.setdefault(k, v)
    print(f"\nflags (April to June) whose earlier voucher has a DIFFERENT vendor_identity (joined only by norm_vendor): {cross}")
    json.dump([[v["tx"], v["sup"]] for v, _r in flagged_warm], open(os.path.join(SCRATCH, "v1_flags_aprjun.json"), "w"))
else:
    # planted-duplicate recall on the frozen months (secondary; same method as tuning), then hand-check sheets
    vs = [v for v in FED if v["file"] in SCORE]
    rec = recurring_keys(vs)
    print("\nplanted duplicates on April to June (300 copies each, cold start; synthetic injection, not real duplicates):")
    for shift in (0, 1, 3, 10):
        stream, copies = planted(vs, shift)
        out, _d = run_stream(stream, **CFG)
        keys = [(vendor_identity(stream[i][0]["sup"]), stream[i][0]["total"]) for i in copies]
        nonrec = [j for j, k in enumerate(keys) if k not in rec]
        recj = [j for j, k in enumerate(keys) if k in rec]
        f = lambda js: sum(1 for j in js if out[copies[j]][0] == "possible_duplicate")  # noqa: E731
        print(f"  shift {shift}: all {sum(1 for i in copies if out[i][0] == 'possible_duplicate')}/{len(copies)}  non-recurring keys {f(nonrec)}/{len(nonrec)}  recurring keys {f(recj)}/{len(recj)}")
    sup_by_total = collections.defaultdict(set)
    for v in FED:
        sup_by_total[v["total"]].add(v["sup"])
    # sheet 1: 30 v2 flags
    rnd = random.Random(20262611)
    pick = rnd.sample(flagged_warm, min(30, len(flagged_warm)))
    # rebuild per-key history up to each flagged voucher
    order = {(v["tx"], v["sup"]): i for i, v in enumerate(FED)}
    bykey = collections.defaultdict(list)
    for v in FED:
        bykey[(vendor_identity(v["sup"]), v["total"])].append(v)

    def sheet(v, why):
        prior = [x for x in bykey[(vendor_identity(v["sup"]), v["total"])] if order[(x["tx"], x["sup"])] < order[(v["tx"], v["sup"])]]
        near = [x for x in prior if abs((datetime.date.fromisoformat(x["date"]) - datetime.date.fromisoformat(v["date"])).days) <= CFG["w"]]
        return {"supplier": v["sup"], "total": str(v["total"]), "date": v["date"], "tx": v["tx"], "lines": v["lines"], "purposes": sorted(v["purposes"])[:4],
                "why": why, "other_suppliers_paid_this_total": len(sup_by_total[v["total"]]) - 1, "key_earlier_events": len(prior),
                "key_distinct_dates": len({x["date"] for x in prior} | {v["date"]}),
                "near_peers": [{"tx": x["tx"], "date": x["date"], "lines": x["lines"], "purposes": sorted(x["purposes"])[:4]} for x in near[:3]]}
    json.dump([dict(i=i, **sheet(v, r[1])) for i, (v, r) in enumerate(pick)], open(os.path.join(SCRATCH, "sample_v2_flags.json"), "w"), indent=1)
    # sheet 2: 30 v1 flags that v2 does not flag
    v1f = {tuple(x) for x in json.load(open(os.path.join(SCRATCH, "v1_flags_aprjun.json")))}
    v2f = {(v["tx"], v["sup"]) for v, _r in flagged_warm}
    dropped = [v for v in FED if v["file"] in SCORE and (v["tx"], v["sup"]) in v1f and (v["tx"], v["sup"]) not in v2f]
    why_by = {(v["tx"], v["sup"]): r[1] for v, r in zip(FED, res_warm)}
    print(f"\nv1 flags in April to June: {len(v1f)}  of which v2 does not flag: {len(dropped)}  v2 flags that v1 did not flag: {len(v2f - v1f)}")
    print("why v2 dropped them:", dict(collections.Counter(why_by[(v['tx'], v['sup'])] for v in dropped)))
    pick2 = random.Random(20262611).sample(dropped, min(30, len(dropped)))
    json.dump([dict(i=i, **sheet(v, why_by[(v["tx"], v["sup"])])) for i, v in enumerate(pick2)], open(os.path.join(SCRATCH, "sample_v1_only_flags.json"), "w"), indent=1)
    print("sample sheets written to scratch (unmasked, not committed)")
