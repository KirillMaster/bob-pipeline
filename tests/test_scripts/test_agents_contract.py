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
