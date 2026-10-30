import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ci_gates  # noqa: E402

SCRIPT = ROOT / "scripts" / "ci_gates.py"
TESTS = "tests/Billing.Tests/CalcTests.cs"
ADR_OK = "# ADR 1\n\n## Context\nWhy.\n\n## Decision\nThis.\n\n## Alternatives\nOther.\n"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def write(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "src/Billing/Calc.cs", "namespace Billing;\npublic class Calc {\n}\n")
    write(repo, TESTS, "[Fact]\npublic void Adds() {\n    Assert.Equal(5, Calc.Add(2, 3));\n}\n")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "feature")
    return repo


def cli(repo, *extra):
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), "--base", "main", *extra],
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else {}), r.stderr


def test_clean_range_passes(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, "src/Billing/Calc.cs", "namespace Billing;\npublic class Calc {\n    // note\n}\n")
    commit(repo, "feat: comment")
    code, report, _ = cli(repo)
    assert code == 0 and report["passed"]
    assert report["gates"]["adr"]["applicable"] is False and report["gates"]["bugfix"]["applicable"] is False


def test_tidy_commit_editing_assertion_fails(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, TESTS, "[Fact]\npublic void Adds() {\n    Assert.Equal(6, Calc.Add(2, 3));\n}\n")
    commit(repo, "refactor: rename")
    code, report, err = cli(repo)
    assert code == 1
    assert report["gates"]["tidy-first"]["offenders"][0]["rule"] == "structural-edits-assertion"
    assert "FAIL" in err


def test_warn_only_exits_zero_but_reports(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, TESTS, "[Fact]\npublic void Adds() {\n    Assert.Equal(6, Calc.Add(2, 3));\n}\n")
    commit(repo, "tidy: x")
    code, report, _ = cli(repo, "--warn-only")
    assert code == 0 and report["passed"] is False


def test_github_annotations(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, TESTS, "[Fact]\npublic void Adds() {\n    Assert.Equal(6, Calc.Add(2, 3));\n}\n")
    commit(repo, "style: x")
    _, _, err = cli(repo, "--annotations", "github")
    assert err.startswith("::error file=" + TESTS)


def test_new_interface_without_adr_fails(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, "src/Billing/IPricer.cs", "namespace Billing;\npublic interface IPricer {\n}\n")
    commit(repo, "feat: pricer")
    code, report, _ = cli(repo)
    assert code == 1
    assert report["gates"]["adr"]["offenders"][0]["rule"] == "adr-missing"
    assert report["gates"]["adr"]["source"] == "diff"


def test_new_interface_with_adr_passes(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, "src/Billing/IPricer.cs", "namespace Billing;\npublic interface IPricer {\n}\n")
    write(repo, "docs/adr/0001-pricer.md", ADR_OK)
    commit(repo, "feat: pricer")
    code, report, _ = cli(repo)
    assert code == 0 and report["gates"]["adr"]["applicable"] is True


def test_incomplete_adr_fails(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, "src/Billing/IPricer.cs", "namespace Billing;\npublic interface IPricer {\n}\n")
    write(repo, "docs/adr/0001-pricer.md", "# ADR\n\n## Context\nWhy.\n")
    commit(repo, "feat: pricer")
    code, report, _ = cli(repo)
    assert code == 1 and report["gates"]["adr"]["offenders"][0]["rule"] == "adr-incomplete"


def test_adr_exempt_in_commit_body(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, "src/Billing/IPricer.cs", "namespace Billing;\npublic interface IPricer {\n}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "feat: pricer", "-m", "adr-exempt: mirror of an existing contract")
    assert cli(repo)[0] == 0


def test_new_project_reference_triggers_adr(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, "src/Billing/Billing.csproj", "<Project>\n</Project>\n")
    commit(repo, "chore: proj")
    git(repo, "checkout", "-q", "-b", "edge")
    write(repo, "src/Billing/Billing.csproj", '<Project>\n  <ProjectReference Include="../Core/Core.csproj" />\n</Project>\n')
    commit(repo, "feat: edge")
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), "--base", "feature", "--gates", "adr"],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "new ProjectReference" in r.stdout


def test_bugfix_manifest_gate_runs_on_changed_manifest(tmp_path):
    repo = make_repo(tmp_path)
    manifest = {"slices": [{"slice": "S1", "feature_module": "Billing", "kind": "bugfix",
                            "allowed_paths": ["src/Billing/**", "tests/**", ".bob/**"], "new_types": [], "allowed_new_edges": [],
                            "locked_tests": [TESTS], "root_cause": "src/Billing/Calc.cs", "regression_test": [TESTS]}]}
    import yaml
    write(repo, ".bob/features/f.manifest.yaml", yaml.safe_dump(manifest))
    write(repo, "src/Other.cs", "namespace X;\npublic class Other {\n}\n")
    commit(repo, "fix: bug")
    code, report, _ = cli(repo, "--gates", "bugfix")
    assert code == 1
    assert report["gates"]["bugfix"]["applicable"] is True
    assert any(o["rule"] == "root-cause-untouched" for o in report["gates"]["bugfix"]["offenders"])


def test_config_can_disable_gate(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, TESTS, "[Fact]\npublic void Adds() {\n    Assert.Equal(6, Calc.Add(2, 3));\n}\n")
    commit(repo, "tidy: x")
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("tidy_first:\n  enabled: false\n", encoding="utf-8")
    assert cli(repo, "--config", str(cfg))[0] == 0


def test_unknown_gate_and_bad_base_are_usage_errors(tmp_path):
    repo = make_repo(tmp_path)
    assert cli(repo, "--gates", "nope")[0] == 2
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), "--base", "no-such-ref"], capture_output=True, text=True)
    assert r.returncode == 2


def test_module_helpers_importable():
    assert ci_gates.GATES == ["tidy-first", "adr", "bugfix"]
