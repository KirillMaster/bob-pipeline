#!/usr/bin/env python3
"""ADR required gate (1.9.0, G1): an architectural slice must bring a decision record.

Usage:
    python scripts/adr_gate.py --manifest <manifest.yaml> --repo <worktree> [--slice <id>] [--head HEAD] \
        [--config <bob-pipeline.yaml>] [--report <out.json>]

A slice is architectural when it declares a new `interface` type or a non-empty `allowed_new_edges`
(deterministic triggers from the manifest). It then needs `adr: <path>` (under `adr.paths`, default docs/adr/**,
docs/decisions/**) that exists at <head> with non-empty Context, Decision and Alternatives sections, or `adr_exempt: <reason>`.

Rules: adr-missing, adr-not-found, adr-bad-path, adr-incomplete. Exit 0 = pass, 1 = offenders, 2 = usage/manifest error.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from diffkit import git, matches, offender
from plan_conformance import load_manifest

DEFAULT_PATHS = ["docs/adr/**", "docs/decisions/**"]
SECTIONS = {"Context": r"context", "Decision": r"decision", "Alternatives": r"alternatives?(?:\s+considered)?"}


def triggers(manifest):
    out = []
    if any(t.get("kind") == "interface" for t in manifest.get("new_types") or []):
        out.append("new interface")
    if manifest.get("allowed_new_edges"):
        out.append("new module edge")
    return out


def sections(text):
    found, name = {}, None
    for line in text.splitlines():
        m = re.match(r"^#{1,6}\s*(.+?)\s*$", line)
        if m:
            name = next((k for k, rx in SECTIONS.items() if re.fullmatch(rx, m.group(1), re.I)), None)
            if name:
                found.setdefault(name, "")
        elif name:
            found[name] += line.strip()
    return found


def check(manifest, repo, head, cfg=None):
    cfg = cfg or {}
    why = triggers(manifest)
    if not why or manifest.get("adr_exempt"):
        return [], why
    paths = cfg.get("paths") or DEFAULT_PATHS
    adr = manifest.get("adr")
    if not adr:
        return [offender("adr-missing", "-", f"slice is architectural ({', '.join(why)}) but has no adr",
                         f"write an ADR under {paths[0]} with Context, Decision, Alternatives and set adr in the manifest, or set adr_exempt with a reason")], why
    if not matches(adr, paths):
        return [offender("adr-bad-path", adr, "adr is outside adr.paths", f"move the ADR under {paths[0]}")], why
    r = git(repo, "show", f"{head}:{adr}", check=False)
    if r.returncode != 0:
        return [offender("adr-not-found", adr, f"adr does not exist at {head}", f"commit {adr}")], why
    found = sections(r.stdout)
    missing = [k for k in SECTIONS if not found.get(k)]
    if missing:
        return [offender("adr-incomplete", adr, f"empty or missing section(s): {', '.join(missing)}",
                         f"fill {', '.join(missing)} in {adr}")], why
    return [], why


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--slice")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--config")
    ap.add_argument("--report")
    args = ap.parse_args()
    try:
        manifest = load_manifest(args.manifest, args.slice)
        full = (yaml.safe_load(Path(args.config).read_text(encoding="utf-8-sig")) or {}) if args.config else {}
        cfg = full.get("adr") or {}
        if cfg.get("enabled") is False or cfg.get("required") is False:
            report = {"passed": True, "applicable": False, "slice": manifest.get("slice"), "offenders": []}
        else:
            offenders, why = check(manifest, args.repo, args.head, cfg)
            report = {"passed": not offenders, "applicable": bool(why), "slice": manifest.get("slice"), "offenders": offenders, "triggers": why}
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
