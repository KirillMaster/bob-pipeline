#!/usr/bin/env python3
"""Shared diff helpers for the 1.9.0 gates (bugfix_gates, bugfix_ablation, tidy_first): hunks, comment filter, test-edit check."""
import re
import subprocess

from plan_conformance import DEFAULT_TEST_PATHS, changed_files, git, matches, offender  # noqa: F401

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
TRIVIAL = re.compile(r"^\s*(?:$|//|#(?!pragma)|/\*|\*|using\s|import\s|from\s+\S+\s+import\s)")
ASSERT_OR_LITERAL = re.compile(r"\b(?:Assert|assert|Should|Expect|expect|Verify|Throws)\b|\.Should\(|\d|[\"']")
TEST_METHOD = re.compile(r"\[(?:Fact|Theory|Test|TestCase|TestMethod)\b|^\s*(?:async\s+)?def\s+test_|^\s*(?:it|test)\(")


def exists_at(repo, ref, path):
    return git(repo, "cat-file", "-e", f"{ref}:{path}", check=False).returncode == 0


def hunks(repo, base, head, path):
    """[{old_start, old_count, new_start, new_count, removed, added, lines, patch}] of `git diff -U0 base..head -- path`."""
    out = git(repo, "diff", "-U0", "--no-color", f"{base}..{head}", "--", path).stdout
    header, result, cur = [], [], None
    for line in out.splitlines():
        m = HUNK.match(line)
        if m:
            cur = {"old_start": int(m.group(1)), "old_count": int(m.group(2) or 1),
                   "new_start": int(m.group(3)), "new_count": int(m.group(4) or 1),
                   "removed": [], "added": [], "lines": [line]}
            result.append(cur)
        elif cur is None:
            header.append(line)
        else:
            cur["lines"].append(line)
            if line.startswith("-"):
                cur["removed"].append(line[1:])
            elif line.startswith("+"):
                cur["added"].append(line[1:])
    for h in result:
        h["patch"] = "\n".join(header + h["lines"]) + "\n"
    return result


def substantive(lines):
    return [l for l in lines if not TRIVIAL.match(l)]


def is_test(path, test_paths):
    return matches(path, test_paths)


def test_edit_offenders(repo, base, head, test_paths, rule, fix_hint):
    """Existing test files may only gain lines: a removed assert/literal line or a deleted test file is an offender."""
    out = []
    for status, path, old in changed_files(repo, base, head):
        if not (is_test(path, test_paths) or (old and is_test(old, test_paths))):
            continue
        if status == "D":
            out.append(offender(rule, path, "existing test file deleted", f"restore {path}; {fix_hint}"))
        elif status in ("M", "R"):
            gone = [l for h in hunks(repo, base, head, old or path) for l in substantive(h["removed"]) if ASSERT_OR_LITERAL.search(l)]
            if gone:
                out.append(offender(rule, path, f"{len(gone)} assertion/literal line(s) removed or changed, e.g. `{gone[0].strip()[:80]}`",
                                    f"restore the original lines in {path}; {fix_hint}"))
    return out


def run(command, cwd, timeout=900):
    try:
        r = subprocess.run(command, shell=True, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode
    except subprocess.TimeoutExpired:
        return 124
