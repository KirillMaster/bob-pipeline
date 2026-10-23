import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from compute_gates import compute  # noqa: E402


@pytest.fixture
def config():
    template = (ROOT / "templates" / "bob-pipeline.yaml").read_text(encoding="utf-8")
    filled = (template
              .replace("{{PROJECT_NAME}}", "fixture")
              .replace("{{STACK}}", "csharp")
              .replace("{{TESTS_RUN_COMMAND}}", "dotnet test")
              .replace("{{TESTS_SCOPED_COMMAND}}", 'dotnet test --filter "{filter}"')
              .replace("{{TESTS_COVERAGE_COMMAND}}", "dotnet test --collect:x")
              .replace("{{TOOLS}}", """
  - stack: csharp
    category: mutation
    tool: Stryker.NET
    run_command: "dotnet stryker"
    report_parser: stryker
    enabled: true
  - stack: csharp
    category: coverage
    tool: coverlet
    run_command: "dotnet test"
    report_parser: cobertura
    enabled: true
  - stack: any
    category: complexity
    tool: lizard
    run_command: "lizard --csv ."
    report_parser: lizard
    enabled: true
  - stack: any
    category: duplication
    tool: jscpd
    run_command: "jscpd ."
    report_parser: jscpd
    enabled: true"""))
    return yaml.safe_load(filled)


def gate(results, name):
    return next(r for r in results if r["gate"] == name)


def test_mutation_below_threshold_is_only_a_deviation(config):
    config["mutation"] = {"framework_enabled": True}
    results = compute(config, "hardener", [{"category": "mutation", "metric_value": 72}], None, 0, None)
    g = gate(results, "mutation-score")
    assert g["passed"] is True and g["deviation"] is True
    assert "72" in g["diagnosis"] and "80" in g["diagnosis"]


def test_mutation_at_threshold_passes(config):
    config["mutation"] = {"framework_enabled": True}
    results = compute(config, "hardener", [{"category": "mutation", "metric_value": 80}], None, 0, None)
    assert gate(results, "mutation-score")["passed"] is True


def test_coverage_is_informational_never_blocks(config):
    results = compute(config, "hardener",
                      [{"category": "mutation", "metric_value": 95}, {"category": "hardening", "metric_value": 0},
                       {"category": "coverage", "metric_value": 10}], None, 0, None)
    cov = gate(results, "coverage-informational")
    assert cov["passed"] is True
    assert all(r["passed"] for r in results)


def test_complexity_equal_to_baseline_passes(config):
    results = compute(config, "architect", [{"category": "complexity", "metric_value": 11},
                                          {"category": "duplication", "metric_value": 3.0}],
                      {"complexity": 11, "duplication": 3.0}, 0, None)
    assert gate(results, "complexity-baseline")["passed"] is True
    assert gate(results, "duplication-baseline")["passed"] is True


def test_complexity_worse_than_baseline_fails(config):
    results = compute(config, "architect", [{"category": "complexity", "metric_value": 14},
                                          {"category": "duplication", "metric_value": 3.0}],
                      {"complexity": 11, "duplication": 3.0}, 0, None)
    g = gate(results, "complexity-baseline")
    assert g["passed"] is False
    assert "baseline" in g["diagnosis"]


def test_first_run_without_baseline_passes_and_notes_capture(config):
    results = compute(config, "architect", [{"category": "complexity", "metric_value": 14},
                                          {"category": "duplication", "metric_value": 3.0}],
                      None, 0, None)
    g = gate(results, "complexity-baseline")
    assert g["passed"] is True
    assert "baseline" in g["diagnosis"]


def test_tests_green_fail(config):
    results = compute(config, "coder", [], None, 1, None)
    g = gate(results, "tests-green")
    assert g["passed"] is False
    assert "exited 1" in g["diagnosis"]


def test_traceability_missing_scenarios(config):
    results = compute(config, "qa", [], None, 0,
                      {"scenario_ids": ["US1-AS1", "US1-AS2"], "traced_ids": ["US1-AS1"]})
    g = gate(results, "gherkin-traceability")
    assert g["passed"] is False
    assert "US1-AS2" in g["diagnosis"]


def test_mutation_disabled_degrades_instead_of_blocking(config):
    for t in config["tools"]:
        if t["category"] == "mutation":
            t["enabled"] = False
    results = compute(config, "hardener", [], None, 0, None)
    g = gate(results, "mutation-score")
    assert g["passed"] is True
    assert "semantic" in g["diagnosis"]


def test_missing_mutation_metric_is_a_deviation_when_framework_enabled(config):
    config["mutation"] = {"framework_enabled": True}
    g = gate(compute(config, "hardener", [], None, 0, None), "mutation-score")
    assert g["passed"] is True and g["deviation"] is True


def test_mutation_framework_off_by_default_ignores_metric(config):
    g = gate(compute(config, "hardener", [{"category": "mutation", "metric_value": 10}], None, 0, None), "mutation-score")
    assert g["passed"] is True and "deviation" not in g


def test_legacy_cleaner_role_maps_to_architect(config):
    results = compute(config, "cleaner", [{"category": "complexity", "metric_value": 5},
                                          {"category": "duplication", "metric_value": 1.0}],
                      {"complexity": 11, "duplication": 3.0}, 0, None)
    assert gate(results, "complexity-baseline")["passed"] is True


def test_disabled_role_yields_no_gates(config):
    next(r for r in config["roles"] if r["name"] == "hardener")["enabled"] = False
    assert compute(config, "hardener", [], None, None, None) == []


def test_first_run_reports_captured_baselines(config):
    captured = {}
    compute(config, "architect", [{"category": "complexity", "metric_value": 14},
                                  {"category": "duplication", "metric_value": 3.0}],
            None, 0, None, captured=captured)
    assert captured == {"complexity": 14, "duplication": 3.0}


def test_cli_persists_baseline_on_first_capture(config, tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(yaml.safe_dump(config), encoding="utf-8")
    metrics = tmp_path / "m.json"
    metrics.write_text(json.dumps([{"category": "complexity", "metric_value": 14},
                                   {"category": "duplication", "metric_value": 3.0}]), encoding="utf-8")
    base = tmp_path / ".bob" / "baselines.json"
    cmd = [sys.executable, str(ROOT / "scripts" / "compute_gates.py"), "--config", str(cfg),
           "--role", "architect", "--metrics", str(metrics), "--baselines", str(base), "--tests-exit", "0"]
    subprocess.run(cmd, check=True, capture_output=True)
    assert json.loads(base.read_text()) == {"complexity": 14, "duplication": 3.0}
    worse = tmp_path / "w.json"
    worse.write_text(json.dumps([{"category": "complexity", "metric_value": 20},
                                 {"category": "duplication", "metric_value": 3.0}]), encoding="utf-8")
    cmd[cmd.index("--metrics") + 1] = str(worse)
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    g = next(r for r in json.loads(out.stdout) if r["gate"] == "complexity-baseline")
    assert g["passed"] is False and g["baseline"] == 14
