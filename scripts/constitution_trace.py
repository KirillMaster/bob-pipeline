#!/usr/bin/env python3
"""Constitution traceability gate input (design D20/D21), merge gate only.

Usage:
    python scripts/constitution_trace.py --constitution .specify/memory/constitution.yaml \
        [--green-tests <file with one passing test name per line>]

Every NON-NEGOTIABLE principle must have a non-empty `gate_condition`; when it also lists
`verified_by` entries (optional field), each entry must appear (substring) in the green-tests list.
No constitution file -> no-op (metric 0).

Output (stdout): {"category": "constitution-traceability", "metric": "untraced_principles",
"metric_value": <n>, "details": [{"id", "reason"}]}. Exit 0 always; 2 on usage errors.
"""
import argparse
import json
import sys
from pathlib import Path

import yaml


def trace(constitution, green_tests):
    details = []
    for p in (constitution or {}).get("principles", []):
        if p.get("severity") != "NON-NEGOTIABLE":
            continue
        pid = p.get("id", "?")
        if not str(p.get("gate_condition") or "").strip():
            details.append({"id": pid, "reason": "no gate_condition"})
            continue
        entries = p.get("verified_by") or []
        if isinstance(entries, str):
            entries = [entries]
        missing = [e for e in entries if not any(e in t for t in green_tests)]
        if missing:
            details.append({"id": pid, "reason": "verified_by not green: " + ", ".join(missing)})
    return {"category": "constitution-traceability", "metric": "untraced_principles",
            "metric_value": len(details), "details": details}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--constitution", required=True)
    ap.add_argument("--green-tests")
    args = ap.parse_args()
    path = Path(args.constitution)
    if not path.exists():
        out = {"category": "constitution-traceability", "metric": "untraced_principles",
               "metric_value": 0, "details": [], "note": "no constitution — no-op"}
    else:
        green = []
        if args.green_tests and Path(args.green_tests).exists():
            green = Path(args.green_tests).read_text(encoding="utf-8-sig").splitlines()
        out = trace(yaml.safe_load(path.read_text(encoding="utf-8-sig")), green)
    json.dump(out, sys.stdout)
    print()


if __name__ == "__main__":
    main()
