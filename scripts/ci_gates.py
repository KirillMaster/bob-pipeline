#!/usr/bin/env python3
"""Mechanical bob gates outside bob-run (1.11.0): one CLI entry for Jenkins, GitHub Actions and local pre-push.

Usage:
    python scripts/ci_gates.py --base <ref> [--head HEAD] [--repo .] [--config .claude/bob-pipeline.yaml]
        [--gates tidy-first,adr,bugfix] [--manifest <file> ...] [--manifest-dir .bob/features]
        [--run-tests] [--warn-only] [--annotations github] [--report <out.json>]

Gates (base is resolved to `git merge-base <base> <head>`, so pass the target branch, e.g. origin/develop):
    tidy-first  E1 + Z16, needs only git: a tidy:/refactor:/structural:/style:/format: commit must not edit existing
                test assertions or add test methods (scripts/tidy_first.py).
    adr         G1: an architectural change needs an ADR with Context, Decision, Alternatives (scripts/adr_gate.py).
                Without slice manifests the trigger is derived from the diff: a new top-level `interface` type or a new
                `ProjectReference` in a *.csproj; the ADR is an added/changed file under adr.paths with complete sections;
                waiver = a commit body line `adr-exempt: <reason>`. With manifests the manifest triggers apply.
    bugfix      K1, K4, K5, K7, K8 (+ K2/K3 with --run-tests) for every changed slice manifest with `kind: bugfix`
                (scripts/bugfix_gates.py). Skipped when the range has no bugfix manifest.

Manifests: --manifest (repeatable) or every `*.manifest.yaml` under --manifest-dir added/changed in base..head.
Config sections adr / tidy_first / bugfix with `enabled: false` switch a gate off.
--warn-only reports offenders but exits 0 (report-only rollout). Exit 0 = pass, 1 = offenders, 2 = usage error.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

import adr_gate
import bugfix_gates
import tidy_first
from diffkit import DEFAULT_TEST_PATHS, changed_files, git, matches, offender
from plan_conformance import declared_types, file_at, load_manifest

GATES = ["tidy-first", "adr", "bugfix"]
EXEMPT = re.compile(r"^adr-exempt:\s*(\S.*)$", re.I | re.M)
PROJECT_REF = re.compile(r"<ProjectReference\b", re.I)


def resolve_base(repo, base, head):
    r = git(repo, "merge-base", base, head, check=False)
    if r.returncode != 0 or not r.stdout.strip():
        raise SystemExit(f"cannot resolve merge-base of {base} and {head}: fetch full history (fetch-depth: 0 / git fetch --unshallow)")
    return r.stdout.strip()


def find_manifests(repo, base, head, explicit, manifest_dir):
    paths = [Path(p) for p in explicit]
    if not explicit:
        for status, path, _ in changed_files(repo, base, head):
            if status in ("A", "M", "R") and path.startswith(manifest_dir.rstrip("/") + "/") and path.endswith(".manifest.yaml"):
                paths.append(Path(repo) / path)
    return paths


def slice_ids(path):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(data, dict) and "slices" in data:
        return [s.get("slice") for s in data["slices"]]
    return [None]


def diff_adr_triggers(repo, base, head):
    why = []
    for status, path, old in changed_files(repo, base, head):
        if status == "D":
            continue
        new = declared_types(path, file_at(repo, head, path))
        before = declared_types(old or path, file_at(repo, base, old or path)) if status != "A" else {}
        added = [n for n, k in new.items() if k == "interface" and before.get(n) != "interface"]
        if added:
            why.append(f"new interface {', '.join(added)} in {path}")
        if path.lower().endswith(".csproj"):
            old_text = file_at(repo, base, old or path) if status != "A" else ""
            if len(PROJECT_REF.findall(file_at(repo, head, path))) > len(PROJECT_REF.findall(old_text)):
                why.append(f"new ProjectReference in {path}")
    return why


def diff_adr_check(repo, base, head, cfg):
    why = diff_adr_triggers(repo, base, head)
    if not why:
        return [], why
    if EXEMPT.search(git(repo, "log", "--format=%B", f"{base}..{head}").stdout):
        return [], why
    paths = cfg.get("paths") or adr_gate.DEFAULT_PATHS
    candidates = [p for s, p, _ in changed_files(repo, base, head) if s in ("A", "M", "R") and matches(p, paths)]
    if not candidates:
        return [offender("adr-missing", "-", f"architectural change ({'; '.join(why[:3])}) without an ADR in the diff",
                         f"add an ADR under {paths[0]} with Context, Decision, Alternatives, or put `adr-exempt: <reason>` in a commit body")], why
    incomplete = []
    for p in candidates:
        found = adr_gate.sections(file_at(repo, head, p))
        missing = [k for k in adr_gate.SECTIONS if not found.get(k)]
        if not missing:
            return [], why
        incomplete.append((p, missing))
    p, missing = incomplete[0]
    return [offender("adr-incomplete", p, f"empty or missing section(s): {', '.join(missing)}", f"fill {', '.join(missing)} in {p}")], why


def run_gates(repo, base, head, full, gates, manifests, run_tests):
    results = {}
    test_paths = (full.get("plan_conformance") or {}).get("test_paths") or DEFAULT_TEST_PATHS
    loaded = [(m, sid, load_manifest(m, sid)) for m in manifests for sid in slice_ids(m)]
    if "tidy-first" in gates:
        cfg = full.get("tidy_first") or {}
        if cfg.get("enabled") is False:
            results["tidy-first"] = {"passed": True, "applicable": False, "offenders": []}
        else:
            structural = any(s.get("structural") for _, _, s in loaded)
            offenders, info = tidy_first.check(repo, base, head, cfg, test_paths, structural)
            results["tidy-first"] = {"passed": not offenders, "applicable": True, "offenders": offenders, **info}
    if "adr" in gates:
        cfg = full.get("adr") or {}
        if cfg.get("enabled") is False or cfg.get("required") is False:
            results["adr"] = {"passed": True, "applicable": False, "offenders": []}
        else:
            offenders, why = [], []
            if loaded:
                for _, _, s in loaded:
                    o, w = adr_gate.check(s, repo, head, cfg)
                    offenders += o
                    why += w
            else:
                offenders, why = diff_adr_check(repo, base, head, cfg)
            results["adr"] = {"passed": not offenders, "applicable": bool(why), "offenders": offenders, "triggers": why,
                              "source": "manifest" if loaded else "diff"}
    if "bugfix" in gates:
        cfg = full.get("bugfix") or {}
        fixes = [s for _, _, s in loaded if s.get("kind") == "bugfix"]
        if not fixes or cfg.get("enabled") is False:
            results["bugfix"] = {"passed": True, "applicable": False, "offenders": []}
        else:
            offenders, warnings = [], []
            for s in fixes:
                o, _ = bugfix_gates.check(s, repo, base, head, cfg, test_paths)
                if run_tests:
                    more, info = bugfix_gates.run_tests(s, repo, base, head, cfg)
                    o += more
                    warnings += info.get("warnings") or []
                offenders += [{**x, "detail": f"[{s.get('slice')}] {x['detail']}"} for x in o]
            results["bugfix"] = {"passed": not offenders, "applicable": True, "offenders": offenders, "slices": len(fixes)}
            if warnings:
                results["bugfix"]["warnings"] = warnings
    return results


def annotate(results, style):
    for gate, r in results.items():
        for o in r["offenders"]:
            text = f"{gate}/{o['rule']}: {o['detail']} -> {o['fix']}"
            if style == "github":
                loc = f"file={o['path']}," if o.get("path") not in (None, "-") else ""
                print(f"::error {loc}title=bob {gate}::{text}", file=sys.stderr)
            else:
                print(f"FAIL {o['path']}: {text}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--config")
    ap.add_argument("--gates", default=",".join(GATES))
    ap.add_argument("--manifest", action="append", default=[])
    ap.add_argument("--manifest-dir", default=".bob/features")
    ap.add_argument("--run-tests", action="store_true")
    ap.add_argument("--warn-only", action="store_true")
    ap.add_argument("--annotations", choices=["plain", "github"], default="plain")
    ap.add_argument("--report")
    args = ap.parse_args()
    try:
        gates = [g.strip() for g in args.gates.split(",") if g.strip()]
        unknown = [g for g in gates if g not in GATES]
        if unknown:
            raise SystemExit(f"unknown gate(s): {', '.join(unknown)}; known: {', '.join(GATES)}")
        config = args.config or str(Path(args.repo) / ".claude" / "bob-pipeline.yaml")
        full = yaml.safe_load(Path(config).read_text(encoding="utf-8-sig")) or {} if Path(config).is_file() else {}
        base = resolve_base(args.repo, args.base, args.head)
        manifests = find_manifests(args.repo, base, args.head, args.manifest, args.manifest_dir)
        results = run_gates(args.repo, base, args.head, full, gates, manifests, args.run_tests)
    except SystemExit as e:
        print(e, file=sys.stderr)
        sys.exit(2)
    passed = all(r["passed"] for r in results.values())
    report = {"passed": passed, "base": base, "head": args.head, "warn_only": args.warn_only,
              "manifests": [str(m) for m in manifests], "gates": results}
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    json.dump(report, sys.stdout, indent=2)
    print()
    annotate(results, args.annotations)
    sys.exit(0 if passed or args.warn_only else 1)


if __name__ == "__main__":
    main()
