#!/usr/bin/env python3
"""PR description from the slice manifest (1.9.0, E3 + E4): what changed and why each new type exists.

Usage:
    python scripts/pr_description.py --manifest <manifest.yaml> [--slice <id>] [--out <pr-body.md>] [--config <bob-pipeline.yaml>] [--report <out.json>]

E3  renders a Markdown section per slice: module, kind, paths, new types with their purpose, new module edges,
    ADR, and for a bugfix the root cause and regression test.
E4  every `new_types[].purpose` must be a non-empty sentence when `pr_description.require_purpose` is not false:
    offender `missing-purpose` (fix: the Specifier adds the purpose to the manifest).

Output (stdout): {"passed", "offenders", "markdown"}. Exit 0 = pass, 1 = offenders, 2 = usage/manifest error.
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

from plan_conformance import offender


def render(slices):
    lines = ["## Changes by slice", ""]
    for s in slices:
        lines.append(f"### {s['slice']} - {s.get('feature_module', '')} ({s.get('kind', 'feature')})")
        if s.get("kind") == "bugfix":
            lines.append(f"- Root cause: `{s.get('root_cause', '?')}`")
            reg = s.get("regression_test") or []
            lines.append("- Regression test: " + (", ".join(f"`{r}`" for r in reg) if reg else f"exempt ({s.get('test_exempt', 'no reason')})"))
        lines.append("- Paths: " + ", ".join(f"`{p}`" for p in s.get("allowed_paths") or []))
        types = s.get("new_types") or []
        if types:
            lines += ["", "| New type | Kind | Module | Purpose |", "|---|---|---|---|"]
            lines += [f"| `{t['name']}` | {t['kind']} | {t['module']} | {t.get('purpose') or '**missing**'} |" for t in types]
            lines.append("")
        else:
            lines.append("- No new types")
        if s.get("allowed_new_edges"):
            lines.append("- New module edges: " + ", ".join(f"`{e}`" for e in s["allowed_new_edges"]))
        if s.get("adr"):
            lines.append(f"- ADR: `{s['adr']}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def check(slices, require_purpose=True):
    offenders = []
    if require_purpose:
        for s in slices:
            for t in s.get("new_types") or []:
                if len((t.get("purpose") or "").strip()) < 10:
                    offenders.append(offender("missing-purpose", f"{s['slice']}:{t['name']}", "new type has no purpose sentence",
                                              f"return send-back so the Specifier adds a purpose for {t['name']} to new_types"))
    return offenders


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--slice")
    ap.add_argument("--out")
    ap.add_argument("--config")
    ap.add_argument("--report")
    args = ap.parse_args()
    try:
        data = yaml.safe_load(Path(args.manifest).read_text(encoding="utf-8-sig"))
        slices = data["slices"] if isinstance(data, dict) and "slices" in data else [data]
        if args.slice:
            slices = [s for s in slices if isinstance(s, dict) and s.get("slice") == args.slice]
        if not slices or not all(isinstance(s, dict) and "slice" in s for s in slices):
            raise SystemExit("manifest must be a slice mapping or have a `slices` list")
    except (SystemExit, OSError, yaml.YAMLError) as e:
        print(e, file=sys.stderr)
        sys.exit(2)
    full = (yaml.safe_load(Path(args.config).read_text(encoding="utf-8-sig")) or {}) if args.config else {}
    cfg = full.get("pr_description") or {}
    offenders = check(slices, cfg.get("require_purpose", True) and cfg.get("enabled", True))
    md = render(slices)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
    report = {"passed": not offenders, "offenders": offenders, "markdown": md}
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    json.dump(report, sys.stdout, indent=2)
    print()
    sys.exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
