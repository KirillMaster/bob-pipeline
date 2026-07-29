#!/usr/bin/env python3
"""Compute gate verdicts from normalized metrics — the only place verdicts come from (P1).

Usage:
    python scripts/compute_gates.py --config <bob-pipeline.yaml> --role <role> \
        --metrics <metrics.json> [--baselines <baselines.json>] [--tests-exit <int>] \
        [--traceability <traceability.json>]

Inputs:
    metrics.json      list of {"category", "metric", "metric_value"} from parse_reports.py
                      (pass "[]" or an empty file when no tool metrics apply)
    baselines.json    {"complexity": <number>, "duplication": <number>} captured at run start
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
    text = p.read_text(encoding="utf-8") if p.exists() else value
    return json.loads(text) if text.strip() else None


def result(gate, role, passed, metric_value=None, threshold=None, baseline=None, diagnosis=None):
    r = {"gate": gate, "role": role, "passed": passed}
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


def compute(config, role_name, metrics, baselines, tests_exit, traceability):
    role = next((r for r in config["roles"] if r["name"] == role_name), None)
    if role is None:
        raise SystemExit(f"unknown role '{role_name}'")
    thresholds = config["thresholds"]
    enabled_cats = {t["category"] for t in config["tools"] if t["enabled"]}
    results = []

    for gate in role["gates"]:
        if gate == "tests-green":
            if tests_exit is None:
                results.append(result(gate, role_name, False, diagnosis="test suite was not run (--tests-exit missing)"))
            else:
                ok = tests_exit == 0
                results.append(result(gate, role_name, ok, diagnosis=None if ok else f"test suite exited {tests_exit}"))

        elif gate == "mutation-score":
            if "mutation" not in enabled_cats:
                results.append(result(gate, role_name, True, diagnosis="mutation category disabled for this stack — role degraded to heuristic strengthening (recorded as deviation)"))
                continue
            value = metric_for(metrics, "mutation")
            threshold = thresholds["mutation_score_min"]
            if value is None:
                results.append(result(gate, role_name, False, threshold=threshold, diagnosis="no mutation metric produced — run the mutation tool and parse its report"))
            else:
                ok = value >= threshold
                results.append(result(gate, role_name, ok, metric_value=value, threshold=threshold,
                                      diagnosis=None if ok else f"mutation score {value} below threshold {threshold}: kill surviving mutants with new tests (in-place repair)"))

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
    args = ap.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    results = compute(
        config,
        args.role,
        load_json_arg(args.metrics) or [],
        load_json_arg(args.baselines),
        args.tests_exit,
        load_json_arg(args.traceability),
    )
    json.dump(results, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
