"""Part A of PROTOCOL.md: run docmatch.extract on real CORD-v2 receipt text. Run with: python3 -I run_cord.py <data_dir>"""
import collections
import glob
import json
import os
import re
import sys

LAB = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(LAB, "src"))
from docmatch.extract import extract  # noqa: E402
from docmatch.util import money, wilson  # noqa: E402
from docmatch.validate import check_invoice  # noqa: E402

DATA = sys.argv[1]
OUT_SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples", "cord_texts_frozen.jsonl")


def build_text(vl):
    rows = collections.defaultdict(list)
    for line in vl:
        for w in line["words"]:
            q = w["quad"]
            rows[w["row_id"]].append((q["x1"], q["y1"], w["text"]))
    ordered = sorted(rows.values(), key=lambda ws: min(y for _x, y, _t in ws))
    return "\n".join(" ".join(t for _x, _y, t in sorted(ws)) for ws in ordered)


def variant_c(text):
    out = []
    for ln in text.split("\n"):
        parts = ln.split()
        if len(parts) == 2 and parts[0].lower() == "total":
            out.append("Total: " + parts[1])
        else:
            out.append(ln)
    return "\n".join(out)


docs = []
for f in sorted(glob.glob(os.path.join(DATA, "cord", "*_*.json"))):
    d = json.load(open(f))
    if "rows" not in d:
        continue
    split = os.path.basename(f).split("_")[0]
    for r in d["rows"]:
        g = json.loads(r["row"]["ground_truth"])
        docs.append((split, r["row_idx"], g))
print("receipts loaded:", len(docs), collections.Counter(s for s, _i, _g in docs))

scored = []
fixed_by_key = {}
skipped = 0
for split, idx, g in docs:
    tp = g["gt_parse"].get("total", {})
    tp = tp.get("total_price") if isinstance(tp, dict) else None
    if isinstance(tp, list):
        tp = None
    digits = re.sub(r"\D", "", tp or "")
    if not digits:
        skipped += 1
        continue
    scored.append((split, idx, int(digits), tp, build_text(g["valid_line"])))
    fixed = int(re.sub(r"\D", "", re.sub(r"[.,]\d{2}$", "", tp)))  # deviation 1 in PROTOCOL.md: strip a trailing 2-digit cents group
    fixed_by_key[(split, idx)] = fixed
print("scoreable (has total_price with digits):", len(scored), " left out:", skipped)

os.makedirs(os.path.dirname(OUT_SAMPLE), exist_ok=True)
with open(OUT_SAMPLE, "w") as fh:
    for split, idx, val, raw, text in scored:
        fh.write(json.dumps({"split": split, "idx": idx, "gt_total_raw": raw, "gt_total_int": val, "text": text}, ensure_ascii=False) + "\n")


def run(label, tf, use_fixed=False):
    cnt = collections.Counter()
    reasons = collections.Counter()
    nonnull_vendor = nonnull_date = clean = 0
    wrong_examples = []
    vendor_vals, date_vals = [], []
    for split, idx, val, raw, text in scored:
        if use_fixed:
            val = fixed_by_key[(split, idx)]
        inv = extract(tf(text))
        rs = check_invoice(inv)
        if not rs:
            clean += 1
        for r in rs:
            reasons[r] += 1
        if inv.vendor:
            nonnull_vendor += 1
            vendor_vals.append((split, idx, inv.vendor))
        if inv.date:
            nonnull_date += 1
            date_vals.append((split, idx, inv.date))
        if inv.total is None:
            cnt["REFUSED"] += 1
        elif inv.total == val:
            cnt["CORRECT"] += 1
        else:
            cnt["WRONG"] += 1
            wrong_examples.append((split, idx, str(inv.total), raw, inv.conf.get("total")))
    n = len(scored)
    print(f"\n== variant {label} ==")
    for k in ("CORRECT", "WRONG", "REFUSED"):
        lo, hi = wilson(cnt[k], n)
        print(f"total {k}: {cnt[k]}/{n}  Wilson95 [{lo*100:.1f}%, {hi*100:.1f}%]")
    print("vendor non-empty:", nonnull_vendor, " date non-empty:", nonnull_date)
    print("check_invoice clean (no reasons):", clean)
    print("top reasons:", reasons.most_common(8))
    if wrong_examples:
        print("WRONG examples (split, idx, extracted, gt_raw, conf):")
        for e in wrong_examples[:20]:
            print("  ", e)
    for lab, vals in (("vendor", vendor_vals), ("date", date_vals)):
        for v in vals[:30]:
            print(f"  {lab} value: {v}")


for fx in (False, True):
    print("\n######## ground-truth rule:", "CORRECTED (deviation 1: trailing cents group stripped)" if fx else "AS WRITTEN IN PROTOCOL (digits only)")
    run("R (primary, text as built)", lambda t: t, fx)
    run("C (diagnostic, 'total x' rewritten to 'Total: x')", variant_c, fx)

# readable ceiling (uses the corrected ground truth, deviation 1): any token equal to the GT digits that the strict money() grammar accepts
ceil = 0
dotted = 0
for split, idx, val, raw, text in scored:
    ok = False
    for tok in re.split(r"\s+", text):
        m = money(tok)
        if m is not None and m == fixed_by_key[(split, idx)]:
            ok = True
            break
    ceil += ok
    if re.search(r"\d\.\d{3}\b|\d,\d{3}\b", raw or ""):
        dotted += 1
print(f"\nreadable ceiling: {ceil}/{len(scored)} receipts have a token equal to the true total that money() accepts")
print(f"ground-truth totals written with a 3-digit group separator ('.' or ','): {dotted}/{len(scored)}")
