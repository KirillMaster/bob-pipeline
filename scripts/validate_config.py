#!/usr/bin/env python3
"""Validate a bob-pipeline config (and optionally the tool registry).

Usage:
    python scripts/validate_config.py <config.yaml> [--schema schemas/bob-pipeline.schema.json]
    python scripts/validate_config.py --registry registry/tool-registry.yaml

Exit 0 on success; non-zero with JSON violations on stderr otherwise.
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
KNOWN_PARSERS = {"stryker", "mutmut", "pit", "cobertura", "lcov", "jacoco", "lizard", "jscpd",
                 "exitcode-lint", "exitcode-format", "exitcode-architecture", "diff-cover",
                 "constitution-trace"}  # constitution-trace is handled by scripts/constitution_trace.py
CATEGORIES = {"mutation", "coverage", "complexity", "duplication"}  # every stack must resolve these
QG_CATEGORIES = {"lint", "format", "architecture", "diff-coverage", "constitution-traceability"}  # optional, D20
NON_SKIPPABLE = {"specifier", "coder"}
DEPRECATED_ROLES = {"cleaner": "architect"}


def canon(name):
    return DEPRECATED_ROLES.get(name, name)


def warn(warnings):
    if warnings:
        json.dump({"warnings": warnings}, sys.stderr, indent=2)
        sys.stderr.write("\n")


def fail(violations):
    json.dump({"violations": violations}, sys.stderr, indent=2)
    sys.stderr.write("\n")
    sys.exit(1)


def validate_registry(path: Path) -> list:
    violations = []
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        return [{"path": str(path), "message": "registry must contain a non-empty 'entries' list"}]
    seen = set()
    for i, e in enumerate(entries):
        loc = f"entries[{i}]"
        for field in ("stack", "category", "tool", "run_command", "report_parser", "enabled"):
            if field not in e:
                violations.append({"path": loc, "message": f"missing field '{field}'"})
        if e.get("category") not in CATEGORIES | QG_CATEGORIES:
            violations.append({"path": loc, "message": f"unknown category '{e.get('category')}'"})
        if e.get("report_parser") not in KNOWN_PARSERS:
            violations.append({"path": loc, "message": f"report_parser '{e.get('report_parser')}' has no handler in scripts/parse_reports.py"})
        if e.get("category") == "mutation" and not e.get("scope_flag"):
            violations.append({"path": loc, "message": "mutation entry requires 'scope_flag' (slice-scoped mutation, design D5)"})
        key = (e.get("stack"), e.get("category"))
        if key in seen:
            violations.append({"path": loc, "message": f"duplicate entry for {key}"})
        seen.add(key)
    # every stack must resolve a full category set via its own entries + 'any' fallbacks
    stacks = {e["stack"] for e in entries if e.get("stack") and e["stack"] != "any"}
    any_cats = {e["category"] for e in entries if e.get("stack") == "any"}
    for stack in sorted(stacks):
        covered = {e["category"] for e in entries if e.get("stack") == stack} | any_cats
        for cat in sorted(CATEGORIES - covered):
            violations.append({"path": stack, "message": f"category '{cat}' unresolved (no stack entry and no 'any' fallback)"})
    return violations


def validate_config(config_path: Path, schema_path: Path, warnings=None) -> list:
    warnings = warnings if warnings is not None else []
    try:
        import jsonschema
    except ImportError:
        return [{"path": "environment", "message": "jsonschema package is required: pip install jsonschema pyyaml"}]

    config = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    violations = [
        {"path": "/".join(str(p) for p in err.absolute_path) or "<root>", "message": err.message}
        for err in jsonschema.Draft202012Validator(schema).iter_errors(config)
    ]
    if violations:
        return violations

    # cross-field rules the schema can't express
    raw_names = [r["name"] for r in config["roles"]]
    for n in raw_names:
        if n in DEPRECATED_ROLES:
            warnings.append({"path": f"roles/{n}", "message": f"role '{n}' is deprecated and treated as '{canon(n)}'"})
    role_names = [canon(n) for n in raw_names]
    for required in NON_SKIPPABLE:
        if required not in role_names:
            violations.append({"path": "roles", "message": f"role '{required}' is mandatory and missing"})
        elif not next(r for r in config["roles"] if canon(r["name"]) == required)["enabled"]:
            violations.append({"path": f"roles/{required}", "message": f"role '{required}' cannot be disabled"})
    if len(role_names) != len(set(role_names)):
        violations.append({"path": "roles", "message": "duplicate role names (cleaner counts as architect)"})
    for source, targets in config.get("send_back_routes", {}).items():
        targets = targets if isinstance(targets, list) else [targets]
        for name in [source, *targets]:
            if name in DEPRECATED_ROLES:
                warnings.append({"path": f"send_back_routes/{source}", "message": f"'{name}' is deprecated and treated as '{canon(name)}'"})
        for t in targets:
            if canon(t) not in role_names:
                violations.append({"path": f"send_back_routes/{source}", "message": f"target role '{t}' is not in roles"})
    tests = config.get("tests") or {}
    if tests.get("integration_at") and not tests.get("integration_command"):
        warnings.append({"path": "tests/integration_at", "message": "integration_at is set but integration_command is absent: no integration run happens"})
    enabled_cats = {t["category"] for t in config["tools"] if t["enabled"]}
    if "mutation" not in enabled_cats and (config.get("mutation") or {}).get("framework_enabled"):
        hardener = next((r for r in config["roles"] if r["name"] == "hardener"), None)
        if hardener and hardener["enabled"] and not hardener.get("degradation"):
            violations.append({"path": "roles/hardener", "message": "mutation category disabled but hardener has no 'degradation' behavior defined"})
    return violations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config", nargs="?", help="path to bob-pipeline.yaml")
    ap.add_argument("--schema", default=str(PLUGIN_ROOT / "schemas" / "bob-pipeline.schema.json"))
    ap.add_argument("--registry", help="validate a tool registry file instead of / in addition to the config")
    args = ap.parse_args()

    violations = []
    warnings = []
    if args.registry:
        violations += validate_registry(Path(args.registry))
    if args.config:
        violations += validate_config(Path(args.config), Path(args.schema), warnings)
    if not args.config and not args.registry:
        ap.error("provide a config path and/or --registry")
    warn(warnings)
    if violations:
        fail(violations)
    print("OK")


if __name__ == "__main__":
    main()
