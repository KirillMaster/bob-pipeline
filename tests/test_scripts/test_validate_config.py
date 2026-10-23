import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "validate_config.py"

VALID_TOOLS = """
  - stack: csharp
    category: mutation
    tool: Stryker.NET
    run_command: "dotnet stryker"
    report_parser: stryker
    enabled: true
  - stack: any
    category: complexity
    tool: lizard
    run_command: "lizard --csv ."
    report_parser: lizard
    enabled: true"""


def make_config(tmp_path, mutate=None):
    template = (ROOT / "templates" / "bob-pipeline.yaml").read_text(encoding="utf-8")
    text = (template.replace("{{PROJECT_NAME}}", "t")
            .replace("{{STACK}}", "csharp")
            .replace("{{TESTS_RUN_COMMAND}}", "dotnet test")
            .replace("{{TESTS_SCOPED_COMMAND}}", 'dotnet test --filter "{filter}"')
            .replace("{{TESTS_COVERAGE_COMMAND}}", "dotnet test --collect:x")
            .replace("{{TOOLS}}", VALID_TOOLS))
    if mutate:
        text = mutate(text)
    f = tmp_path / "bob-pipeline.yaml"
    f.write_text(text, encoding="utf-8")
    return f


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_template_with_defaults_is_valid(tmp_path):
    r = run(str(make_config(tmp_path)))
    assert r.returncode == 0, r.stderr


def test_registry_is_valid():
    r = run("--registry", str(ROOT / "registry" / "tool-registry.yaml"))
    assert r.returncode == 0, r.stderr


def test_threshold_out_of_range_rejected(tmp_path):
    f = make_config(tmp_path, lambda t: t.replace("mutation_score_min: 80", "mutation_score_min: 150"))
    r = run(str(f))
    assert r.returncode == 1
    violations = json.loads(r.stderr)["violations"]
    assert any("mutation_score_min" in v["path"] for v in violations)


def test_disabling_coder_rejected(tmp_path):
    f = make_config(tmp_path, lambda t: t.replace(
        "  - name: coder\n    model: sonnet\n    enabled: true",
        "  - name: coder\n    model: sonnet\n    enabled: false"))
    r = run(str(f))
    assert r.returncode == 1
    assert any("coder" in v["message"] for v in json.loads(r.stderr)["violations"])


def test_unknown_role_in_routes_rejected(tmp_path):
    f = make_config(tmp_path, lambda t: t.replace("qa: coder", "qa: reviewer"))
    r = run(str(f))
    assert r.returncode == 1


def test_unknown_parser_in_registry_rejected(tmp_path):
    reg = tmp_path / "reg.yaml"
    reg.write_text("""entries:
  - stack: csharp
    category: mutation
    tool: X
    run_command: x
    report_parser: nonexistent
    enabled: true
  - stack: any
    category: coverage
    tool: c
    run_command: c
    report_parser: lcov
    enabled: true
  - stack: any
    category: complexity
    tool: l
    run_command: l
    report_parser: lizard
    enabled: true
  - stack: any
    category: duplication
    tool: j
    run_command: j
    report_parser: jscpd
    enabled: true
""", encoding="utf-8")
    r = run("--registry", str(reg))
    assert r.returncode == 1
    assert any("nonexistent" in v["message"] for v in json.loads(r.stderr)["violations"])


def test_registry_unresolved_category_rejected(tmp_path):
    reg = tmp_path / "reg.yaml"
    reg.write_text("""entries:
  - stack: csharp
    category: mutation
    tool: X
    run_command: x
    report_parser: stryker
    enabled: true
""", encoding="utf-8")
    r = run("--registry", str(reg))
    assert r.returncode == 1
    assert any("unresolved" in v["message"] for v in json.loads(r.stderr)["violations"])


def legacy_cleaner(text):
    return text.replace("  - name: architect\n", "  - name: cleaner\n", 1).replace("architect: coder", "cleaner: coder")


def test_template_has_no_cleaner_role():
    import yaml
    tpl = (ROOT / "templates" / "bob-pipeline.yaml").read_text(encoding="utf-8")
    names = [r["name"] for r in yaml.safe_load(tpl.replace("{{TOOLS}}", "[]"))["roles"]]
    assert names == ["specifier", "coder", "architect", "hardener", "qa"]


def test_legacy_cleaner_accepted_with_deprecation_warning(tmp_path):
    r = run(str(make_config(tmp_path, legacy_cleaner)))
    assert r.returncode == 0, r.stderr
    assert "deprecated" in r.stderr and "cleaner" in r.stderr


def test_cleaner_and_architect_together_is_duplicate(tmp_path):
    def both(text):
        return text.replace("  - name: hardener\n", "  - name: cleaner\n    model: sonnet\n    enabled: true\n    gates: [tests-green]\n  - name: hardener\n", 1)
    r = run(str(make_config(tmp_path, both)))
    assert r.returncode == 1 and "duplicate" in r.stderr


def test_scoped_command_requires_filter_placeholder(tmp_path):
    r = run(str(make_config(tmp_path, lambda t: t.replace('--filter "{filter}"', ""))))
    assert r.returncode == 1


def test_tests_section_is_optional_for_legacy_configs(tmp_path):
    import re
    r = run(str(make_config(tmp_path, lambda t: re.sub(r"(?ms)^tests:.*?\n\n", "", t))))
    assert r.returncode == 0, r.stderr


def test_registry_mutation_entries_have_scope_flag():
    import yaml
    data = yaml.safe_load((ROOT / "registry" / "tool-registry.yaml").read_text(encoding="utf-8"))
    flags = {e["tool"]: e["scope_flag"] for e in data["entries"] if e["category"] == "mutation"}
    assert flags["Stryker.NET"] == '--mutate "{file}"'
    assert "mutmut" in flags and "StrykerJS" in flags
    assert run("--registry", str(ROOT / "registry" / "tool-registry.yaml")).returncode == 0


def test_registry_mutation_without_scope_flag_rejected(tmp_path):
    f = tmp_path / "reg.yaml"
    f.write_text("entries:\n  - {stack: any, category: mutation, tool: x, run_command: x, report_parser: stryker, enabled: true}\n", encoding="utf-8")
    r = run("--registry", str(f))
    assert r.returncode == 1 and "scope_flag" in r.stderr
