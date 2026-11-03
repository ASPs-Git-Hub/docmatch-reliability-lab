"""PROTOCOL-v2.md Part A: total extraction on CORD-v2 receipts, v1 code (real-data/v1) or v2 code (src).
Run: python3 -I run_cord_v2.py <data_dir> --impl v1|v2 --set dev|frozen
Ground-truth rule is the corrected one from PROTOCOL.md Deviation 1 (a trailing two-digit cents group is stripped, then digits kept).
Variants: R = text as built; C = a line 'total x' rewritten to 'Total: x'; C-IDR (v2 only) = C plus assume_currency='IDR' (a deployment-level
declaration, NOT per-document evidence)."""
import collections
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.abspath(os.path.join(HERE, ".."))
DATA = sys.argv[1]
IMPL = sys.argv[sys.argv.index("--impl") + 1]
SET = sys.argv[sys.argv.index("--set") + 1]
sys.path.insert(0, os.path.join(HERE, "v1") if IMPL == "v1" else os.path.join(LAB, "src"))
from docmatch.extract import extract  # noqa: E402
from docmatch.util import wilson  # noqa: E402
from docmatch.validate import check_invoice  # noqa: E402

print(f"impl={IMPL} set={SET}")


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
        out.append("Total: " + parts[1] if len(parts) == 2 and parts[0].lower() == "total" else ln)
    return "\n".join(out)


docs = []
if SET == "frozen":
    files = [(os.path.basename(f).split("_")[0], f) for f in sorted(glob.glob(os.path.join(DATA, "cord", "*_*.json"))) if "api_card" not in f]
else:
    files = [("train", os.path.join(DATA, "cord_dev", "train_first_rows.json"))]
for split, f in files:
    d = json.load(open(f))
    for r in d.get("rows", []):
        docs.append((split, r["row_idx"], json.loads(r["row"]["ground_truth"])))
scored, skipped = [], 0
for split, idx, g in docs:
    tp = g["gt_parse"].get("total", {})
    tp = tp.get("total_price") if isinstance(tp, dict) else None
    if isinstance(tp, list):
        tp = None
    if not re.sub(r"\D", "", tp or ""):
        skipped += 1
        continue
    st = g["gt_parse"].get("sub_total", {})
    st = st.get("subtotal_price") if isinstance(st, dict) else None
    if isinstance(st, list):
        st = st[0] if st else None
    sub_val = int(re.sub(r"\D", "", re.sub(r"[.,]\d{2}$", "", st))) if isinstance(st, str) and re.sub(r"\D", "", st) else None
    scored.append((split, idx, int(re.sub(r"\D", "", re.sub(r"[.,]\d{2}$", "", tp))), tp, build_text(g["valid_line"]), sub_val))
n = len(scored)
print(f"receipts loaded: {len(docs)}  scoreable: {n}  left out (no total_price digits): {skipped}")


def run(label, tf, kw):
    cnt = collections.Counter()
    reasons = collections.Counter()
    evid = collections.Counter()
    wrong, correct_forms = [], collections.Counter()
    vend = date = clean = 0
    for split, idx, val, raw, text, sub_val in scored:
        inv = extract(tf(text), **kw)
        rs = check_invoice(inv)
        clean += not rs
        reasons.update(rs)
        vend += bool(inv.vendor)
        date += bool(inv.date)
        evid.update(getattr(inv, "format_evidence", []))
        if inv.total is None:
            cnt["REFUSED"] += 1
        elif inv.total == val:
            cnt["CORRECT"] += 1
            correct_forms["dotted-or-comma-grouped" if re.search(r"\d[.,]\d{3}\b", raw or "") else "other"] += 1
        else:
            cnt["WRONG"] += 1
            wrong.append((split, idx, str(inv.total), raw, inv.conf.get("total"), "equals the receipt's labelled SUBTOTAL (a pre-tax 'TOTAL' line)" if sub_val is not None and inv.total == sub_val else "other cause"))
    print(f"\n== variant {label} ==")
    for k in ("CORRECT", "WRONG", "REFUSED"):
        lo, hi = wilson(cnt[k], n)
        print(f"total {k}: {cnt[k]}/{n}  Wilson95 [{lo*100:.1f}%, {hi*100:.1f}%]")
    print("vendor non-empty:", vend, " date non-empty:", date, " check_invoice clean:", clean)
    print("top reasons:", reasons.most_common(8))
    if evid:
        print("evidence used:", dict(evid))
    if cnt["CORRECT"]:
        print("correct totals by written form:", dict(correct_forms))
    for e in wrong[:20]:
        print("  WRONG:", e)


run("R (text as built)", lambda t: t, {})
run("C (colon added to 'total x')", variant_c, {})
if IMPL == "v2":
    run("C-IDR (colon added + caller declares assume_currency='IDR'; deployment-level declaration)", variant_c, {"assume_currency": "IDR"})
    run("R-IDR (text as built + assume_currency='IDR')", lambda t: t, {"assume_currency": "IDR"})
dotted = sum(1 for _s, _i, _v, raw, _t, _sv in scored if re.search(r"\d[.,]\d{3}\b", raw or ""))
print(f"\nground-truth totals written with a 3-digit group separator: {dotted}/{n}")
