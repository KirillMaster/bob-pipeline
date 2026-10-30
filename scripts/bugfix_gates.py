#!/usr/bin/env python3
"""KISS gates for a `kind: bugfix` slice (K1-K5, K7, K8 + optional K2/K3 test runs; PublicApi K4 since 1.10.0).

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
    complexity-delta      decision points in a changed production file grew by more than bugfix.max_complexity_delta (K8)
    nesting-delta         max indentation depth of a changed production file grew by more than bugfix.max_nesting_delta (K8)
    fix-not-needed        --run-tests: regression test still passes with root_cause files reverted to base (K3)
    regression-red        --run-tests: regression test fails on head
    green-on-base         --run-tests: regression test passes on the clean base with only the test files from head (K2)
    red-not-assertion     --run-tests: red on base is a compile error or a timeout, not an assertion/runtime failure; seam-required needs manifest seam (K2)
    new-public-api        added entry in PublicAPI.Unshipped.txt (Roslyn PublicApiAnalyzers RS0016 list) outside allow: new-api (K4)
Warnings (not offenders): frame-outside-diff = K3 failure output names no changed production file (K1 hint).

Exit 0 = pass (also when the slice is not a bugfix: applicable=false), 1 = offenders, 2 = usage/manifest error.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from diffkit import DEFAULT_TEST_PATHS, TRIVIAL, changed_files, exists_at, git, hunks, is_test, matches, offender, quote, run, substantive, test_edit_offenders
from plan_conformance import load_manifest

DEFAULTS = {"max_added_lines": 30, "max_files": 2, "runs": 3, "max_complexity_delta": 3, "max_nesting_delta": 1}
DECISION = re.compile(r"\b(?:if|elif|else\s+if|for|foreach|while|case|catch|except|when|and|or)\b|&&|\|\||\?\?|\?(?=[^?.\[])")
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


def measures(text):
    """(decision points, max indentation depth) of a source text: language-agnostic stand-in for cognitive complexity / nesting."""
    lines = [l for l in text.splitlines() if not TRIVIAL.match(l)]
    depth = 0
    for l in lines:
        indent = len(l) - len(l.lstrip(" 	"))
        depth = max(depth, l[:indent].count("	") + (l[:indent].count(" ") // 4))
    return sum(len(DECISION.findall(l)) for l in lines), depth


def delta_offenders(repo, base, head, files, budget, cfg):
    out = []
    max_cc = budget.get("max_complexity_delta", cfg["max_complexity_delta"])
    max_nest = budget.get("max_nesting_delta", cfg["max_nesting_delta"])
    for status, path, old in files:
        before = git(repo, "show", f"{base}:{old or path}", check=False).stdout if status in ("M", "R") else ""
        after = git(repo, "show", f"{head}:{path}", check=False).stdout
        (cc0, n0), (cc1, n1) = measures(before), measures(after)
        if cc1 - cc0 > max_cc:
            out.append(offender("complexity-delta", path, f"decision points {cc0} -> {cc1} (limit +{max_cc})",
                                "simplify the fix (no new branches) or return send-back so the Specifier sets budget.max_complexity_delta with a reason"))
        if n1 - n0 > max_nest:
            out.append(offender("nesting-delta", path, f"max nesting {n0} -> {n1} (limit +{max_nest})",
                                "use a guard clause instead of deeper nesting or return send-back so the Specifier sets budget.max_nesting_delta with a reason"))
    return out


def root_cause_files(manifest):
    rc = manifest.get("root_cause")
    return [rc.split("#")[0]] if rc else []


def public_api_offenders(repo, base, head, files):
    """K4 via Roslyn: PublicApiAnalyzers keep every public member in PublicAPI.Unshipped.txt; an added entry is a new/changed public signature."""
    out = []
    for status, path, _ in files:
        if status == "D" or Path(path).name != "PublicAPI.Unshipped.txt":
            continue
        for h in hunks(repo, base, head, path):
            removed = {l.strip() for l in h["removed"]}
            for line in h["added"]:
                entry = line.strip()
                if entry and not entry.startswith(("#", "*REMOVED*")) and entry not in removed:
                    out.append(offender("new-public-api", path, f"public API entry added: `{entry[:100]}`",
                                        "reuse an existing member or return send-back so the Specifier allows new-api"))
    return out


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
    if "new-api" not in allow:
        offenders += public_api_offenders(repo, base, head, files)
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
    offenders += delta_offenders(repo, base, head, [(s, p, o) for s, p, o in files if s != "D" and not is_test(p, test_paths)], budget, cfg)
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


COMPILE_ERROR = re.compile(r"\berror\s+(?:CS|MSB|NETSDK)\d+|Build FAILED|SyntaxError|ModuleNotFoundError|ImportError|NameError|cannot find symbol", re.I)


def run_capture(command, cwd, timeout=900):
    try:
        r = subprocess.run(command, shell=True, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, ""


def classify(code, output):
    """pass | timeout | compile | assertion"""
    if code == 0:
        return "pass"
    if code == 124:
        return "timeout"
    return "compile" if COMPILE_ERROR.search(output) else "assertion"


def run_all(cmd, cwd, runs):
    results = [run_capture(cmd, cwd) for _ in range(runs)]
    return [classify(c, o) for c, o in results], "\n".join(o for _, o in results)


def red_on_base(manifest, repo, base, head, cmd, runs, tmp):
    """K2: clean base + only the regression test files from head; must fail by assertion in every run."""
    wt = tmp / "base"
    git(repo, "worktree", "add", "--detach", str(wt), base)
    reg = manifest.get("regression_test") or []
    for path in git(repo, "ls-tree", "-r", "--name-only", "-z", head).stdout.split("\0"):
        if path and matches(path, reg):
            git(wt, "checkout", head, "--", path)
    kinds, _ = run_all(cmd, wt, runs)
    if "pass" in kinds:
        return [offender("green-on-base", "-", "regression test passes on the clean base", "the test does not reproduce the bug; return send-back so the Specifier writes a red test")]
    if "timeout" in kinds or ("compile" in kinds and not manifest.get("seam")):
        return [offender("red-not-assertion", "-", f"red on base is {'a timeout' if 'timeout' in kinds else 'a compile error'}, not an assertion failure",
                         "the Specifier must commit a seam stub (manifest seam) so the test compiles and fails by assertion")]
    return []


def run_tests(manifest, repo, base, head, cfg):
    cmd = regression_command(manifest, repo, base, head, cfg)
    if not cmd:
        return [], {"skipped": "no bugfix.test_command / regression_test, or test_exempt"}
    runs = int({**DEFAULTS, **(cfg or {})}["runs"])
    if any(run(cmd, repo) != 0 for _ in range(runs)):
        return [offender("regression-red", "-", f"regression test fails on head (of {runs} runs)", "make the fix pass the regression test")], {"command": cmd}
    tmp = Path(tempfile.mkdtemp(prefix="bob-k3-"))
    wt = tmp / "wt"
    offenders, info = [], {"command": cmd}
    try:
        offenders += red_on_base(manifest, repo, base, head, cmd, runs, tmp)
        git(repo, "worktree", "add", "--detach", str(wt), head)
        for p in root_cause_files(manifest):
            if exists_at(repo, base, p):
                git(wt, "checkout", base, "--", p)
        kinds, output = run_all(cmd, wt, runs)
        if "pass" in kinds:
            offenders.append(offender("fix-not-needed", "-", "regression test passes with root_cause files reverted to base",
                                      "the test does not capture the bug or the diff is not the fix; return send-back"))
        elif "compile" in kinds or "timeout" in kinds:
            info["k3"] = "skipped: revert does not compile or times out (seam case), red on clean base checked by K2"
        else:
            names = {Path(p).name for _, p, _ in changed_files(repo, base, head) if not is_test(p, DEFAULT_TEST_PATHS)}
            if names and not any(n in output for n in names):
                info["warnings"] = [offender("frame-outside-diff", "-", "failure output names no changed production file", "check that root_cause is the file that fails (K1)")]
    finally:
        git(repo, "worktree", "remove", "--force", str(wt), check=False)
        git(repo, "worktree", "remove", "--force", str(tmp / "base"), check=False)
        shutil.rmtree(tmp, ignore_errors=True)
    return offenders, info


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
            if info.get("warnings"):
                report["warnings"] = info.pop("warnings")
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
