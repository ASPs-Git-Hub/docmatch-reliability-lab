"""Evaluate DocMatch and NaiveDocMatch on sets A, B, C.

Set A: tuned while building (not clean). Set B: frozen before the first code commit; the code CHANGED after B
was measured, so B is a regression check, not a clean set. Set C: written in round 2 (single-invoice cases plus
labelled batch cases); first-run numbers are saved separately in evidence/.
Labels in every set come from the same author model, not from an independent human.

Metrics (each as k/n with Wilson 95% interval):
  false auto-match : predicted MATCH but expected is not MATCH, or MATCH to the wrong PO (over all cases)
  trap flagged     : traps that ended in needs_review (and, where the implementation has a queue, in the queue)
  correct auto     : normal cases auto-matched to the right PO
  dropped          : cases with no valid single terminal disposition (silently lost, or listed twice)
Batch cases (set C): per-invoice outcome compared with expected_list; plus POs auto-matched more than once.
Usage: python3 scripts/evaluate.py [A] [B] [C]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from docmatch import DocMatch, NaiveDocMatch  # noqa: E402
from docmatch.util import wilson  # noqa: E402


def dispositions(r):
    return len(r["auto_matched"]) + len(r["needs_review"]) + len(r["skipped"])


def run_case(impl_cls, case):
    impl = impl_cls(case["pos"])
    r = impl.process([case["invoice_text"]])
    if dispositions(r) != 1:
        return "DROPPED", None
    if r["auto_matched"]:
        return "MATCH", r["auto_matched"][0].get("po_id")
    if "queue" in r and not r["queue"]:
        return "DROPPED", None  # flagged without any queue entry: nothing for a human to work from
    if r["needs_review"]:
        return "FLAG", None
    return "DROPPED", None


def evaluate(impl_cls, cases):
    single = [c for c in cases if c["kind"] in ("trap", "normal")]
    n = len(single)
    false_auto = dropped = trap_flagged = correct_auto = 0
    traps = [c for c in single if c["kind"] == "trap"]
    normal = [c for c in single if c["kind"] == "normal"]
    bad = []
    for c in single:
        out, po = run_case(impl_cls, c)
        if out == "DROPPED":
            dropped += 1
            bad.append(("DROPPED", c["id"]))
        if out == "MATCH" and (c["expected"] != "MATCH" or po != c["expected_po"]):
            false_auto += 1
            bad.append(("FALSE_AUTO", c["id"]))
        if c["kind"] == "trap" and out == "FLAG":
            trap_flagged += 1
        if c["kind"] == "normal":
            if out == "MATCH" and po == c["expected_po"]:
                correct_auto += 1
            else:
                bad.append(("MISSED_AUTO", c["id"]))
    return {"n": n, "n_traps": len(traps), "n_normal": len(normal), "false_auto": false_auto, "dropped": dropped,
            "trap_flagged": trap_flagged, "correct_auto": correct_auto, "bad": bad}


def evaluate_batches(impl_cls, cases):
    """Per-invoice outcomes in submission order: MATCH:<po>, FLAG or SKIP."""
    total = false_auto = wrong = double_po = 0
    bad = []
    for c in (x for x in cases if x["kind"] == "batch"):
        impl = impl_cls(c["pos"])
        got = []
        po_hits = {}
        for text in c["invoices"]:  # one invoice per process() call keeps submission order observable
            r = impl.process([text])
            if r["auto_matched"] and dispositions(r) == 1:
                po = r["auto_matched"][0].get("po_id")
                got.append("MATCH:" + str(po))
                po_hits[po] = po_hits.get(po, 0) + 1
            elif r["skipped"] and dispositions(r) == 1:
                got.append("SKIP")
            elif r["needs_review"] and dispositions(r) == 1:
                got.append("FLAG")
            else:
                got.append("DROPPED")
        for g, e in zip(got, c["expected_list"]):
            total += 1
            if g != e:
                wrong += 1
                bad.append((c["id"], f"{g}!={e}"))
            if g.startswith("MATCH") and g != e:
                false_auto += 1
        double_po += sum(1 for v in po_hits.values() if v > 1)
    return {"invoices": total, "wrong": wrong, "false_auto": false_auto, "double_paid_pos": double_po, "bad": bad,
            "cases": sum(1 for x in cases if x["kind"] == "batch")}


def row(label, k, n):
    lo, hi = wilson(k, n)
    return f"  {label:<22} {k:>3}/{n:<3}  {100 * k / n if n else 0:5.1f}%  Wilson95 [{100 * lo:5.1f}%, {100 * hi:5.1f}%]"


SETS = (("A", "set_a.json", "TUNED (not clean)"),
        ("B", "set_b.json", "FROZEN, REGRESSION-CHECKED (code changed after B was measured; not clean)"),
        ("C", "set_c.json", "NEW in round 2 (same author model labelled it; not independent)"))


def main():
    for tag, fname, status in SETS:
        if len(sys.argv) > 1 and tag not in sys.argv[1:]:
            continue
        with open(os.path.join(ROOT, "data", fname)) as f:
            cases = json.load(f)["cases"]
        print(f"=== Set {tag}: {status}: {len(cases)} cases ===")
        for name, cls in (("DocMatch", DocMatch), ("NaiveDocMatch", NaiveDocMatch)):
            m = evaluate(cls, cases)
            print(f" {name}  (single-invoice cases: {m['n']})")
            print(row("false auto-match", m["false_auto"], m["n"]))
            print(row("trap flagged", m["trap_flagged"], m["n_traps"]))
            print(row("correct auto-match", m["correct_auto"], m["n_normal"]))
            print(f"  dropped (no valid single disposition): {m['dropped']}")
            if m["bad"]:
                print("  detail:", ", ".join(f"{k}:{i}" for k, i in m["bad"]))
            b = evaluate_batches(cls, cases)
            if b["cases"]:
                print(f"  batch cases: {b['cases']} ({b['invoices']} invoices)")
                print(row("batch false auto", b["false_auto"], b["invoices"]))
                print(row("batch wrong outcome", b["wrong"], b["invoices"]))
                print(f"  POs auto-matched more than once: {b['double_paid_pos']}")
                if b["bad"]:
                    print("  batch detail:", ", ".join(f"{i}:{d}" for i, d in b["bad"]))
        print()


if __name__ == "__main__":
    main()
