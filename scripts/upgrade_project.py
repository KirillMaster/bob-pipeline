#!/usr/bin/env python3
"""Deterministic parts of `/bob-init --upgrade` (design D12), also reused by /bob-init (D8/D9).

Usage:
    python scripts/upgrade_project.py --project <dir> [--plugin-root <dir>] [--dry-run]
        [--steps config,agents,support] [--old-ref <git-ref> ...]

Steps (default: all):
    config   migrate .claude/bob-pipeline.yaml: cleaner -> architect (gates merged, routes
             rewritten), add tests.* from the template's per-stack defaults, add scope_flag
             to mutation tools. The old file is kept as bob-pipeline.yaml.bak-pre-1.2
             (comments are not preserved by the rewrite).
    agents   3-way regenerate .claude/agents/bob/*.md: base = old plugin template (from git
             history of the plugin, see --old-ref) rendered with the placeholder values
             recovered from the project copy; ours = project copy; theirs = new template
             rendered with the same values. Merged with `git merge-file`; conflicts are left
             as markers and reported. Removes agents/bob/cleaner.md.
    support  add .gitignore entries for .bob runtime files and merge permissions.allow for the
             configured commands into .claude/settings.json (existing entries are kept).

Output: JSON report on stdout. Exit 0 ok; 1 when agent merges left conflicts; 2 usage error.
"""
import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OLD_REFS = ["v1.1.0", "3456188", "v1.0.0", "d7caca1"]
GITIGNORE_ENTRIES = [".bob/run-state.yaml", ".bob/state.yaml", ".bob/loop-logs/", ".worktrees/"]
GITIGNORE_HEADER = "# bob-pipeline runtime files"
DEPRECATED_ROLES = {"cleaner": "architect"}
PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


# ── template defaults ────────────────────────────────────────────────

def stack_defaults(template_text, stack):
    """Parse `#@ <stack>.<key> = <command>` lines of templates/bob-pipeline.yaml."""
    out = {}
    for m in re.finditer(r"^#@ (\w+)\.(\w+) = (.+)$", template_text, re.M):
        if m.group(1) == stack:
            out[m.group(2)] = m.group(3).strip()
    return out


def detect_sln(project):
    for pattern in ("*.sln", "*.csproj"):
        found = sorted(project.glob(pattern))
        if found:
            return found[0].name
    return None


def fill_sln(command, sln):
    return command.replace("{sln}", sln) if sln else command.replace(" {sln}", "")


# ── config migration ─────────────────────────────────────────────────

def migrate_config(config, template_text, registry, project):
    """Return (new_config, changes[])."""
    changes = []
    roles = config.get("roles", [])
    names = [r["name"] for r in roles]
    if "cleaner" in names:
        cleaner = next(r for r in roles if r["name"] == "cleaner")
        arch = next((r for r in roles if r["name"] == "architect"), None)
        if arch is None:
            cleaner["name"] = "architect"
            arch = cleaner
            changes.append("roles: cleaner renamed to architect")
        else:
            roles.remove(cleaner)
            changes.append("roles: cleaner removed (merged into architect)")
        gates = list(arch.get("gates", []))
        for g in cleaner.get("gates", []):
            if g not in gates:
                gates.append(g)
        for g in ("tests-green", "complexity-baseline", "duplication-baseline"):
            if g not in gates:
                gates.append(g)
        arch["gates"] = gates
        if not cleaner.get("enabled", True):
            arch["enabled"] = arch.get("enabled", True) and False
    routes = config.get("send_back_routes", {})
    new_routes = {}
    for source, targets in routes.items():
        targets = targets if isinstance(targets, list) else [targets]
        src = DEPRECATED_ROLES.get(source, source)
        mapped = []
        for t in targets:
            t = DEPRECATED_ROLES.get(t, t)
            if t != src and t not in mapped:
                mapped.append(t)
        if not mapped:
            changes.append(f"send_back_routes.{source}: dropped (only routed to itself)")
            continue
        value = mapped if len(mapped) > 1 else mapped[0]
        if src != source or value != routes[source]:
            changes.append(f"send_back_routes.{source}: {routes[source]} -> {src}: {value}")
        existing = new_routes.get(src)
        if existing is not None:
            merged = (existing if isinstance(existing, list) else [existing])
            merged += [m for m in mapped if m not in merged]
            value = merged if len(merged) > 1 else merged[0]
        new_routes[src] = value
    if routes:
        config["send_back_routes"] = new_routes

    defaults = stack_defaults(template_text, config.get("stack", ""))
    tests = config.get("tests")
    if tests is None:
        tests = {}
    sln = detect_sln(project)
    for key in ("run_command", "scoped_command", "coverage_command"):
        if key not in tests and key in defaults:
            tests[key] = fill_sln(defaults[key], sln)
            changes.append(f"tests.{key}: added from template defaults")
    if tests:
        config["tests"] = tests
    for tool in config.get("tools", []):
        if tool.get("category") == "mutation" and not tool.get("scope_flag"):
            entry = next((e for e in registry.get("entries", [])
                          if e.get("category") == "mutation" and e.get("tool") == tool.get("tool")
                          and e.get("scope_flag")), None)
            if entry:
                tool["scope_flag"] = entry["scope_flag"]
                changes.append(f"tools[{tool['tool']}].scope_flag: added from registry")
    return config, changes


# ── support: gitignore + permissions ─────────────────────────────────

def gitignore_additions(text):
    present = {ln.strip() for ln in text.splitlines()}
    return [e for e in GITIGNORE_ENTRIES if e not in present]


def command_prefixes(command):
    """`dotnet test {sln} --filter "{filter}"` -> `dotnet test`: text before the first placeholder/flag."""
    out = []
    for part in re.split(r"&&|\|\||;", command):
        words = []
        tokens = part.split()
        i = 0
        while i < len(tokens):
            w = tokens[i]
            if w == "-m" and i + 1 < len(tokens):
                words += [w, tokens[i + 1]]
                i += 2
                continue
            if (w.startswith(("-", "{", "<", '"', "'")) or "{" in w or "<" in w
                    or "/" in w or "\\" in w or w.endswith((".sln", ".slnx", ".csproj"))):
                break
            words.append(w)
            i += 1
        if words:
            out.append(" ".join(words))
    return out


def permission_entries(config):
    commands = []
    tests = config.get("tests") or {}
    for key in ("run_command", "scoped_command", "coverage_command"):
        if tests.get(key):
            commands.append(tests[key])
    for tool in config.get("tools", []):
        if tool.get("enabled"):
            commands.append(tool["run_command"])
    entries = []
    for c in commands:
        for prefix in command_prefixes(c):
            e = f"Bash({prefix}:*)"
            if e not in entries:
                entries.append(e)
    return entries


def merge_permissions(settings, entries):
    perms = settings.setdefault("permissions", {})
    allow = perms.setdefault("allow", [])
    added = [e for e in entries if e not in allow]
    allow.extend(added)
    return added


# ── agents 3-way merge ───────────────────────────────────────────────

def git_show(plugin_root, ref, path):
    r = subprocess.run(["git", "-C", str(plugin_root), "show", f"{ref}:{path}"],
                       capture_output=True, text=True, encoding="utf-8")
    return r.stdout if r.returncode == 0 else None


def render(template, values):
    return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), template)


def extract_values(old_template, project_copy):
    """Recover placeholder values from a project copy of an old template."""
    names = PLACEHOLDER.findall(old_template)
    if not names:
        return {}
    # whole-text match first (handles multi-line values), then line-aligned diff
    parts, seen = [], {}
    for chunk in re.split(r"(\{\{[A-Z_]+\}\})", old_template):
        m = PLACEHOLDER.fullmatch(chunk)
        if not m:
            parts.append(re.escape(chunk))
        elif m.group(1) in seen:
            parts.append(f"(?P={m.group(1)})")
        else:
            seen[m.group(1)] = True
            parts.append(f"(?P<{m.group(1)}>.*?)")
    m = re.fullmatch("".join(parts), project_copy, re.S)
    if m:
        return m.groupdict()
    values = {}
    old_lines, new_lines = old_template.splitlines(), project_copy.splitlines()
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "replace" or (i2 - i1) != (j2 - j1):
            continue
        for ol, nl in zip(old_lines[i1:i2], new_lines[j1:j2]):
            if not PLACEHOLDER.search(ol):
                continue
            rx, local = "", set()
            for chunk in re.split(r"(\{\{[A-Z_]+\}\})", ol):
                pm = PLACEHOLDER.fullmatch(chunk)
                if not pm:
                    rx += re.escape(chunk)
                elif pm.group(1) in local:
                    rx += f"(?P={pm.group(1)})"
                else:
                    local.add(pm.group(1))
                    rx += f"(?P<{pm.group(1)}>.*?)"
            lm = re.fullmatch(rx, nl)
            if lm:
                values.update({k: v for k, v in lm.groupdict().items() if k not in values})
    return values


def merge_file(ours, base, theirs):
    """git merge-file -p: returns (text, conflict_count)."""
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for name, text in (("ours", ours), ("base", base), ("theirs", theirs)):
            p = Path(d) / name
            p.write_text(text, encoding="utf-8", newline="")
            paths.append(str(p))
        r = subprocess.run(["git", "merge-file", "-p", *paths], capture_output=True, text=True, encoding="utf-8")
        if r.returncode < 0 or r.returncode > 127:
            raise RuntimeError(r.stderr.strip() or "git merge-file failed")
        return r.stdout, r.returncode


def upgrade_agent(project_copy, role, plugin_root, old_refs):
    """Return dict(status, text, conflicts, unresolved, ref)."""
    new_tpl_path = plugin_root / "agents" / f"{role}.md"
    if not new_tpl_path.exists():
        return {"status": "no-new-template"}
    new_tpl = new_tpl_path.read_text(encoding="utf-8")
    best = None
    for ref in old_refs:
        old = git_show(plugin_root, ref, f"agents/{role}.md")
        if old is None:
            continue
        values = extract_values(old, project_copy)
        score = difflib.SequenceMatcher(None, render(old, values), project_copy, autojunk=False).quick_ratio()
        if best is None or score > best[0]:
            best = (score, ref, old, values)
    if best is None:
        return {"status": "no-old-template", "note": f"none of {old_refs} has agents/{role}.md; regenerate manually"}
    _, ref, old, values = best
    base = render(old, values)
    theirs = render(new_tpl, values)
    text, conflicts = merge_file(project_copy, base, theirs)
    unresolved = sorted(set(PLACEHOLDER.findall(text)))
    return {"status": "conflicts" if conflicts else "merged", "text": text,
            "conflicts": conflicts, "unresolved": unresolved, "ref": ref}


# ── driver ───────────────────────────────────────────────────────────

def run(project, plugin_root, dry_run, steps, old_refs):
    report = {"dry_run": dry_run, "steps": {}}
    cfg_path = project / ".claude" / "bob-pipeline.yaml"
    config = yaml.safe_load(cfg_path.read_text(encoding="utf-8-sig")) if cfg_path.exists() else None

    if "config" in steps:
        if config is None:
            report["steps"]["config"] = {"skipped": "no .claude/bob-pipeline.yaml"}
        else:
            template_text = (plugin_root / "templates" / "bob-pipeline.yaml").read_text(encoding="utf-8")
            registry = yaml.safe_load((plugin_root / "registry" / "tool-registry.yaml").read_text(encoding="utf-8"))
            config, changes = migrate_config(config, template_text, registry, project)
            if changes and not dry_run:
                shutil.copyfile(cfg_path, cfg_path.with_name("bob-pipeline.yaml.bak-pre-1.2"))
                cfg_path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
            report["steps"]["config"] = {"changes": changes}

    if "agents" in steps:
        agents_dir = project / ".claude" / "agents" / "bob"
        res = {"files": {}, "removed": []}
        if agents_dir.is_dir():
            for f in sorted(agents_dir.glob("*.md")):
                role = f.stem
                if role in DEPRECATED_ROLES:
                    res["removed"].append(f.name)
                    if not dry_run:
                        f.unlink()
                    continue
                current = f.read_text(encoding="utf-8")
                r = upgrade_agent(current, role, plugin_root, old_refs)
                text = r.pop("text", None)
                r["changed"] = text is not None and text != current
                if r["changed"] and not dry_run:
                    f.write_text(text, encoding="utf-8", newline="")
                res["files"][f.name] = r
        else:
            res["skipped"] = "no .claude/agents/bob"
        report["steps"]["agents"] = res

    if "support" in steps:
        res = {}
        gi = project / ".gitignore"
        gi_text = gi.read_text(encoding="utf-8") if gi.exists() else ""
        add = gitignore_additions(gi_text)
        res["gitignore_added"] = add
        if add and not dry_run:
            sep = "" if not gi_text or gi_text.endswith("\n") else "\n"
            gi.write_text(gi_text + sep + GITIGNORE_HEADER + "\n" + "\n".join(add) + "\n", encoding="utf-8")
        settings_path = project / ".claude" / "settings.json"
        if config is not None:
            settings = json.loads(settings_path.read_text(encoding="utf-8-sig")) if settings_path.exists() else {}
            added = merge_permissions(settings, permission_entries(config))
            res["permissions_added"] = added
            if added and not dry_run:
                settings_path.parent.mkdir(parents=True, exist_ok=True)
                settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        else:
            res["permissions_added"] = []
        report["steps"]["support"] = res
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--plugin-root", default=str(PLUGIN_ROOT))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--steps", default="config,agents,support")
    ap.add_argument("--old-ref", action="append", help="git ref(s) of the plugin holding old agent templates")
    args = ap.parse_args()
    steps = {s.strip() for s in args.steps.split(",") if s.strip()}
    if not steps <= {"config", "agents", "support"}:
        ap.error("--steps must be a subset of config,agents,support")
    project = Path(args.project).resolve()
    if not project.is_dir():
        ap.error(f"project dir not found: {project}")
    report = run(project, Path(args.plugin_root).resolve(), args.dry_run, steps, args.old_ref or DEFAULT_OLD_REFS)
    json.dump(report, sys.stdout, indent=2)
    print()
    conflicts = any(f.get("status") == "conflicts" for f in report["steps"].get("agents", {}).get("files", {}).values())
    sys.exit(1 if conflicts else 0)


if __name__ == "__main__":
    main()
