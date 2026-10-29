#!/usr/bin/env python3
"""Plan-conformance gate: does the coder's diff stay inside the specifier's slice manifest?

Usage:
    python scripts/plan_conformance.py --manifest <manifest.yaml> --repo <worktree> --base <ref> \
        [--slice <id>] [--head HEAD] [--config <bob-pipeline.yaml>] [--report <out.json>]

Inputs:
    manifest   slice manifest (schemas/slice-manifest.schema.json); a file with a `slices` list needs --slice
    git diff   <base>..<head> in --repo (the slice worktree)
    config     optional; reads `plan_conformance` {enabled, protected_paths, module_paths, edge_check_command}

Rules (each offender carries a one-line actionable `fix`):
    protected          baselines, bob config/agents/state, config `protected_paths` touched
    locked-test        a file matching `locked_tests` added/modified/deleted/renamed
    out-of-scope       a changed file outside `allowed_paths`
    undeclared-type    new top-level production type (files under `test_paths` are exempt) (C# class/record/interface/struct/enum, TS class/interface/type/enum,
                       Python class) missing from `new_types`, or declared with another kind
    module-mismatch    declared type lives in a file outside its module's `module_paths` globs
    edge-check         `edge_check_command` exited non-zero

Output (stdout): {"passed", "slice", "offenders": [{"rule", "path", "detail", "fix"}], "allowed_new_edges", "files"}
Exit 0 = pass, 1 = offenders, 2 = usage/manifest error.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BUILTIN_PROTECTED = [
    ".bob/**",
    ".claude/bob-pipeline.yaml*",
    ".claude/agents/bob/**",
    "**/*baseline*.json",
]
DEFAULT_TEST_PATHS = ["**/tests/**", "**/test/**", "**/__tests__/**", "**/*Tests/**", "**/*.Tests/**",
                      "**/*Tests.cs", "**/*Test.cs", "**/*.test.*", "**/*.spec.*", "**/test_*.py", "**/*_test.py"]
EDGE_CHECK_TIMEOUT = 900

CS_TYPE = re.compile(r"^(?P<indent>[ \t]*)(?:(?:public|internal|private|protected|static|abstract|sealed|partial|readonly|unsafe|file|new)\s+)*"
                     r"(?P<kind>record\s+struct|record\s+class|record|class|interface|struct|enum)\s+(?P<name>[A-Za-z_]\w*)")
TS_TYPE = re.compile(r"^(?P<indent>)(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:const\s+)?"
                     r"(?P<kind>class|interface|type|enum)\s+(?P<name>[A-Za-z_$][\w$]*)")
PY_TYPE = re.compile(r"^(?P<indent>)(?P<kind>class)\s+(?P<name>[A-Za-z_]\w*)")
CS_BLOCK_NS = re.compile(r"^\s*namespace\s+[\w.]+\s*(//.*)?$", re.M)


def glob_regex(pattern):
    p = pattern.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    if p.endswith("/"):
        p += "**"
    out, i = "", 0
    while i < len(p):
        if p.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif p.startswith("**", i):
            out += ".*"
            i += 2
        elif p[i] == "*":
            out += "[^/]*"
            i += 1
        elif p[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(p[i])
            i += 1
    return re.compile("^" + out + "$")


def matches(path, patterns):
    return any(glob_regex(g).match(path) for g in patterns or [])


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def changed_files(repo, base, head):
    """[(status, path, old_path)] with status in A/M/D/R."""
    out = git(repo, "diff", "--name-status", "-z", "-M", f"{base}..{head}").stdout
    tokens = out.split("\0")
    files, i = [], 0
    while i < len(tokens) and tokens[i]:
        status = tokens[i][0]
        if status in ("R", "C"):
            files.append(("R" if status == "R" else "A", tokens[i + 2], tokens[i + 1]))
            i += 3
        else:
            files.append((status, tokens[i + 1], None))
            i += 2
    return files


def file_at(repo, ref, path):
    r = git(repo, "show", f"{ref}:{path}", check=False)
    return r.stdout if r.returncode == 0 else ""


def normalize_kind(kind):
    kind = re.sub(r"\s+", " ", kind)
    return "record" if kind.startswith("record") else kind


def declared_types(path, text):
    """{name: kind} of top-level types in a source file (by extension); {} for other files."""
    suffix = Path(path).suffix.lower()
    if suffix == ".cs":
        rx = CS_TYPE
        ns_indent = 4 if CS_BLOCK_NS.search(text) else 0
    elif suffix in (".ts", ".tsx", ".mts", ".cts"):
        rx, ns_indent = TS_TYPE, 0
    elif suffix == ".py":
        rx, ns_indent = PY_TYPE, 0
    else:
        return {}
    found = {}
    for line in text.splitlines():
        m = rx.match(line)
        if not m:
            continue
        indent = len(m.group("indent").replace("\t", "    "))
        if indent > ns_indent:
            continue
        found[m.group("name")] = normalize_kind(m.group("kind"))
    return found


def offender(rule, path, detail, fix):
    return {"rule": rule, "path": path, "detail": detail, "fix": fix}


def check(manifest, repo, base, head, pc_config=None):
    pc = pc_config or {}
    protected = BUILTIN_PROTECTED + list(pc.get("protected_paths") or [])
    module_paths = pc.get("module_paths") or {}
    test_paths = pc.get("test_paths") or DEFAULT_TEST_PATHS
    allowed = manifest.get("allowed_paths") or []
    locked = manifest.get("locked_tests") or []
    declared = {t["name"]: t for t in manifest.get("new_types") or []}
    offenders, files = [], changed_files(repo, base, head)

    for status, path, old in files:
        touched = [path] + ([old] if old else [])
        hit = next((p for p in touched if matches(p, protected)), None)
        if hit:
            offenders.append(offender("protected", hit, "protected file changed",
                                      f"revert {hit}; gates, baselines and config are not yours to change - report a blocker instead"))
            continue
        hit = next((p for p in touched if matches(p, locked)), None)
        if hit:
            offenders.append(offender("locked-test", hit, f"locked test changed ({status})",
                                      f"revert {hit}; fix the production code, not the locked test"))
            continue
        bad = next((p for p in touched if not matches(p, allowed)), None)
        if bad:
            offenders.append(offender("out-of-scope", bad, "changed file is outside allowed_paths",
                                      f"revert {bad} or return send-back so the Specifier adds it to allowed_paths"))
            continue
        if status == "D" or matches(path, test_paths):
            continue  # test classes are covered by allowed_paths; new_types lists production types
        new = declared_types(path, file_at(repo, head, path))
        if not new:
            continue
        old_types = declared_types(old or path, file_at(repo, base, old or path))
        for name, kind in new.items():
            if name in old_types:
                continue
            spec = declared.get(name)
            if spec is None:
                offenders.append(offender("undeclared-type", path, f"new {kind} {name} is not in new_types",
                                          f"remove {name} or return send-back so the Specifier declares it in new_types"))
                continue
            if spec.get("kind") and normalize_kind(spec["kind"]) != kind:
                offenders.append(offender("undeclared-type", path, f"{name} declared as {spec['kind']} but is a {kind}",
                                          f"make {name} a {spec['kind']} as planned"))
            globs = module_paths.get(spec.get("module"))
            if globs and not matches(path, globs):
                offenders.append(offender("module-mismatch", path, f"{name} belongs to module {spec['module']}, file is outside its paths",
                                          f"move {name} into a path of module {spec['module']}: {', '.join(globs)}"))
    return offenders, [f[1] for f in files]


def run_edge_check(command, repo):
    try:
        r = subprocess.run(command, shell=True, cwd=str(repo), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=EDGE_CHECK_TIMEOUT)
    except subprocess.TimeoutExpired:
        return offender("edge-check", "-", f"edge_check_command timed out after {EDGE_CHECK_TIMEOUT}s",
                        "remove the new module dependency or return send-back")
    if r.returncode == 0:
        return None
    tail = " | ".join((r.stdout + r.stderr).strip().splitlines()[-5:])[:400]
    return offender("edge-check", "-", f"edge_check_command exited {r.returncode}: {tail}",
                    "remove the new module dependency, or return send-back so the Specifier declares it in allowed_new_edges")


def load_manifest(path, slice_id):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(data, dict) and "slices" in data:
        if not slice_id:
            raise SystemExit("manifest has several slices: pass --slice <id>")
        data = next((s for s in data["slices"] if s.get("slice") == slice_id), None)
        if data is None:
            raise SystemExit(f"slice '{slice_id}' not in manifest")
    if not isinstance(data, dict) or "allowed_paths" not in data:
        raise SystemExit("manifest must be a mapping with `allowed_paths`")
    try:
        import jsonschema
        schema = json.loads((PLUGIN_ROOT / "schemas" / "slice-manifest.schema.json").read_text(encoding="utf-8"))
        errors = [e.message for e in jsonschema.Draft202012Validator(schema["$defs"]["slice"]).iter_errors(data)]
        if errors:
            raise SystemExit("invalid manifest: " + "; ".join(errors[:5]))
    except ImportError:
        pass
    return data


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
    except SystemExit as e:
        print(e, file=sys.stderr)
        sys.exit(2)
    pc = {}
    if args.config:
        pc = (yaml.safe_load(Path(args.config).read_text(encoding="utf-8-sig")) or {}).get("plan_conformance") or {}
    try:
        offenders, files = check(manifest, args.repo, args.base, args.head, pc)
    except SystemExit as e:
        print(e, file=sys.stderr)
        sys.exit(2)
    if pc.get("edge_check_command"):
        bad = run_edge_check(pc["edge_check_command"], args.repo)
        if bad:
            offenders.append(bad)
    report = {"passed": not offenders, "slice": manifest.get("slice"), "offenders": offenders,
              "allowed_new_edges": manifest.get("allowed_new_edges") or [], "files": files}
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    json.dump(report, sys.stdout, indent=2)
    print()
    sys.exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
