#!/usr/bin/env python3
"""Hunk ablation for a bugfix slice (1.9.0, K6): every substantive production hunk must be necessary.

Usage:
    python scripts/bugfix_ablation.py --manifest <manifest.yaml> --repo <worktree> --base <ref> \
        [--slice <id>] [--head HEAD] [--config <bob-pipeline.yaml>] [--report <out.json>]

For each production hunk (comments / using / imports excluded) of <base>..<head>: a temporary worktree at <head>,
the hunk reverse-applied, `bugfix.test_command` run. Tests still green = the hunk is not needed for the fix:
offender `unnecessary-hunk`. `bugfix.ablation`: off | warn (default; offenders go to `warnings`, gate passes) | hard.
A slice with `allow: [refactor]` is skipped. Exit 0 = pass, 1 = offenders (hard), 2 = usage/manifest error.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from bugfix_gates import regression_command
from diffkit import DEFAULT_TEST_PATHS, changed_files, git, hunks, is_test, offender, run, substantive
from plan_conformance import load_manifest

MAX_HUNKS = 12


def ablate(manifest, repo, base, head, cfg, test_paths):
    cmd = regression_command(manifest, repo, base, head, cfg)
    if not cmd:
        return [], "no bugfix.test_command / regression_test"
    found = []
    for status, path, _ in changed_files(repo, base, head):
        if status != "D" and not is_test(path, test_paths):
            found += [(path, h) for h in hunks(repo, base, head, path) if substantive(h["added"] + h["removed"])]
    if len(found) > MAX_HUNKS:
        return [], f"{len(found)} hunks exceed the ablation cap of {MAX_HUNKS}: the fix is too scattered (see the budget rule)"
    tmp = Path(tempfile.mkdtemp(prefix="bob-k6-"))
    wt = tmp / "wt"
    offenders = []
    try:
        git(repo, "worktree", "add", "--detach", str(wt), head)
        for path, h in found:
            patch = tmp / "h.patch"
            patch.write_text(h["patch"], encoding="utf-8", newline="\n")
            ok = subprocess.run(["git", "-C", str(wt), "apply", "-R", "--unidiff-zero", "--whitespace=nowarn", str(patch)], capture_output=True)
            if ok.returncode != 0:
                continue
            if run(cmd, wt) == 0:
                offenders.append(offender("unnecessary-hunk", f"{path}:{h['new_start']}", "regression test stays green without this hunk",
                                          f"drop the hunk at {path}:{h['new_start']} or split it into a separate tidy commit"))
            git(wt, "checkout", "--", ".")
    finally:
        git(repo, "worktree", "remove", "--force", str(wt), check=False)
        shutil.rmtree(tmp, ignore_errors=True)
    return offenders, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--slice")
    ap.add_argument("--config")
    ap.add_argument("--report")
    args = ap.parse_args()
    try:
        manifest = load_manifest(args.manifest, args.slice)
        full = (yaml.safe_load(Path(args.config).read_text(encoding="utf-8-sig")) or {}) if args.config else {}
        cfg = full.get("bugfix") or {}
        test_paths = (full.get("plan_conformance") or {}).get("test_paths") or DEFAULT_TEST_PATHS
        mode = cfg.get("ablation", "warn")
        report = {"passed": True, "applicable": False, "slice": manifest.get("slice"), "offenders": [], "warnings": [], "mode": mode}
        if manifest.get("kind") == "bugfix" and mode != "off" and "refactor" not in (manifest.get("allow") or []):
            offenders, skipped = ablate(manifest, args.repo, args.base, args.head, cfg, test_paths)
            report["applicable"] = skipped is None
            if skipped:
                report["skipped"] = skipped
            if mode == "hard":
                report["offenders"] = offenders
            else:
                report["warnings"] = offenders
            report["passed"] = not report["offenders"]
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
