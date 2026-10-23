#!/usr/bin/env python3
"""Compute gate verdicts from normalized metrics — the only place verdicts come from (P1).

Usage:
    python scripts/compute_gates.py --config <bob-pipeline.yaml> --role <role> \
        --metrics <metrics.json> [--baselines <baselines.json>] [--tests-exit <int>] \
        [--traceability <traceability.json>]

Inputs:
    metrics.json      list of {"category", "metric", "metric_value"} from parse_reports.py
                      (pass "[]" or an empty file when no tool metrics apply)
    baselines.json    {"complexity": <number>, "duplication": <number>}; a category with no
                      baseline yet is captured from the current metric and written back to
                      this path (when it is a file path), so the next run compares against it
    --tests-exit      exit code of the project test suite run (for the tests-green gate)
    traceability.json {"scenario_ids": [...], "traced_ids": [...]} for gherkin-traceability

Output (stdout): JSON list of GateResult objects:
    {"gate", "role", "metric_value", "threshold", "baseline", "passed", "diagnosis"}
Exit 0 always (verdicts are data); exit 2 on usage errors.
"""
import argparse
import json
import sys
from pathlib import Path

import yaml


def load_json_arg(value):
    if value is None:
        return None
    p = Path(value)
    if p.exists():
        text = p.read_text(encoding="utf-8-sig")
    elif value.lstrip().startswith(("[", "{")) or not value.strip():
        text = value
    else:
        return None  # a path that doesn't exist yet (e.g. first-run baselines file)
    return json.loads(text) if text.strip() else None


def result(gate, role, passed, metric_value=None, threshold=None, baseline=None, diagnosis=None, deviation=False):
    r = {"gate": gate, "role": role, "passed": passed}
    if deviation:
        r["deviation"] = True
    if metric_value is not None:
        r["metric_value"] = metric_value
    if threshold is not None:
        r["threshold"] = threshold
    if baseline is not None:
        r["baseline"] = baseline
    if diagnosis:
        r["diagnosis"] = diagnosis
    return r


def metric_for(metrics, category):
    for m in metrics or []:
        if m.get("category") == category:
            return m.get("metric_value")
    return None


DEPRECATED_ROLES = {"cleaner": "architect"}
MERGE_GATE = "merge-gate"  # pseudo-role: gates of the orchestrator's merge-gate run (D20)
MERGE_GATE_GATES = ["tests-green", "diff-coverage", "constitution-traceability"]
# gate -> registry tool category whose metric feeds it (D20)
QG_GATES = {
    "lint": "lint",
    "format": "format",
    "architecture": "architecture",
    "diff-coverage": "diff-coverage",
    "constitution-traceability": "constitution-traceability",
}
DEFAULT_DIFF_COVERAGE_MIN = 80


def compute(config, role_name, metrics, baselines, tests_exit, traceability, stack=None, captured=None):
    """captured: optional dict; categories whose baseline was first captured are added to it."""
    role_name = DEPRECATED_ROLES.get(role_name, role_name)
    if role_name == MERGE_GATE:
        role = {"name": MERGE_GATE, "enabled": True, "gates": MERGE_GATE_GATES}
    else:
        role = next((r for r in config["roles"] if DEPRECATED_ROLES.get(r["name"], r["name"]) == role_name), None)
    if role is None:
        raise SystemExit(f"unknown role '{role_name}'")
    if not role.get("enabled", True):
        return []  # disabled role: no gates, no metrics expected
    qg = config.get("quality_gates") or {}
    qg_on = qg.get("enabled", True)
    qg_per_gate = qg.get("gates") or {}
    framework_enabled = (config.get("mutation") or {}).get("framework_enabled", False)
    thresholds = config["thresholds"]
    stack = stack or config.get("stack")
    enabled_cats = {
        t["category"] for t in config["tools"]
        if t["enabled"] and t.get("stack") in (stack, "any")
    }
    results = []

    for gate in role["gates"]:
        if gate == "tests-green":
            if tests_exit is None:
                results.append(result(gate, role_name, False, diagnosis="test suite was not run (--tests-exit missing)"))
            else:
                ok = tests_exit == 0
                results.append(result(gate, role_name, ok, diagnosis=None if ok else f"test suite exited {tests_exit}"))

        elif gate == "mutation-score":
            # D22: mutation never blocks — a low or missing score is a deviation, not a failure
            if not framework_enabled or "mutation" not in enabled_cats:
                results.append(result(gate, role_name, True, diagnosis="mutation framework off (mutation.framework_enabled) — semantic hardening only"))
                continue
            value = metric_for(metrics, "mutation")
            threshold = thresholds["mutation_score_min"]
            if value is None:
                results.append(result(gate, role_name, True, threshold=threshold, deviation=True, diagnosis="DEVIATION: no mutation metric produced — record in the report"))
            else:
                ok = value >= threshold
                results.append(result(gate, role_name, True, metric_value=value, threshold=threshold, deviation=not ok,
                                      diagnosis=None if ok else f"DEVIATION: mutation score {value} below threshold {threshold} (non-blocking)"))

        elif gate == "hardening-findings":
            value = metric_for(metrics, "hardening")
            if value is None:
                results.append(result(gate, role_name, False, diagnosis="no hardening metric produced — report unfixed_findings from the hardener report"))
            else:
                ok = value == 0
                results.append(result(gate, role_name, ok, metric_value=value, threshold=0,
                                      diagnosis=None if ok else f"{value} unfixed hardening finding(s): strengthen the tests (in-place repair) or send back to coder if production code is the cause"))

        elif gate in QG_GATES:
            category = QG_GATES[gate]
            if not qg_on or qg_per_gate.get(gate, True) is False:
                results.append(result(gate, role_name, True, diagnosis="quality gate disabled by config"))
                continue
            if category not in enabled_cats:
                results.append(result(gate, role_name, True, diagnosis=f"no {category} tool enabled for this stack — gate skipped"))
                continue
            value = metric_for(metrics, category)
            if value is None:
                results.append(result(gate, role_name, False, diagnosis=f"no {category} metric produced — run the {category} tool"))
            elif gate == "diff-coverage":
                threshold = qg.get("diff_coverage_min", DEFAULT_DIFF_COVERAGE_MIN)
                ok = value >= threshold
                results.append(result(gate, role_name, ok, metric_value=value, threshold=threshold,
                                      diagnosis=None if ok else f"diff coverage {value}% below {threshold}%: add tests for the changed lines"))
            else:
                ok = value == 0
                results.append(result(gate, role_name, ok, metric_value=value, threshold=0,
                                      diagnosis=None if ok else f"{category} failed ({value}): see the tool output and fix in place"))

        elif gate in ("complexity-baseline", "duplication-baseline"):
            category = gate.split("-")[0]
            policy = thresholds[f"{category}_policy"]
            if policy == "off" or category not in enabled_cats:
                results.append(result(gate, role_name, True, diagnosis=f"{category} gate disabled by policy/tooling"))
                continue
            value = metric_for(metrics, category)
            baseline = (baselines or {}).get(category)
            if value is None:
                results.append(result(gate, role_name, False, baseline=baseline, diagnosis=f"no {category} metric produced — run the {category} tool"))
            elif baseline is None:
                # first run: nothing to compare against; value becomes the baseline
                if captured is not None:
                    captured[category] = value
                results.append(result(gate, role_name, True, metric_value=value, diagnosis="first run — captured as baseline"))
            else:
                ok = value <= baseline
                results.append(result(gate, role_name, ok, metric_value=value, baseline=baseline,
                                      diagnosis=None if ok else f"{category} {value} worse than baseline {baseline}: refactor before handoff (in-place repair)"))

        elif gate == "gherkin-traceability":
            if not traceability:
                results.append(result(gate, role_name, False, diagnosis="no traceability data supplied"))
                continue
            missing = sorted(set(traceability.get("scenario_ids", [])) - set(traceability.get("traced_ids", [])))
            ok = not missing
            results.append(result(gate, role_name, ok,
                                  diagnosis=None if ok else f"scenarios without a traced test: {', '.join(missing)}"))

    # coverage is informational: report it whenever a metric exists, never block (P1/spec)
    cov = metric_for(metrics, "coverage")
    if cov is not None:
        results.append(result("coverage-informational", role_name, True, metric_value=cov, diagnosis="informational only, never blocks"))

    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--role", required=True)
    ap.add_argument("--metrics", default="[]")
    ap.add_argument("--baselines")
    ap.add_argument("--tests-exit", type=int, default=None)
    ap.add_argument("--traceability")
    ap.add_argument("--stack", default=None,
                     help="stack of the slice being gated (e.g. csharp, python); "
                          "defaults to config's top-level stack. Scopes which tools/ "
                          "entries count as 'enabled' for this gate computation — a "
                          "multi-stack project's tools list is not otherwise filtered "
                          "per-role, which previously let one stack's enabled tool "
                          "force a gate for another stack with no tool configured.")
    args = ap.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8-sig"))
    baselines = load_json_arg(args.baselines)
    captured = {}
    results = compute(
        config,
        args.role,
        load_json_arg(args.metrics) or [],
        baselines,
        args.tests_exit,
        load_json_arg(args.traceability),
        args.stack,
        captured,
    )
    if captured and args.baselines and not args.baselines.lstrip().startswith(("[", "{")):
        merged = {**(baselines or {}), **captured}
        Path(args.baselines).parent.mkdir(parents=True, exist_ok=True)
        Path(args.baselines).write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    json.dump(results, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
