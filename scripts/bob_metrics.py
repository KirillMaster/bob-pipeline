#!/usr/bin/env python3
"""Run instrumentation (design D19): append role runs / approval waits to .bob/metrics.jsonl and summarize.

Usage:
    python scripts/bob_metrics.py append --file <bob_root>/.bob/metrics.jsonl --kind role \
        --role coder --slice S1 --start <ISO> --end <ISO> --verdict pass [--send-back-reason <text>]
    python scripts/bob_metrics.py append --file ... --kind approval --what gherkin --start <ISO> --end <ISO>
    python scripts/bob_metrics.py summarize <metrics.jsonl>

Output: `append` echoes the written JSON line; `summarize` prints a JSON summary (per-role runs, wall
seconds, share of role time, send-backs, total approval wait, per-slice wall time). Exit 0 ok, 2 usage error.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_ts(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def seconds(start, end):
    return max(0.0, (parse_ts(end) - parse_ts(start)).total_seconds())


def build_record(kind, start, end, role=None, slice_id=None, verdict=None, send_back_reason=None, what=None):
    if kind == "role":
        if not (role and slice_id and verdict):
            raise ValueError("role record needs --role, --slice and --verdict")
        rec = {"kind": "role", "role": role, "slice": slice_id, "start": start, "end": end,
               "verdict": verdict, "send_back_reason": send_back_reason if verdict == "send-back" else None}
    elif kind == "approval":
        rec = {"kind": "approval", "what": what or "gherkin", "start": start, "end": end}
    else:
        raise ValueError(f"unknown kind '{kind}'")
    rec["wait_s" if kind == "approval" else "duration_s"] = round(seconds(start, end), 3)
    return rec


def append(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load(path):
    records = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn trailing line must not break the summary
    return records


def summarize(records):
    roles, slices = {}, {}
    approval = 0.0
    for r in records:
        if r.get("kind") == "approval":
            approval += r.get("wait_s", 0.0)
        elif r.get("kind") == "role":
            d = r.get("duration_s", 0.0)
            agg = roles.setdefault(r["role"], {"runs": 0, "wall_s": 0.0, "send_backs": 0})
            agg["runs"] += 1
            agg["wall_s"] += d
            if r.get("verdict") == "send-back":
                agg["send_backs"] += 1
            sl = slices.setdefault(r["slice"], {"wall_s": 0.0, "send_backs": 0, "reasons": []})
            sl["wall_s"] += d
            if r.get("verdict") == "send-back":
                sl["send_backs"] += 1
                if r.get("send_back_reason"):
                    sl["reasons"].append(r["send_back_reason"])
    total = sum(a["wall_s"] for a in roles.values())
    for a in roles.values():
        a["wall_s"] = round(a["wall_s"], 1)
        a["share_pct"] = round(100 * a["wall_s"] / total, 1) if total else 0.0
        a["send_back_rate_pct"] = round(100 * a["send_backs"] / a["runs"], 1) if a["runs"] else 0.0
    for s in slices.values():
        s["wall_s"] = round(s["wall_s"], 1)
    return {"roles": roles, "slices": slices, "role_wall_s": round(total, 1),
            "approval_wait_s": round(approval, 1)}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("append")
    a.add_argument("--file", required=True)
    a.add_argument("--kind", choices=["role", "approval"], required=True)
    a.add_argument("--role")
    a.add_argument("--slice", dest="slice_id")
    a.add_argument("--start", required=True)
    a.add_argument("--end", required=True)
    a.add_argument("--verdict")
    a.add_argument("--send-back-reason")
    a.add_argument("--what")
    s = sub.add_parser("summarize")
    s.add_argument("file")
    args = ap.parse_args()
    if args.cmd == "append":
        try:
            rec = build_record(args.kind, args.start, args.end, args.role, args.slice_id,
                               args.verdict, args.send_back_reason, args.what)
        except ValueError as e:
            ap.error(str(e))
        append(args.file, rec)
        print(json.dumps(rec, ensure_ascii=False))
    else:
        if not Path(args.file).exists():
            ap.error(f"no such file: {args.file}")
        json.dump(summarize(load(args.file)), sys.stdout, indent=2)
        print()


if __name__ == "__main__":
    main()
