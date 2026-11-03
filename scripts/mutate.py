"""Mutation check: plant one-line defects in a temp copy, run the suite, require it to fail.

Groups (reported separately, never as one bare percentage):
  orig     the 31 hand-picked mutants of round 1 (tolerance boundary split into two = 32), re-pointed at the round 2 code
  fable18  18 unplanned mutants from the round 1 Fable review (9 survived then; 3 are retired because the code
           they mutated was removed by the fixes, see REVIEW_ROUND2.md)
  round2   mutants written for the round 2 behaviours, after the tests; same caveat as orig31: hand-picked
  v2       mutants for the v2 changes (numfmt.py number conventions, recurrence-aware DuplicateDetector, vendor_identity keys);
           hand-picked after the v2 tests. Three v1 mutants whose code the v2 detector replaced are re-pointed at the new code
           (parts_flagged_as_duplicates, po_content_key_off, po_content_key_same_number_flagged).
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
M, X, V, Q, P, U, N = ("src/docmatch/match.py", "src/docmatch/extract.py", "src/docmatch/validate.py",
                       "src/docmatch/queue.py", "src/docmatch/pipeline.py", "src/docmatch/util.py", "src/docmatch/numfmt.py")

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
("orig", "parts_flagged_as_duplicates", V, " if e[1] != inv.invoice_no]", "]"),
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
("round2", "consumption_not_recorded", P, "self.consumed.setdefault(res.po_id, []).append((vendor_identity(inv.vendor), inv.invoice_no, inv.total))", "pass"),
("round2", "overbilled_reason_dropped", P, "if not within_tolerance(billed, _po_total(po), self.cfg):", "if False:"),
("round2", "po_content_key_off", V, "if inv.po_ref and any(e[2] == inv.po_ref for e in earlier):", "if False:"),
("round2", "po_content_key_same_number_flagged", V, "any(e[2] == inv.po_ref for e in earlier)", "any(e[2] == inv.po_ref for e in self.by_key.get(self.event_key(inv), []))"),
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
("round2", "items_unparsed_off", X, '    if n_unparsed:\n        issues.append("items_unparsed")\n', '    if n_unparsed:\n        pass\n'),
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
("v2", "num_group_first_zero_allowed", N, 'bool(re.fullmatch(r"[1-9]\\d{0,2}", first))', 'bool(re.fullmatch(r"\\d{1,3}", first))'),
("v2", "num_fraction_four_digits", N, '_FRAC = re.compile(r"\\d{1,3}")', '_FRAC = re.compile(r"\\d{1,4}")'),
("v2", "num_minor_digits_limit_off", N, "if digits is not None and len(fp) > digits:", "if False:"),
("v2", "num_minor_digits_off_by_one", N, "if digits is not None and len(fp) > digits:", "if digits is not None and len(fp) > digits + 1:"),
("v2", "num_group_of_two_allowed", N, 'all(re.fullmatch(r"\\d{3}", g) for g in rest)', 'all(re.fullmatch(r"\\d{2,3}", g) for g in rest)'),
("v2", "num_double_sign_allowed", N, "if s1 and s2:\n        return None", "if False:\n        return None"),
("v2", "num_sign_dropped", N, "return -v if (s1 or s2) else v", "return v"),
("v2", "num_plain_digits_15", N, '_PLAIN = re.compile(r"\\d{1,12}")', '_PLAIN = re.compile(r"\\d{1,15}")'),
("v2", "num_two_decimal_marks_allowed", N, "if body.count(dec) > 1:", "if body.count(dec) > 2:"),
("v2", "num_idr_not_zero_decimal", N, '"XPF", "IDR"}', '"XPF"}'),
("v2", "num_three_decimal_currencies_off", N, '_THREE_DECIMAL = {"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"}', "_THREE_DECIMAL = set()"),
("v2", "num_not_2dp_gate_off", N, "if v != v.quantize(CENT):\n            values[n] = None", "if False:\n            values[n] = None"),
("v2", "num_values_not_quantised", N, "values[n] = v.quantize(CENT)", "values[n] = v"),
("v2", "num_mixed_styles_not_detected", N, "common = [c for c in CONVS if all(c in d for d in live.values())]", "common = [c for c in CONVS if any(c in d for d in live.values())]"),
("v2", "num_ambiguity_guessed", N, "chosen = loc if loc in common else arith_pick", "chosen = loc if loc in common else (arith_pick or common[0])"),
("v2", "num_locale_ignored", N, "chosen = loc if loc in common else arith_pick", "chosen = arith_pick"),
("v2", "num_arithmetic_ignored", N, "chosen = loc if loc in common else arith_pick", "chosen = loc if loc in common else None"),
("v2", "num_locale_arithmetic_conflict_off", N, "if loc and arith_pick and loc != arith_pick:", "if False:"),
("v2", "num_arithmetic_tie_picks_first", N, "arith_pick = arith[0] if len(arith) == 1 else None", "arith_pick = arith[0] if arith else None"),
("v2", "num_close_exclusive", N, "return abs(a - b) <= CENT", "return abs(a - b) < CENT"),
("v2", "num_line_relation_off", N, "checks.append(_close((qty * unit).quantize(CENT), amt))", "pass"),
("v2", "num_item_sum_relation_off", N, "checks.append(_close(line_sum, sub))", "pass"),
("v2", "num_total_relation_off", N, "checks.append(_close(base + (tax if tax is not None else Decimal(0)), tot))", "pass"),
("v2", "num_missing_tax_not_zero", N, "(tax if tax is not None else Decimal(0)), tot))", "(tax if tax is not None else Decimal(1)), tot))"),
("v2", "num_partial_item_sum_used", N, "if amts and len(amts) == len(items) else None", "if amts else None"),
("v2", "num_inferred_flag_off", N, 'if len(no_cur[n]) == 2 and len({v for v in no_cur[n].values()}) > 1:', "if False:"),
("v2", "num_evidence_labels_swapped", N, 'evidence.append("currency" if len(with_cur[n]) == 1 else "document_convention")', 'evidence.append("document_convention" if len(with_cur[n]) == 1 else "currency")'),
("v2", "num_mixed_keeps_separator_tokens", N, '            else:\n                issues.append(f"{n}_unparseable")', '            else:\n                values[n] = next(iter(d.values()))'),
("v2", "extract_assume_currency_dropped", X, "inv.currency, assume_currency, loc)", "inv.currency, None, loc)"),
("v2", "extract_locale_ignored", X, "loc = _single(_RE_LOCALE, text, \"locale\", issues)", "loc = None"),
("v2", "extract_inferred_total_full_confidence", X, 'inv.total, c["total"] = total, 0.7 if "total" in inferred else 1.0', 'inv.total, c["total"] = total, 1.0'),
("v2", "extract_item_issue_names_leak", X, 'issues.extend(i for i in num_issues if not i.startswith("item"))', "issues.extend(num_issues)"),
("v2", "cadence_weekly_wider", V, "CADENCES = ((5, 9),", "CADENCES = ((5, 10),"),
("v2", "cadence_fortnightly_wider", V, "(12, 16),", "(12, 17),"),
("v2", "cadence_monthly_wider", V, "(26, 35))", "(26, 36))"),
("v2", "cadence_classes_not_compared", V, "if k is not None and k == _cadence_class(g2):", "if k is not None:"),
("v2", "cadence_no_end_position", V, "for start in (i - 2, i - 1, i):", "for start in (i - 2, i - 1):"),
("v2", "cadence_no_start_position", V, "for start in (i - 2, i - 1, i):", "for start in (i, i - 1):"),
("v2", "cadence_bounds_off", V, "if start < 0 or start + 2 >= len(u):", "if start < 0:"),
("v2", "dup_window_exclusive", V, "abs((e[0] - d).days) <= self.window_days)]", "abs((e[0] - d).days) < self.window_days)]"),
("v2", "dup_same_reference_off", V, "if inv.po_ref and any(e[2] == inv.po_ref for e in earlier):", "if False:"),
("v2", "dup_distinct_refs_off", V, "if e[2] and inv.po_ref and e[2] != inv.po_ref:", "if False:"),
("v2", "dup_distinct_context_off", V, "return bool(self.use_context and e[3] is not None and inv.context is not None and e[3] != inv.context)", "return False"),
("v2", "dup_currency_not_in_key", V, "return (vendor_identity(inv.vendor), inv.total, inv.currency)", "return (vendor_identity(inv.vendor), inv.total)"),
("v2", "dup_event_key_uses_stripped_name", V, "return (vendor_identity(inv.vendor), inv.total, inv.currency)", 'return (vendor_identity(inv.vendor).split("|")[0], inv.total, inv.currency)'),
("v2", "dup_id_key_uses_raw_name", V, "return (vendor_identity(inv.vendor), inv.invoice_no, inv.part)", 'return ((inv.vendor or "").lower(), inv.invoice_no, inv.part)'),
("v2", "dup_part_group_uses_stripped_name", V, "return (vendor_identity(inv.vendor), inv.invoice_no, inv.po_ref)", 'return (vendor_identity(inv.vendor).split("|")[0], inv.invoice_no, inv.po_ref)'),
("v2", "dup_cadence_off", V, "if self.use_cadence and d is not None:", "if d is not None:"),
("v2", "dup_batch_surplus_off_by_one", V, "if any(n >= counts[d] + 1 for dd, n in counts.items() if dd != d):", "if any(n >= counts[d] for dd, n in counts.items() if dd != d):"),
("v2", "dup_new_date_in_cadence_flagged", V, "if d not in counts:\n                    return None, \"recurring_batch\"", "if False:\n                    return None, \"recurring_batch\""),
("v2", "dup_missing_dates_not_compared", V, "(e[0] is None and d is None) or", "False or"),
("v2", "dup_context_off_ignored", V, "return bool(self.use_context and", "return bool(True and"),
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
