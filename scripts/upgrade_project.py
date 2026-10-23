#!/usr/bin/env python3
"""Deterministic parts of `/bob-init --upgrade` (design D12), also reused by /bob-init (D8/D9).

Usage:
    python scripts/upgrade_project.py --project <dir> [--plugin-root <dir>] [--dry-run]
        [--steps config,agents,support,untrack] [--old-ref <git-ref> ...] [--prefer-new]

Steps (default: all):
    config   migrate .claude/bob-pipeline.yaml: cleaner -> architect (gates merged, routes
             rewritten), add tests.* from the template's per-stack defaults, add scope_flag
             to mutation tools, and (only when tests.integration_command is set) the stack's
            integration-exclusion filter to run/coverage/scoped commands. The old file is kept as bob-pipeline.yaml.bak-pre-1.2
             (comments are not preserved by the rewrite).
    agents   3-way regenerate .claude/agents/bob/*.md: base = old plugin template (from git
             history of the plugin, see --old-ref) rendered with the placeholder values
             recovered from the project copy; ours = project copy; theirs = new template
             rendered with the same values. Merged with `git merge-file`; conflicts are left
             as markers and reported. Removes agents/bob/cleaner.md.
    support  add the bob files to .git/info/exclude (local, shared by all worktrees; never
             .gitignore, design D15) and merge permissions.allow for the configured commands
             into .claude/settings.json (existing entries are kept).
    untrack  OPT-IN (not in the default steps): `git rm -r --cached` the bob files when they are
             tracked in the project repo. Files stay on disk; nothing is committed — the caller
             commits the removal.

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
DEFAULT_OLD_REFS = ["v1.2.0", "v1.1.0", "3456188", "v1.0.0", "d7caca1"]
DEFAULT_STEPS = "config,agents,support"
ALL_STEPS = {"config", "agents", "support", "untrack"}
# bob-owned local tooling, never tracked in the project repo (design D15)
BOB_PATHS = [".claude/bob-pipeline.yaml", ".claude/bob-pipeline.yaml.bak-pre-1.2", ".claude/agents/bob/", ".bob/", ".worktrees/"]
EXCLUDE_HEADER = "# bob-pipeline local files"
SHARED_KEYS = {"PROJECT_NAME", "DOMAIN", "TECH_STACK"}  # same value in every role copy
SKIP_DIRS = {".git", "node_modules", "bin", "obj", ".venv", ".worktrees", ".bob"}
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


def add_integration_exclusion(command, key, defaults):
    """Append the stack's integration-exclusion filter; None when not applicable or already present."""
    flag = defaults.get("exclude_integration")
    if not command or not flag:
        return None
    marker = flag.split()[0]
    if key == "scoped_command":
        scoped = defaults.get("scoped_exclude_integration")
        if not scoped or "Category!=Integration" in command:
            return None
        # only the exact template shape is rewritten; anything custom is left alone
        template_filter = '--filter "{filter}"'
        if template_filter in command and "--filter" in scoped:
            return command.replace(template_filter, scoped)
        return None
    if "integration" in command.lower():
        return None
    if marker in command or (marker == "--filter" and "--filter" in command) or (marker == "-m" and " -m " in command):
        return None
    return f"{command} {flag}"


def find_integration_candidates(project, limit=5):
    """Cheap hint for /bob-init and the upgrade report: paths with 'integration' in their name."""
    found = []
    stack = [project]
    while stack and len(found) < limit:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for e in entries:
            if e.name in SKIP_DIRS:
                continue
            if "integration" in e.name.lower() and (e.is_dir() or e.suffix in (".csproj", ".py", ".ts", ".js", ".java", ".cs")):
                found.append(str(e.relative_to(project)).replace("\\", "/"))
                if len(found) >= limit:
                    break
            elif e.is_dir():
                stack.append(e)
    return found


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
    if not defaults and config.get("stack"):
        changes.append(f"NOTE tests.*: stack {config['stack']!r} has no single default; set tests.run_command/scoped_command/coverage_command (and integration_command) via /bob-config")
    sln = detect_sln(project)
    for key in ("run_command", "scoped_command", "coverage_command"):
        if key not in tests and key in defaults:
            tests[key] = fill_sln(defaults[key], sln)
            changes.append(f"tests.{key}: added from template defaults")
    if tests.get("integration_command"):
        for key in ("run_command", "coverage_command", "scoped_command"):
            new = add_integration_exclusion(tests.get(key), key, defaults)
            if new and new != tests[key]:
                tests[key] = new
                changes.append(f"tests.{key}: integration exclusion filter added")
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


# ── support: local exclude + permissions ─────────────────────────────

def git_common_dir(project):
    r = subprocess.run(["git", "-C", str(project), "rev-parse", "--git-common-dir"],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        return None
    d = Path(r.stdout.strip())
    return d if d.is_absolute() else (project / d).resolve()


def exclude_additions(text):
    present = {ln.strip() for ln in text.splitlines()}
    return [f"/{p}" for p in BOB_PATHS if f"/{p}" not in present]


def tracked_bob_paths(project):
    out = []
    for p in BOB_PATHS:
        r = subprocess.run(["git", "-C", str(project), "ls-files", "--", p.rstrip("/")],
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0 and r.stdout.strip():
            out.append(p.rstrip("/"))
    return out


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


def merge_file(ours, base, theirs, prefer_new=False):
    """git merge-file -p: returns (text, conflict_count). prefer_new resolves conflicting hunks to the new template."""
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for name, text in (("ours", ours), ("base", base), ("theirs", theirs)):
            p = Path(d) / name
            p.write_text(text, encoding="utf-8", newline="")
            paths.append(str(p))
        r = subprocess.run(["git", "merge-file", "-p", "-L", "project", "-L", "old-template", "-L", "new-template", *(["--theirs"] if prefer_new else []), *paths], capture_output=True, text=True, encoding="utf-8")
        if r.returncode < 0 or r.returncode > 127:
            raise RuntimeError(r.stderr.strip() or "git merge-file failed")
        return r.stdout, r.returncode


def upgrade_agent(project_copy, role, plugin_root, old_refs, shared=None, prefer_new=False):
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
    theirs = render(new_tpl, {**{k: v for k, v in (shared or {}).items() if k not in values}, **values})
    text, conflicts = merge_file(project_copy, base, theirs)
    if conflicts and prefer_new:
        text, _ = merge_file(project_copy, base, theirs, True)
    unresolved = sorted(set(PLACEHOLDER.findall(text)))
    status = "merged" if not conflicts else ("merged-prefer-new" if prefer_new else "conflicts")
    return {"status": status, "text": text, "conflicts": conflicts, "unresolved": unresolved,
            "ref": ref, "values": values}


def fallback_values(config, role):
    """Placeholder values derivable from the config when no project copy carries them."""
    out = {}
    if config:
        if config.get("project_name"):
            out["PROJECT_NAME"] = config["project_name"]
        if config.get("stack"):
            out["TECH_STACK"] = config["stack"]
        if role == "hardener":
            tools = [f"{t['tool']}: `{t['run_command']}`" for t in config.get("tools", [])
                     if t.get("category") == "mutation" and t.get("enabled")]
            if tools:
                out["TOOLS"] = "; ".join(tools)
    return out


# ── driver ───────────────────────────────────────────────────────────

def run(project, plugin_root, dry_run, steps, old_refs, prefer_new=False):
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
            if not config.get("tests", {}).get("integration_command"):
                hint = find_integration_candidates(project)
                if hint:
                    report["steps"]["config"]["integration_candidates"] = hint

    if "agents" in steps:
        agents_dir = project / ".claude" / "agents" / "bob"
        res = {"files": {}, "removed": []}
        shared, pending = {}, []
        if agents_dir.is_dir():
            for f in sorted(agents_dir.glob("*.md")):
                role = f.stem
                if role in DEPRECATED_ROLES:
                    res["removed"].append(f.name)
                    if not dry_run:
                        f.unlink()
                    continue
                current = f.read_text(encoding="utf-8")
                r = upgrade_agent(current, role, plugin_root, old_refs, {**fallback_values(config, role), **shared}, prefer_new)
                for k, v in r.get("values", {}).items():
                    if k in SHARED_KEYS and v:
                        shared.setdefault(k, v)
                pending.append((f, role, current, r))
            for f, role, current, r in pending:
                effective = {**fallback_values(config, role), **shared}
                if set(r.get("unresolved", [])) & set(effective):
                    r = upgrade_agent(current, role, plugin_root, old_refs, effective, prefer_new)
                r.pop("values", None)
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
        common = git_common_dir(project)
        if common is None:
            res["exclude_added"] = []
            res["exclude_skipped"] = "not a git repo"
        else:
            ex = common / "info" / "exclude"
            ex_text = ex.read_text(encoding="utf-8") if ex.exists() else ""
            add = exclude_additions(ex_text)
            res["exclude_added"] = add
            if add and not dry_run:
                ex.parent.mkdir(parents=True, exist_ok=True)
                sep = "" if not ex_text or ex_text.endswith("\n") else "\n"
                ex.write_text(ex_text + sep + EXCLUDE_HEADER + "\n" + "\n".join(add) + "\n", encoding="utf-8")
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

    if "untrack" in steps:
        tracked = tracked_bob_paths(project)
        res = {"untracked": tracked, "note": "commit the removal yourself; files stay on disk"}
        if tracked and not dry_run:
            r = subprocess.run(["git", "-C", str(project), "rm", "-r", "--cached", "-f", "-q", "--", *tracked],
                               capture_output=True, text=True, encoding="utf-8")
            if r.returncode != 0:
                res["error"] = r.stderr.strip()
        report["steps"]["untrack"] = res
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--plugin-root", default=str(PLUGIN_ROOT))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--steps", default=DEFAULT_STEPS, help="comma list of config,agents,support,untrack (untrack is opt-in)")
    ap.add_argument("--old-ref", action="append", help="git ref(s) of the plugin holding old agent templates")
    ap.add_argument("--prefer-new", action="store_true", help="resolve conflicting agent hunks to the new template (project edits elsewhere are kept)")
    args = ap.parse_args()
    steps = {s.strip() for s in args.steps.split(",") if s.strip()}
    if not steps <= ALL_STEPS:
        ap.error("--steps must be a subset of config,agents,support,untrack")
    project = Path(args.project).resolve()
    if not project.is_dir():
        ap.error(f"project dir not found: {project}")
    report = run(project, Path(args.plugin_root).resolve(), args.dry_run, steps, args.old_ref or DEFAULT_OLD_REFS, args.prefer_new)
    json.dump(report, sys.stdout, indent=2)
    print()
    conflicts = any(f.get("status") == "conflicts" for f in report["steps"].get("agents", {}).get("files", {}).values())
    sys.exit(1 if conflicts else 0)


if __name__ == "__main__":
    main()
