import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import upgrade_project as up  # noqa: E402

OLD_AGENT = "# {{PROJECT_NAME}} coder\nDomain: {{DOMAIN}}\nStack: {{TECH_STACK}}\nRun everything often.\nEnd.\n"
NEW_AGENT = "# {{PROJECT_NAME}} coder\nDomain: {{DOMAIN}}\nStack: {{TECH_STACK}}\nRun scoped tests; one full run at the end.\nEnd.\n"
OLD_CFG = """version: "1"
project_name: p
stack: csharp
roles:
  - {name: specifier, model: sonnet, enabled: true, gates: [gherkin-traceability]}
  - {name: coder, model: sonnet, enabled: true, gates: [tests-green]}
  - {name: cleaner, model: sonnet, enabled: true, gates: [tests-green, complexity-baseline, duplication-baseline]}
  - {name: architect, model: sonnet, enabled: true, gates: [tests-green]}
  - {name: hardener, model: haiku, enabled: true, gates: [tests-green, mutation-score]}
  - {name: qa, model: haiku, enabled: true, gates: [tests-green, gherkin-traceability]}
tools:
  - {stack: csharp, category: mutation, tool: Stryker.NET, run_command: "dotnet stryker --reporter json", report_parser: stryker, enabled: true}
human_gates: {gherkin_approval: true, final_qa_report: true}
thresholds: {mutation_score_min: 80, coverage_policy: informational, complexity_policy: not-worse-than-baseline, duplication_policy: not-worse-than-baseline}
send_back_routes: {qa: coder, architect: [cleaner, coder]}
return_limit: 3
parallel_limit: 3
night_mode_default: false
"""


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


def make_plugin(tmp_path):
    root = tmp_path / "plugin"
    (root / "agents").mkdir(parents=True)
    (root / "templates").mkdir()
    (root / "registry").mkdir()
    (root / "agents" / "coder.md").write_text(OLD_AGENT, encoding="utf-8")
    (root / "agents" / "cleaner.md").write_text("cleaner {{PROJECT_NAME}}\n", encoding="utf-8")
    for rel in ("templates/bob-pipeline.yaml", "registry/tool-registry.yaml"):
        (root / rel).write_text((ROOT / rel).read_text(encoding="utf-8"), encoding="utf-8")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "old")
    git(root, "tag", "v1.1.0")
    (root / "agents" / "coder.md").write_text(NEW_AGENT, encoding="utf-8")
    (root / "agents" / "cleaner.md").unlink()
    return root


def make_project(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".claude" / "agents" / "bob").mkdir(parents=True)
    (proj / "App.sln").write_text("", encoding="utf-8")
    (proj / ".claude" / "bob-pipeline.yaml").write_text(OLD_CFG, encoding="utf-8")
    agent = (OLD_AGENT.replace("{{PROJECT_NAME}}", "Shop").replace("{{DOMAIN}}", "e-commerce")
             .replace("{{TECH_STACK}}", "C# / .NET 8") + "Project rule: never touch Legacy/.\n")
    (proj / ".claude" / "agents" / "bob" / "coder.md").write_text(agent, encoding="utf-8")
    (proj / ".claude" / "agents" / "bob" / "cleaner.md").write_text("cleaner Shop\n", encoding="utf-8")
    (proj / ".gitignore").write_text("bin/\nobj/", encoding="utf-8")
    git(proj, "init", "-q")
    (proj / ".claude" / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(git status:*)"]}, "x": 1}), encoding="utf-8")
    return proj


def run_cli(proj, plugin, *extra):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "upgrade_project.py"), "--project", str(proj),
                           "--plugin-root", str(plugin), *extra], capture_output=True, text=True)


def snapshot(proj):
    return {p: p.read_bytes() for p in proj.rglob("*") if p.is_file()}


def test_dry_run_changes_nothing(tmp_path):
    plugin, proj = make_plugin(tmp_path), make_project(tmp_path)
    before = snapshot(proj)
    r = run_cli(proj, plugin, "--dry-run")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert rep["steps"]["agents"]["removed"] == ["cleaner.md"]
    assert rep["steps"]["support"]["exclude_added"]
    assert before == snapshot(proj)


def test_full_upgrade(tmp_path):
    plugin, proj = make_plugin(tmp_path), make_project(tmp_path)
    r = run_cli(proj, plugin)
    assert r.returncode == 0, r.stderr + r.stdout
    cfg_path = proj / ".claude" / "bob-pipeline.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert [x["name"] for x in cfg["roles"]] == ["specifier", "coder", "architect", "hardener", "qa"]
    arch = next(x for x in cfg["roles"] if x["name"] == "architect")
    assert "complexity-baseline" in arch["gates"]
    assert cfg["send_back_routes"]["architect"] == "coder"
    assert cfg["tests"]["run_command"] == "dotnet test App.sln"
    assert "{filter}" in cfg["tests"]["scoped_command"] and "XPlat" in cfg["tests"]["coverage_command"]
    assert cfg["tools"][0]["scope_flag"] == '--mutate "{file}"'
    assert (proj / ".claude" / "bob-pipeline.yaml.bak-pre-1.2").exists()
    v = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_config.py"), str(cfg_path)],
                       capture_output=True, text=True)
    assert v.returncode == 0, v.stderr

    agent = (proj / ".claude" / "agents" / "bob" / "coder.md").read_text(encoding="utf-8")
    assert "Domain: e-commerce" in agent and "C# / .NET 8" in agent
    assert "one full run at the end" in agent
    assert "never touch Legacy" in agent
    assert not (proj / ".claude" / "agents" / "bob" / "cleaner.md").exists()

    assert (proj / ".gitignore").read_text(encoding="utf-8") == "bin/\nobj/"
    ex = (proj / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert "/.bob/" in ex and "/.claude/agents/bob/" in ex and "/.claude/bob-pipeline.yaml" in ex
    settings = json.loads((proj / ".claude" / "settings.json").read_text(encoding="utf-8"))
    allow = settings["permissions"]["allow"]
    assert allow[0] == "Bash(git status:*)" and settings["x"] == 1
    assert "Bash(dotnet test:*)" in allow and "Bash(dotnet stryker:*)" in allow


def test_second_run_is_idempotent(tmp_path):
    plugin, proj = make_plugin(tmp_path), make_project(tmp_path)
    run_cli(proj, plugin)
    snap = snapshot(proj)
    rep = json.loads(run_cli(proj, plugin).stdout)
    assert rep["steps"]["config"]["changes"] == []
    assert rep["steps"]["support"] == {"exclude_added": [], "permissions_added": []}
    assert snap == snapshot(proj)


def test_conflicting_customization_leaves_markers_and_exit_1(tmp_path):
    plugin, proj = make_plugin(tmp_path), make_project(tmp_path)
    f = proj / ".claude" / "agents" / "bob" / "coder.md"
    f.write_text(f.read_text(encoding="utf-8").replace("Run everything often.", "Run only on Tuesdays."), encoding="utf-8")
    r = run_cli(proj, plugin, "--steps", "agents")
    assert r.returncode == 1
    assert "<<<<<<<" in f.read_text(encoding="utf-8")


def test_extract_values_multiline_and_line_fallback():
    old = "a {{X}}\nTools:\n{{TOOLS}}\nend {{X}}\n"
    assert up.extract_values(old, "a foo\nTools:\n- t1\n- t2\nend foo\n") == {"X": "foo", "TOOLS": "- t1\n- t2"}
    vals = up.extract_values(old, "a foo\nTools:\nT\nextra line\nend foo\n")
    assert vals.get("X") == "foo"


def test_command_prefixes():
    assert up.command_prefixes('dotnet test {sln} --filter "{filter}"') == ["dotnet test"]
    assert up.command_prefixes("python -m coverage run -m pytest && python -m coverage xml") == [
        "python -m coverage run -m pytest", "python -m coverage xml"]
    assert up.command_prefixes("npx vitest run --coverage || npx jest --coverage") == ["npx vitest run", "npx jest"]


def test_untrack_is_opt_in_and_removes_from_index_only(tmp_path):
    plugin, proj = make_plugin(tmp_path), make_project(tmp_path)
    git(proj, "add", "-f", ".claude/bob-pipeline.yaml", ".claude/agents/bob/coder.md")
    r = run_cli(proj, plugin)
    assert "untrack" not in json.loads(r.stdout)["steps"]
    dry = json.loads(run_cli(proj, plugin, "--steps", "untrack", "--dry-run").stdout)
    assert set(dry["steps"]["untrack"]["untracked"]) == {".claude/bob-pipeline.yaml", ".claude/agents/bob"}
    assert subprocess.run(["git", "-C", str(proj), "ls-files", ".claude"], capture_output=True, text=True).stdout.strip()
    rep = json.loads(run_cli(proj, plugin, "--steps", "untrack").stdout)
    assert rep["steps"]["untrack"]["untracked"]
    assert not subprocess.run(["git", "-C", str(proj), "ls-files", ".claude/agents", ".claude/bob-pipeline.yaml"],
                              capture_output=True, text=True).stdout.strip()
    assert (proj / ".claude" / "bob-pipeline.yaml").exists()
    assert json.loads(run_cli(proj, plugin, "--steps", "untrack").stdout)["steps"]["untrack"]["untracked"] == []


def test_exclude_uses_common_dir_from_worktree(tmp_path):
    plugin, proj = make_plugin(tmp_path), make_project(tmp_path)
    git(proj, "commit", "--allow-empty", "-qm", "init")
    wt = tmp_path / "wt"
    git(proj, "worktree", "add", str(wt), "-b", "x")
    run_cli(wt, plugin, "--steps", "support")
    assert "/.bob/" in (proj / ".git" / "info" / "exclude").read_text(encoding="utf-8")


def test_integration_exclusion_added_only_with_integration_command(tmp_path):
    plugin, proj = make_plugin(tmp_path), make_project(tmp_path)
    (proj / "Shop.IntegrationTests").mkdir()
    rep = json.loads(run_cli(proj, plugin, "--steps", "config", "--dry-run").stdout)
    assert not any("integration exclusion" in c for c in rep["steps"]["config"]["changes"])
    assert rep["steps"]["config"]["integration_candidates"] == ["Shop.IntegrationTests"]
    cfg_path = proj / ".claude" / "bob-pipeline.yaml"
    tests_block = (
        "tests:\n"
        "  run_command: dotnet test App.sln\n"
        "  scoped_command: 'dotnet test App.sln --filter \"{filter}\"'\n"
        "  integration_command: dotnet test --filter Category=Integration\n"
        "tools:"
    )
    cfg_path.write_text(OLD_CFG.replace("tools:", tests_block), encoding="utf-8")
    run_cli(proj, plugin, "--steps", "config")
    t = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["tests"]
    assert t["run_command"].endswith('--filter "Category!=Integration"')
    assert t["scoped_command"].endswith('--filter "({filter})&Category!=Integration"')
    run_cli(proj, plugin, "--steps", "config")
    assert yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["tests"] == t
