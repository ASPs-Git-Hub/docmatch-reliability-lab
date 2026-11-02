"""Mutation check: plant one-line defects in a temp copy, run the suite, require it to fail.

Groups (reported separately, never as one bare percentage):
  orig     the 31 hand-picked mutants of round 1 (tolerance boundary split into two = 32), re-pointed at the round 2 code
  fable18  18 unplanned mutants from the round 1 Fable review (9 survived then; 3 are retired because the code
           they mutated was removed by the fixes, see REVIEW_ROUND2.md)
  round2   mutants written for the round 2 behaviours, after the tests; same caveat as orig31: hand-picked
Outcome classes: KILLED (test assertion or error: the suite reports FAILED with N>0 tests run), CRASH (timeout,
or no tests ran, e.g. import error: not counted as a kill), SURVIVED, PATTERN-ERROR.
Exit 1 if anything survives, crashes, or a pattern does not occur exactly once.
Usage: python3 scripts/mutate.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M, X, V, Q, P, U = ("src/docmatch/match.py", "src/docmatch/extract.py", "src/docmatch/validate.py",
                    "src/docmatch/queue.py", "src/docmatch/pipeline.py", "src/docmatch/util.py")

# (group, name, file relative to ROOT, old text, new text)
MUTANTS = [
("orig", "tolerance_max_to_min", M, "return max(abs(po_total) * cfg.rel, cfg.floor)", "return min(abs(po_total) * cfg.rel, cfg.floor)"),
("orig", "tolerance_over_boundary_exclusive", M, "return diff <= min(tolerance(po_total, cfg), cfg.max_over)", "return diff < min(tolerance(po_total, cfg), cfg.max_over)"),
("orig", "tolerance_under_boundary_exclusive", M, "return -diff <= tolerance(po_total, cfg)", "return -diff < tolerance(po_total, cfg)"),
("orig", "window_after_exclusive", M, "(i - p).days <= cfg.window_after_days", "(i - p).days < cfg.window_after_days"),
("orig", "window_before_exclusive", M, "-cfg.window_before_days <= (i - p)", "-cfg.window_before_days < (i - p)"),
("orig", "dup_po_ids_allowed", M, "if len(found) > 1:", "if len(found) > 2:"),
("orig", "tier1_skip_vendor_check", M, 'if not _vendor_agrees(inv.vendor, p.get("vendor"), cfg):', "if False:"),
("orig", "tier1_skip_total_check", M, "if not within_tolerance(inv.total, _po_total(p), cfg):", "if False:"),
("orig", "tier1_skip_currency_check", M, 'if not inv.currency or inv.currency.upper() != (p.get("currency") or "").upper():', "if False:"),
("orig", "tier3_auto_matches", M, 'return MatchResult("AMBIGUOUS", None, 3,', 'return MatchResult("MATCH", t3[0]["po_id"], 3,'),
("orig", "multi_candidates_pick_first", M, "if len(same_cur) == 1:", "if len(same_cur) >= 1:"),
("orig", "currency_mismatch_auto_matches", M, 'return MatchResult("AMBIGUOUS", None, tier, [p["po_id"] for p in cands], ["currency_mismatch"])', 'return MatchResult("MATCH", cands[0]["po_id"], tier, [p["po_id"] for p in cands], [])'),
("orig", "insufficient_fields_or", M, "(inv.vendor is None and inv.po_ref is None)", "(inv.vendor is None or inv.po_ref is None)"),
("orig", "ref_not_uppercased", U, "return ref.strip().upper() if ref else None", "return ref.strip() if ref else None"),
("orig", "ampersand_dropped", U, 's = name.lower().replace("&", " and ")', 's = name.lower().replace("&", " ")'),
("orig", "zero_total_allowed", V, "if inv.total <= 0:", "if inv.total < 0:"),
("orig", "one_cent_flagged", V, "if abs(expected - inv.total) > CENT:", "if abs(expected - inv.total) >= CENT:"),
("orig", "subtotal_check_off", V, "if inv.subtotal is not None and abs(line_sum - inv.subtotal) > CENT:", "if False:"),
("orig", "resubmission_inverted", V, "self.by_id[k] == fingerprint(inv)", "self.by_id[k] != fingerprint(inv)"),
("orig", "parts_flagged_as_duplicates", V, "ck = (norm_vendor(inv.vendor), inv.total, inv.date)\n        other = self.by_content.get(ck)\n        if other is not None and other != inv.invoice_no:", "ck = (norm_vendor(inv.vendor), inv.total, inv.date)\n        other = self.by_content.get(ck)\n        if other is not None:"),
("orig", "parts_complete_too_early", V, 'if len(g["parts"]) == n:', 'if len(g["parts"]) >= 1:'),
("orig", "part_count_conflict_ignored", V, 'g["n"] != n or ', ""),
("orig", "part_total_conflict_inverted", V, 'g["parts"][i].total != inv.total', 'g["parts"][i].total == inv.total'),
("orig", "queue_not_idempotent", Q, "if k in self._entries:", "if False:"),
("orig", "queue_amount_cap_dropped", Q, "min(entry.amount, 100000.0)", "entry.amount"),
("orig", "queue_negative_age", Q, "age = max(0, (now - datetime.date.fromisoformat(entry.invoice_date)).days)", "age = (now - datetime.date.fromisoformat(entry.invoice_date)).days"),
("orig", "queue_order_reversed", Q, "(-self.priority(e, now)", "(self.priority(e, now)"),
("orig", "resubmission_not_skipped", P, 'if dup == "resubmission":', "if False:"),
("orig", "queue_not_resolved_on_complete", P, 'self.queue.resolve(key, "parts_incomplete")', "pass"),
("orig", "aggregate_uses_last_part_only", P, "for p in parts.values()", "for p in [inv]"),
("orig", "na_po_accepted", X, "refs = [r for r in refs if r.upper() not in _NA]", "refs = [r for r in refs if True]"),
("orig", "header_taken_as_invoice_no", X, r'(r"\b(INV[-/]\w[\w\-/]*)"', r'(r"\b(INV\w*[-/]?\w*)"'),
("fable18", "fuzzy_0.5", M, "fuzzy_threshold: float = 0.85", "fuzzy_threshold: float = 0.5"),
("fable18", "rel_0.05", M, 'rel: Decimal = Decimal("0.02")', 'rel: Decimal = Decimal("0.05")'),
("fable18", "floor_5", M, 'floor: Decimal = Decimal("1.00")', 'floor: Decimal = Decimal("5.00")'),
("fable18", "before_30", M, "window_before_days: int = 3", "window_before_days: int = 30"),
("fable18", "after_180", M, "window_after_days: int = 90", "window_after_days: int = 180"),
("fable18", "ref_prefix", M, 'norm_ref(p.get("po_id")) == inv.po_ref', '(norm_ref(p.get("po_id")) or "").startswith(inv.po_ref)'),
("fable18", "pick_no_cur_guard", M, "and inv.currency]", "and True]"),
("fable18", "abs_dropped", M, "return max(abs(po_total) * cfg.rel, cfg.floor)", "return max(po_total * cfg.rel, cfg.floor)"),
("fable18", "malformed_gate_off", P, 'if "malformed" in reasons:', "if False:"),
("fable18", "register_off", P, "self.dups.register(inv)", "pass"),
("fable18", "subtotal_1_dollar", V, "abs(line_sum - inv.subtotal) > CENT", "abs(line_sum - inv.subtotal) > Decimal(1)"),
("fable18", "na_set_shrunk", X, '_NA = {"N/A", "NA", "NONE", "TBD"}', '_NA = {"N/A"}'),
("fable18", "part_low_index", V, "if not (1 <= i <= n <= MAX_PARTS):", "if not (i <= n <= MAX_PARTS):"),
("fable18", "queue_abs_off", Q, "float(abs(amount))", "float(amount)"),
("fable18", "suffix_set_empty", U, "_SUFFIXES = set(_SUFFIX_CANON)", "_SUFFIXES = set()"),
("round2", "consumed_check_off", P, "prior = self.consumed.get(res.po_id)", "prior = None"),
("round2", "consumption_not_recorded", P, "self.consumed.setdefault(res.po_id, []).append((norm_vendor(inv.vendor), inv.invoice_no, inv.total))", "pass"),
("round2", "overbilled_reason_dropped", P, "if not within_tolerance(billed, _po_total(po), self.cfg):", "if False:"),
("round2", "po_content_key_off", V, "other = self.by_po.get((norm_vendor(inv.vendor), inv.total, inv.currency, inv.po_ref))", "other = None"),
("round2", "po_content_key_same_number_flagged", V, "other = self.by_po.get((norm_vendor(inv.vendor), inv.total, inv.currency, inv.po_ref))\n            if other is not None and other != inv.invoice_no:", "other = self.by_po.get((norm_vendor(inv.vendor), inv.total, inv.currency, inv.po_ref))\n            if other is not None:"),
("round2", "unlabelled_ref_gate_off", M, "if inv.ref_tokens:", "if False:"),
("round2", "twin_outside_window_off", M, "if len(t2_all) > len(t2):", "if False:"),
("round2", "tier2_currency_prefilter_off", M, '== (inv.currency or "").upper()]\n    t2 = ', ']\n    t2 = '),
("round2", "closer_candidate_off", M, "if closer:", "if False:"),
("round2", "closer_candidate_leq", M, "< abs(inv.total - pt)]", "<= abs(inv.total - pt)]"),
("round2", "confidence_gate_off", M, 'weak = _low_conf(inv, ("vendor", "currency", "total", "date"))', "weak = []"),
("round2", "confidence_gate_drops_date", M, '("vendor", "currency", "total", "date"))', '("vendor", "currency", "total"))'),
("round2", "confidence_gate_includes_zero", M, "0.0 < inv.conf.get(f, 0.0) < 1.0", "-1.0 < inv.conf.get(f, 0.0) < 1.0"),
("round2", "invoice_no_conf_gate_off", V, 'if 0.0 < inv.conf.get("invoice_no", 0.0) < 1.0:', "if False:"),
("round2", "suffix_agreement_off", M, "return not (a and b and a != b)", "return True"),
("round2", "vendor_identity_ignores_suffix", U, 'return (n + "|" + legal_suffix(name)) if n else ""', "return n"),
("round2", "limited_not_ltd", U, '"limited": "ltd"', '"limited": "limited"'),
("round2", "over_cap_off", M, "return diff <= min(tolerance(po_total, cfg), cfg.max_over)", "return diff <= tolerance(po_total, cfg)"),
("round2", "under_billing_capped", M, "return -diff <= tolerance(po_total, cfg)", "return -diff <= min(tolerance(po_total, cfg), cfg.max_over)"),
("round2", "max_over_default_500", M, 'max_over: Decimal = Decimal("50.00")', 'max_over: Decimal = Decimal("500.00")'),
("round2", "money_comma_without_decimals", U, "(?=\\.))", ")"),
("round2", "money_three_decimals", U, "(?:\\.(\\d{1,2}))?$", "(?:\\.(\\d{1,3}))?$"),
("round2", "money_double_sign_allowed", U, "if m.group(1) and m.group(3):", "if False:"),
("round2", "calendar_date_unchecked", X, "datetime.date.fromisoformat(v)", "None"),
("round2", "currency_conflict_off", X, 'issues.append("conflicting_currency")', "pass"),
("round2", "currency_symbol_only_off", X, 'issues.append("currency_symbol_only")', "pass"),
("round2", "symbol_set_conflict_off", X, 'issues.append("conflicting_currency_symbols")', "pass"),
("round2", "items_unparsed_off", X, '        else:\n            issues.append("items_unparsed")\n', "        else:\n            pass\n"),
("round2", "items_header_empty_off", X, 'if _RE_ITEMS_HDR.search(text) and not candidates:', "if False:"),
("round2", "line_arithmetic_off", V, "if abs((qty * unit).quantize(CENT, ROUND_HALF_UP) - amt) > CENT:", "if False:"),
("round2", "subtotal_without_items_off", V, "elif inv.subtotal is not None and abs(inv.subtotal + (inv.tax or Decimal(0)) - inv.total) > CENT:", "elif False:"),
("round2", "amount_due_alt_used_when_total_garbled", X, "elif alt is not None and raw_total is None:", "elif alt is not None:"),
("round2", "amount_due_difference_unflagged", X, "if alt is not None and alt != total:", "if False:"),
("round2", "fingerprint_drops_currency", V, "inv.po_ref, inv.currency, inv.subtotal", "inv.po_ref, inv.subtotal"),
("round2", "fingerprint_drops_items", V, "inv.tax, tuple(inv.items))", "inv.tax)"),
("round2", "fingerprint_drops_subtotal", V, "inv.currency, inv.subtotal, inv.tax", "inv.currency, inv.tax"),
("round2", "part_currency_check_off", V, ' or g["cur"] != inv.currency', ""),
("round2", "part_date_check_off", V, ' or g["date"] != inv.date', ""),
("round2", "part_upper_bound_off", X, " <= int(m.group(2)) <= MAX_PARTS:", " <= int(m.group(2)):"),
("round2", "part_two_lines_allowed", X, "if len(pl) > 1:", "if False:"),
("round2", "tracker_range_check_off", V, "if not (1 <= i <= n <= MAX_PARTS):", "if False:"),
("round2", "digest_truncated", P, ".hexdigest()\n        key", ".hexdigest()[:8]\n        key"),
("round2", "lock_removed", P, "with self._lock:", "if True:"),
("round2", "exception_isolation_off", P, "except Exception as exc:", "except ZeroDivisionError as exc:"),
("round2", "label_reads_next_line", X, 'r"[ \\t]*[:#]?[ \\t]*(.*?)[ \\t]*$"', 'r"\\s*[:#]?\\s*(.*?)[ \\t]*$"'),
("round2", "po_label_without_separator", X, "(?:[ \\t]*[:#][ \\t]*|[ \\t]+)(.*?)[ \\t]*$", "(?:[ \\t]*[:#]?[ \\t]*)(.*?)[ \\t]*$"),
("round2", "po_ref_invalid_not_flagged", X, 'issues.append("po_ref_invalid")', "pass"),
("round2", "po_conflict_not_flagged", X, 'issues.append("conflicting_po_ref")', "pass"),
("round2", "date_fallback_restored", X, 'inv.date, c["date"] = None, 0.0', 'inv.date, c["date"] = (_m.group(1), 0.6) if (_m := re.search(r"(\\d{4}-\\d{2}-\\d{2})", text)) else (None, 0.0)'),
]


def run_suite(cwd):
    """Return (returncode, combined output). 124 = timeout."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        p = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"], cwd=cwd, env=env,
                           capture_output=True, text=True, timeout=180)
        return p.returncode, p.stderr + p.stdout
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def classify(rc, out):
    """KILLED only if tests actually ran and reported failures or errors; anything else non-zero is CRASH."""
    if rc == 0:
        return "SURVIVED"
    ran = re.search(r"Ran (\d+) tests?", out)
    if rc == 1 and ran and int(ran.group(1)) > 0 and "FAILED (" in out and "_FailedTest" not in out:
        return "KILLED"
    return "CRASH"


def first_failure(out):
    m = re.search(r"^(?:FAIL|ERROR): (\S+) \(([^)]*)\)", out, re.M)
    return f"{m.group(2)}" if m else "?"


def main():
    results = {}  # name -> class
    groups = {}
    bad_pattern = []
    ignore = shutil.ignore_patterns("__pycache__", "evidence", ".git", ".github")
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "base")
        shutil.copytree(ROOT, base, ignore=ignore)
        rc, out = run_suite(base)
        if rc != 0:
            print("BASELINE FAILS: fix the suite before mutating")
            return 1
        ran = re.search(r"Ran (\d+) tests?", out).group(1)
        print(f"BASELINE ok: {ran} tests pass")
        # control: a no-op edit must SURVIVE, otherwise the harness cannot tell killed from survived
        ctl = os.path.join(tmp, "ctl")
        shutil.copytree(base, ctl, ignore=shutil.ignore_patterns("__pycache__"))
        with open(os.path.join(ctl, "src/docmatch/util.py"), "a") as f:
            f.write("\n# control no-op\n")
        if run_suite(ctl)[0] != 0:
            print("CONTROL FAILED: a harmless edit made the suite fail; harness is unreliable")
            return 2
        print("CONTROL ok: no-op edit survives as it should")
        for i, (group, name, rel, old, new) in enumerate(MUTANTS):
            work = os.path.join(tmp, f"m{i}")
            shutil.copytree(base, work, ignore=shutil.ignore_patterns("__pycache__"))
            path = os.path.join(work, rel)
            with open(path) as f:
                src = f.read()
            count = src.count(old)
            if count != 1:
                print(f"PATTERN-ERROR {name}: {count} occurrences in {rel}")
                bad_pattern.append(name)
                shutil.rmtree(work)
                continue
            with open(path, "w") as f:
                f.write(src.replace(old, new))
            rc, out = run_suite(work)
            cls = classify(rc, out)
            results[name] = cls
            groups.setdefault(group, []).append(cls)
            extra = f"  first failing test: {first_failure(out)}" if cls == "KILLED" else ""
            print(f"{cls:<9} [{group}] {name}{extra}")
            shutil.rmtree(work)
    print()
    for g, lst in groups.items():
        print(f"group {g}: mutants {len(lst)}  killed {lst.count('KILLED')}  survived {lst.count('SURVIVED')}  crash {lst.count('CRASH')}")
    total = len(MUTANTS)
    k = sum(1 for v in results.values() if v == "KILLED")
    sv = sum(1 for v in results.values() if v == "SURVIVED")
    cr = sum(1 for v in results.values() if v == "CRASH")
    print(f"\nmutants: {total}  killed: {k}  survived: {sv}  crash/timeout: {cr}  pattern errors: {len(bad_pattern)}")
    print("note: all mutants are hand-picked and written after the code and tests; this is not a random-operator score")
    return 1 if sv or cr or bad_pattern else 0


if __name__ == "__main__":
    sys.exit(main())
