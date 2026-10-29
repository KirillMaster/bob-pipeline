#!/usr/bin/env python3
"""Tidy First gate (1.9.0, E1 + Z16): structural and behavioural changes live in separate commits.

Usage:
    python scripts/tidy_first.py --repo <worktree> --base <ref> [--head HEAD] [--config <bob-pipeline.yaml>] \
        [--manifest <manifest.yaml> --slice <id>] [--report <out.json>]

A commit is structural when its subject starts with one of `tidy_first.structural_prefixes`
(default tidy, refactor, structural, style, format; optional `(scope)`, then `:`). With a manifest slice
`structural: true` every commit of <base>..<head> is checked as structural.

Rules for a structural commit (offenders carry a one-line `fix`):
    structural-edits-assertion   existing test assertion/literal removed or changed, test file deleted (Z16)
    structural-adds-test         adds a test method: that is behaviour, commit it separately without the tidy prefix

Exit 0 = pass, 1 = offenders, 2 = usage/manifest error.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from diffkit import DEFAULT_TEST_PATHS, TEST_METHOD, changed_files, git, hunks, is_test, offender, test_edit_offenders
from plan_conformance import load_manifest

DEFAULT_PREFIXES = ["tidy", "refactor", "structural", "style", "format"]


def is_structural(subject, prefixes):
    return re.match(r"^(?:%s)(?:\([^)]*\))?!?:" % "|".join(re.escape(p) for p in prefixes), subject, re.I) is not None


def check_commit(repo, sha, test_paths):
    out = []
    for o in test_edit_offenders(repo, f"{sha}~1", sha, test_paths, "structural-edits-assertion",
                                 "a structural commit must not change what the tests assert; move the change to a behavioural commit"):
        out.append({**o, "detail": f"{sha[:8]}: {o['detail']}"})
    for status, path, _ in changed_files(repo, f"{sha}~1", sha):
        if status in ("A", "M") and is_test(path, test_paths):
            if any(TEST_METHOD.search(l) for h in hunks(repo, f"{sha}~1", sha, path) for l in h["added"]):
                out.append(offender("structural-adds-test", path, f"{sha[:8]}: structural commit adds a test method",
                                    "commit new tests in a behavioural commit without the tidy/refactor prefix"))
    return out


def check(repo, base, head, cfg=None, test_paths=None, all_structural=False):
    prefixes = (cfg or {}).get("structural_prefixes") or DEFAULT_PREFIXES
    test_paths = test_paths or DEFAULT_TEST_PATHS
    shas = git(repo, "rev-list", "--reverse", "--no-merges", f"{base}..{head}").stdout.split()
    offenders, structural = [], []
    for sha in shas:
        subject = git(repo, "log", "-1", "--format=%s", sha).stdout.strip()
        if all_structural or is_structural(subject, prefixes):
            structural.append(sha)
            offenders += check_commit(repo, sha, test_paths)
    return offenders, {"commits": len(shas), "structural": len(structural)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--config")
    ap.add_argument("--manifest")
    ap.add_argument("--slice")
    ap.add_argument("--report")
    args = ap.parse_args()
    try:
        full = (yaml.safe_load(Path(args.config).read_text(encoding="utf-8-sig")) or {}) if args.config else {}
        cfg = full.get("tidy_first") or {}
        test_paths = (full.get("plan_conformance") or {}).get("test_paths") or DEFAULT_TEST_PATHS
        manifest = load_manifest(args.manifest, args.slice) if args.manifest else {}
        if cfg.get("enabled") is False:
            report = {"passed": True, "applicable": False, "offenders": []}
        else:
            offenders, info = check(args.repo, args.base, args.head, cfg, test_paths, bool(manifest.get("structural")))
            report = {"passed": not offenders, "applicable": True, "offenders": offenders, **info}
    except SystemExit as e:
        print(e, file=sys.stderr)
        sys.exit(2)
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    json.dump(report, sys.stdout, indent=2)
    print()
    sys.exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
