from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROLES = ["specifier", "coder", "architect", "hardener", "qa"]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_role_set_has_no_cleaner():
    assert sorted(p.stem for p in (ROOT / "agents").glob("*.md")) == sorted(ROLES)


def test_every_role_has_constitution_staging_and_integration_rules():
    for role in ROLES:
        text = read(f"agents/{role}.md")
        assert ".specify/memory/constitution.yaml" in text, role
        assert "spec-change:" in text, role
        assert "git add -A" in text and ".bob/" in text, role
        assert "integration" in text.lower(), role


def test_specifier_returns_slices_file_and_orchestrator_reads_it():
    assert '"slices_file"' in read("agents/specifier.md")
    assert "slices_file" in read("commands/bob-run.md")


def test_constitution_send_back_diagnosis_in_architect_qa_and_run():
    for rel in ("agents/architect.md", "agents/qa.md", "commands/bob-run.md"):
        assert "constitution:<principle id>" in read(rel), rel


def test_bob_files_go_to_git_exclude_not_gitignore():
    assert ".git/info/exclude" in read("commands/bob-init.md")
    assert "git-common-dir" in read("commands/bob-run.md")


def test_hardener_builds_scope_from_scope_flag():
    assert "scope_flag" in read("agents/hardener.md")
    assert "--mutate" not in read("registry/tool-registry.yaml").split("scope_flag:")[0].split("tool: Stryker.NET")[1].split("run_command:")[1].split("\n")[0]


def test_1_3_contract_hooks():
    assert "## Send-back" in read("agents/qa.md") and "## Send-back" in read("agents/coder.md")
    assert "unfixed_findings" in read("agents/hardener.md")
    assert "files" in read("agents/specifier.md") and "DISJOINT" in read("agents/specifier.md")
    run = read("commands/bob-run.md")
    for token in ("bob_metrics.py", "parallel_plan.py qa-rerun", "parallel_plan.py batch", "--role merge-gate", "metrics.jsonl"):
        assert token in run, token
    assert "--steps qg" in read("commands/bob-init.md")


def test_version_bumped_consistently():
    import json
    assert json.loads(read(".claude-plugin/plugin.json"))["version"] == "1.3.1"
    assert json.loads(read(".claude-plugin/marketplace.json"))["plugins"][0]["version"] == "1.3.1"
    assert read("CHANGELOG.md").startswith("# Changelog\n\n## 1.3.1")
