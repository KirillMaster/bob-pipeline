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
