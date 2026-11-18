"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may                                                                                 
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]

    # 1. Metric values must be real numbers: NaN/inf compare False against every threshold.
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (NaN/inf slips past every threshold)")

    # 2. Grader failures, and per-row values that are missing or not booleans.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s): {pr['evaluator_failures'][0]}")
    rows = pr.get("rows") or []
    for m in graded:
        if rows and not any(m in r for r in rows):
            continue                      # metric not graded in this run: gate reports it as MISSING
        bad = [r for r in rows if not isinstance(r.get(m), bool)]
        if bad:
            problems.append(f"{len(bad)} row(s) with no boolean {m} (crashed grader), first "
                            f"{bad[0].get('item_id')}@{bad[0].get('seed')}={bad[0].get(m)!r}")

    # 3. Row count and (item, seed) coverage: every pair exactly once, the same pairs as main.
    man = pr.get("manifest") or {}
    want = int(man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        problems.append(f"{len(rows)} rows, manifest says {man.get('items')} items x "
                        f"{len(man.get('seeds') or [])} seeds = {want}")
    pairs = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = sorted({p for p in pairs if pairs.count(p) > 1}, key=str)
    if dups:
        problems.append(f"duplicated (item, seed) rows: {dups[:3]}")
    base_rows = base.get("rows") or []
    base_pairs = {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if set(pairs) != base_pairs:
        missing, extra = base_pairs - set(pairs), set(pairs) - base_pairs
        problems.append(f"(item, seed) set differs from the baseline: {len(missing)} missing "
                        f"{sorted(missing, key=str)[:3]}, {len(extra)} extra {sorted(extra, key=str)[:3]}")
    bman = base.get("manifest") or {}
    for key in ("items", "seeds"):
        if key in bman and man.get(key) != bman.get(key):
            problems.append(f"manifest {key} {man.get(key)!r} != baseline {bman.get(key)!r}")
    seeds_in_rows = sorted({r.get("seed") for r in rows}, key=str)
    if man.get("seeds") is not None and seeds_in_rows != sorted(man["seeds"], key=str):
        problems.append(f"rows cover seeds {seeds_in_rows}, manifest lists {man.get('seeds')}")

    # 4. Slice tags are derived from labels; a PR may not move an item out of a slice.
    base_tags = {r.get("item_id"): sorted(r.get("slices") or []) for r in base_rows}
    moved = sorted({r.get("item_id") for r in rows if r.get("item_id") in base_tags
                    and sorted(r.get("slices") or []) != base_tags[r.get("item_id")]}, key=str)
    if moved:
        problems.append(f"slice tags differ from the baseline for {moved[:3]}")

    # 5. The headline numbers must be the ones the rows produce (no hand-edited metrics).
    if rows and not problems:
        ids = [m for m in graded if all(m in r for r in rows)]
        filled = [{**r, "cost": r.get("cost", 0.0)} for r in rows]
        again = aggregate(filled, ids, k_values=spec.get("pass_k", []))
        for k, v in again.items():
            if k == "cost_per_success" and not all("cost" in r for r in rows):
                continue
            if k in (pr.get("metrics") or {}) and not _same_number(pr["metrics"][k], v):
                problems.append(f"metric {k}={pr['metrics'][k]!r} but its rows give {v!r}")

    # 6. Ratchet: on the same eval set a spec may only get stricter.
    if base_spec is not None:
        same_set = (spec.get("eval_set_version") == base_spec.get("eval_set_version")
                    or man.get("eval_set_sha") == bman.get("eval_set_sha"))
        if same_set:
            problems += ratchet_problems(spec, base_spec)
    return problems


def _same_number(a, b) -> bool:
    if a is None or b is None:
        return a is b
    try:
        return abs(float(a) - float(b)) <= 1e-9
    except (TypeError, ValueError):
        return a == b


def _looser(new: dict, old: dict, where: str) -> list[str]:
    """Threshold keys of one metric/slice: report every way `new` is laxer than `old`."""
    out = []
    if "min" in old and ("min" not in new or new["min"] < old["min"]):
        out.append(f"{where}: min {old['min']} -> {new.get('min')}")
    if "max" in old and ("max" not in new or new["max"] > old["max"]):
        out.append(f"{where}: max {old['max']} -> {new.get('max')}")
    if "max_increase" in old and ("max_increase" not in new or new["max_increase"] > old["max_increase"]):
        out.append(f"{where}: max_increase {old['max_increase']} -> {new.get('max_increase')}")
    if old.get("no_significant_drop") and not new.get("no_significant_drop"):
        out.append(f"{where}: no_significant_drop dropped")
    return out


def ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    out = []
    new_m = {m["id"]: m for m in spec.get("metrics", [])}
    for m in base_spec.get("metrics", []):
        mid = m["id"]
        if mid not in new_m:
            out.append(f"RATCHET metric {mid} removed")
            continue
        n = new_m[mid]
        if m.get("blocking") and not n.get("blocking"):
            out.append(f"RATCHET metric {mid} no longer blocking")
        if m.get("kind") != n.get("kind"):
            out.append(f"RATCHET metric {mid} kind {m.get('kind')} -> {n.get('kind')}")
        out += [f"RATCHET {x}" for x in _looser(n.get("threshold") or {}, m.get("threshold") or {}, f"metric {mid}")]
    new_s = {(x["name"], x["metric"]): x for x in spec.get("slices") or []}
    for sl in base_spec.get("slices") or []:
        key = (sl["name"], sl["metric"])
        where = f"slice {sl['name']}/{sl['metric']}"
        if key not in new_s:
            out.append(f"RATCHET {where} removed")
            continue
        n = new_s[key]
        if sl.get("blocking") and not n.get("blocking"):
            out.append(f"RATCHET {where} no longer blocking")
        out += [f"RATCHET {x}" for x in _looser(n, sl, where)]
    for key in ("seeds", "bootstrap", "pass_k", "eval_set", "labels", "adversarial_pack"):
        if key in base_spec and spec.get(key) != base_spec.get(key):
            out.append(f"RATCHET {key} changed {base_spec.get(key)!r} -> {spec.get(key)!r}")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        th = {k: sl[k] for k in ("min", "no_significant_drop") if k in sl}
        verdict, note = "ok", ""
        if not a:
            # An empty slice cannot vouch for anything; treat it as a failure, not a pass.
            val, verdict = None, "missing"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if sl.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
                else:
                    verdict, note = "missing", "no items shared with the baseline"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        lines.append(f"  {sid:<34} {val!s:<8} {json.dumps(th):<30} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
