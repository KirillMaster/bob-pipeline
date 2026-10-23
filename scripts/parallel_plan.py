#!/usr/bin/env python3
"""Parallelism planning (design D16, D17).

Usage:
    python scripts/parallel_plan.py batch --slices <slices.yaml> --merged S1,S2 [--running S3] [--failed S4] --limit 3
    python scripts/parallel_plan.py qa-rerun --changed <file>... --qa <.qa.md>...

batch      prints a JSON list of slice ids to start now: pending, all depends_on merged, not
           blocked by a failed predecessor, and independent of every running/selected slice
           (disjoint declared `files`). A slice without `files` only runs alone. At most
           `limit - len(running)` ids.
qa-rerun   prints a JSON list of QA procedure ids whose text references any file the hardener
           changed (the rest of the QA verdict stays valid). A procedure is a `##`/`###` heading
           block of the .qa.md; its id is the first scenario-id-like token of the heading
           (e.g. S1-AS1, US2-AS3), else the whole heading text.
Exit 0 ok, 2 usage error.
"""
import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath

import yaml

ID = re.compile(r"\b[A-Z]{1,3}\d+-AS\d+\b")


def norm(p):
    return PurePosixPath(str(p).replace("\\", "/").strip().lstrip("./").rstrip("/")).as_posix()


def overlaps(a, b):
    """Two declared paths overlap when equal or one is a directory prefix of the other."""
    a, b = norm(a), norm(b)
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def files_disjoint(fa, fb):
    return not any(overlaps(x, y) for x in fa for y in fb)


def dependencies(slices, sid, by_id, seen=None):
    seen = seen if seen is not None else set()
    for d in by_id[sid].get("depends_on") or []:
        if d not in seen:
            seen.add(d)
            if d in by_id:
                dependencies(slices, d, by_id, seen)
    return seen


def independent(a, b, slices, by_id):
    if a["id"] in dependencies(slices, b["id"], by_id) or b["id"] in dependencies(slices, a["id"], by_id):
        return False
    fa, fb = a.get("files") or [], b.get("files") or []
    return bool(fa) and bool(fb) and files_disjoint(fa, fb)


def batch(slices, merged, running, failed, limit):
    by_id = {s["id"]: s for s in slices}
    merged, running, failed = set(merged), set(running), set(failed)
    room = limit - len(running)
    chosen = []
    for s in slices:
        if room <= 0:
            break
        sid = s["id"]
        if sid in merged or sid in running or sid in failed:
            continue
        deps = s.get("depends_on") or []
        if any(d in failed for d in deps) or not all(d in merged for d in deps):
            continue
        active = [by_id[r] for r in running if r in by_id] + [by_id[c] for c in chosen]
        if all(independent(s, o, slices, by_id) for o in active):
            chosen.append(sid)
            room -= 1
    return chosen


def split_procedures(text):
    blocks, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^#{2,3}\s+(.*\S)\s*$", line)
        if m:
            cur = {"heading": m.group(1), "lines": []}
            blocks.append(cur)
        elif cur is not None:
            cur["lines"].append(line)
    out = []
    for b in blocks:
        found = ID.search(b["heading"]) or ID.search("\n".join(b["lines"][:3]))
        out.append((found.group(0) if found else b["heading"], "\n".join(b["lines"])))
    return out


def qa_rerun(changed, qa_texts):
    changed = [norm(c) for c in changed]
    base_names = {PurePosixPath(c).name for c in changed}
    ids = []
    for text in qa_texts:
        for pid, body in split_procedures(text):
            hay = body.replace("\\", "/")
            if any(c in hay for c in changed) or any(re.search(r"(?<![\w.-])" + re.escape(n) + r"(?![\w-])", hay) for n in base_names):
                if pid not in ids:
                    ids.append(pid)
    return ids


def csv(value):
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("batch")
    b.add_argument("--slices", required=True)
    b.add_argument("--merged", default="")
    b.add_argument("--running", default="")
    b.add_argument("--failed", default="")
    b.add_argument("--limit", type=int, required=True)
    q = sub.add_parser("qa-rerun")
    q.add_argument("--changed", nargs="*", default=[])
    q.add_argument("--qa", nargs="+", required=True)
    args = ap.parse_args()
    if args.cmd == "batch":
        data = yaml.safe_load(Path(args.slices).read_text(encoding="utf-8-sig"))
        slices = data["slices"] if isinstance(data, dict) else data
        out = batch(slices, csv(args.merged), csv(args.running), csv(args.failed), args.limit)
    else:
        out = qa_rerun(args.changed, [Path(p).read_text(encoding="utf-8-sig") for p in args.qa])
    json.dump(out, sys.stdout)
    print()


if __name__ == "__main__":
    main()
