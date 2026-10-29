#!/usr/bin/env python3
"""KISS gates for a `kind: bugfix` slice (1.9.0, K1-K5, K7, K8 + optional K2/K3 test runs).

Usage:
    python scripts/bugfix_gates.py --manifest <manifest.yaml> --repo <worktree> --base <ref> \
        [--slice <id>] [--head HEAD] [--config <bob-pipeline.yaml>] [--run-tests] [--report <out.json>]

Slice manifest fields (schemas/slice-manifest.schema.json): kind: bugfix, root_cause (path[#method]),
regression_test (globs, also in locked_tests, committed by the Specifier before the fix), test_exempt (reason),
budget {max_added_lines, max_files, reason}, allow [new-api, test-edit, marker, refactor].

Rules (offenders carry a one-line `fix`):
    missing-root-cause    bugfix slice without root_cause
    missing-regression    no regression_test and no test_exempt, or the test is not locked / absent at base (K2)
    root-cause-untouched  no changed production file is a root_cause file (K1)
    new-type              new_types is not empty without allow: new-api (K4)
    new-signature         added public/internal member or top-level def outside allow: new-api (K4)
    test-edited           existing test assertion/literal removed or changed, test file deleted (K5)
    temp-marker           TODO/FIXME/HACK/temporary/workaround/for now/pragma disable/SuppressMessage/[Obsolete] added (K7)
    budget                added production lines or files above bugfix.max_added_lines / max_files without budget.reason (K8)
    fix-not-needed        --run-tests: regression test still passes with root_cause files reverted to base (K3)
    regression-red        --run-tests: regression test fails on head (K2)

Exit 0 = pass (also when the slice is not a bugfix: applicable=false), 1 = offenders, 2 = usage/manifest error.
"""
import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

from diffkit import DEFAULT_TEST_PATHS, changed_files, exists_at, git, hunks, is_test, matches, offender, quote, run, substantive, test_edit_offenders
from plan_conformance import load_manifest

DEFAULTS = {"max_added_lines": 30, "max_files": 2, "runs": 3}
MARKER = re.compile(r"\b(?:TODO|FIXME|HACK|XXX)\b|temporary|workaround|for now|remove after|#pragma warning disable|SuppressMessage|"
                    r"\[Obsolete\b(?!.*[A-Z]{2,}-\d+)", re.I)
CS_MEMBER = re.compile(r"^\s*(?:public|internal)\s+(?:(?:static|virtual|override|abstract|sealed|async|new|partial|extern)\s+)*"
                       r"(?!class\b|record\b|interface\b|struct\b|enum\b)[\w<>\[\],.?() ]+?\s+\w+\s*(?:<[^>]*>)?\s*\(")
PY_DEF = re.compile(r"^def\s+[A-Za-z]\w*\s*\(")
SIG = re.compile(r"(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)")
TEST_NAME = re.compile(r"\b(?:void|Task)\s+(\w+)\s*\(|\bdef\s+(test_\w+)")


def signature(line):
    m = SIG.search(line)
    return (m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()) if m else None


def root_cause_files(manifest):
    rc = manifest.get("root_cause")
    return [rc.split("#")[0]] if rc else []


def check(manifest, repo, base, head, cfg=None, test_paths=None):
    cfg = {**DEFAULTS, **(cfg or {})}
    test_paths = test_paths or DEFAULT_TEST_PATHS
    allow = set(manifest.get("allow") or [])
    offenders = []
    files = changed_files(repo, base, head)
    prod = [(s, p) for s, p, _ in files if s != "D" and not is_test(p, test_paths)]

    rc = root_cause_files(manifest)
    if not rc:
        offenders.append(offender("missing-root-cause", "-", "bugfix slice has no root_cause",
                                  "return send-back so the Specifier names the root cause as path[#method]"))
    reg = manifest.get("regression_test") or []
    if not reg and not manifest.get("test_exempt"):
        offenders.append(offender("missing-regression", "-", "no regression_test and no test_exempt",
                                  "return send-back so the Specifier commits a red regression test first, or sets test_exempt with a reason"))
    for g in reg:
        if g not in (manifest.get("locked_tests") or []) and not matches(g, manifest.get("locked_tests") or []):
            offenders.append(offender("missing-regression", g, "regression_test is not in locked_tests", "lock the regression test in the manifest"))
        elif "*" not in g and not exists_at(repo, base, g):
            offenders.append(offender("missing-regression", g, "regression test is absent at base", "the Specifier must commit the red test before the Coder starts"))
    if rc and not any(p in rc for _, p in prod):
        offenders.append(offender("root-cause-untouched", rc[0], "no production file in the diff is a root_cause file",
                                  f"fix the defect in {rc[0]} or return send-back if the root cause was named wrongly"))
    if manifest.get("new_types") and "new-api" not in allow:
        offenders.append(offender("new-type", "-", "a bugfix declares new_types", "reuse an existing type; a new type needs allow: new-api from the Specifier"))

    added_total = 0
    for _, path in prod:
        suffix = Path(path).suffix.lower()
        for h in hunks(repo, base, head, path):
            added = substantive(h["added"])
            kept = {signature(l) for l in h["removed"]}
            added_total += len(added)
            for line in added:
                if "marker" not in allow and MARKER.search(line):
                    offenders.append(offender("temp-marker", path, f"temporary marker added: `{line.strip()[:80]}`",
                                              "fix the cause instead of marking a workaround; remove the marker"))
                if "new-api" not in allow and ((suffix == ".cs" and CS_MEMBER.match(line)) or (suffix == ".py" and PY_DEF.match(line))) and signature(line) not in kept:
                    offenders.append(offender("new-signature", path, f"new public member: `{line.strip()[:80]}`",
                                              "reuse an existing member or return send-back so the Specifier allows new-api"))
    if "test-edit" not in allow:
        offenders += test_edit_offenders(repo, base, head, test_paths, "test-edited", "do not weaken existing tests, add a new test instead")

    budget = manifest.get("budget") or {}
    max_lines = budget.get("max_added_lines", cfg["max_added_lines"])
    max_files = budget.get("max_files", cfg["max_files"])
    if budget and not budget.get("reason"):
        offenders.append(offender("budget", "-", "budget override without reason", "the Specifier must give budget.reason"))
    if added_total > max_lines or len(prod) > max_files:
        offenders.append(offender("budget", "-", f"{added_total} added production lines in {len(prod)} file(s); limit {max_lines} lines / {max_files} files",
                                  "shrink the fix to the root cause or return send-back so the Specifier sets budget with a reason"))
    return offenders, [p for _, p in prod]


def regression_names(repo, head, reg):
    """Test method names declared in the regression test files at head (the Specifier commits them before the Coder)."""
    names = []
    for path in git(repo, "ls-tree", "-r", "--name-only", "-z", head).stdout.split("\0"):
        if path and matches(path, reg):
            for line in git(repo, "show", f"{head}:{path}", check=False).stdout.splitlines():
                m = TEST_NAME.search(line)
                if m:
                    names.append(m.group(1) or m.group(2))
    return sorted(set(names))


def regression_command(manifest, repo, base, head, cfg):
    cfg = {**DEFAULTS, **(cfg or {})}
    reg = manifest.get("regression_test") or []
    if not cfg.get("test_command") or not reg or manifest.get("test_exempt"):
        return None
    command = cfg["test_command"]
    if "{filter}" in command:
        names = regression_names(repo, head, reg)
        if not names:
            return None
        command = command.replace("{filter}", "|".join("FullyQualifiedName~" + n for n in names))
    return command.replace("{tests}", " ".join(quote(p) for p in reg))


def run_tests(manifest, repo, base, head, cfg):
    cmd = regression_command(manifest, repo, base, head, cfg)
    if not cmd:
        return [], {"skipped": "no bugfix.test_command / regression_test, or test_exempt"}
    runs = int({**DEFAULTS, **(cfg or {})}["runs"])
    if any(run(cmd, repo) != 0 for _ in range(runs)):
        return [offender("regression-red", "-", f"regression test fails on head (of {runs} runs)", "make the fix pass the regression test")], {"command": cmd}
    tmp = Path(tempfile.mkdtemp(prefix="bob-k3-"))
    wt = tmp / "wt"
    offenders = []
    try:
        git(repo, "worktree", "add", "--detach", str(wt), head)
        for p in root_cause_files(manifest):
            if exists_at(repo, base, p):
                git(wt, "checkout", base, "--", p)
        if any(run(cmd, wt) == 0 for _ in range(runs)):
            offenders.append(offender("fix-not-needed", "-", "regression test passes with root_cause files reverted to base",
                                      "the test does not capture the bug or the diff is not the fix; return send-back"))
    finally:
        git(repo, "worktree", "remove", "--force", str(wt), check=False)
        shutil.rmtree(tmp, ignore_errors=True)
    return offenders, {"command": cmd}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--slice")
    ap.add_argument("--config")
    ap.add_argument("--run-tests", action="store_true")
    ap.add_argument("--report")
    args = ap.parse_args()
    try:
        manifest = load_manifest(args.manifest, args.slice)
        full = (yaml.safe_load(Path(args.config).read_text(encoding="utf-8-sig")) or {}) if args.config else {}
        cfg = full.get("bugfix") or {}
        test_paths = (full.get("plan_conformance") or {}).get("test_paths") or DEFAULT_TEST_PATHS
        if manifest.get("kind") != "bugfix" or cfg.get("enabled") is False:
            report = {"passed": True, "applicable": False, "slice": manifest.get("slice"), "offenders": []}
        else:
            offenders, files = check(manifest, args.repo, args.base, args.head, cfg, test_paths)
            info = {}
            if args.run_tests:
                more, info = run_tests(manifest, args.repo, args.base, args.head, cfg)
                offenders += more
            report = {"passed": not offenders, "applicable": True, "slice": manifest.get("slice"), "offenders": offenders, "files": files, "tests": info}
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
