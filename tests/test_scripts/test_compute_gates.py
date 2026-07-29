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


def test_mutation_below_threshold_fails_with_diagnosis(config):
    results = compute(config, "hardener", [{"category": "mutation", "metric_value": 72}], None, 0, None)
    g = gate(results, "mutation-score")
    assert g["passed"] is False
    assert "72" in g["diagnosis"] and "80" in g["diagnosis"]


def test_mutation_at_threshold_passes(config):
    results = compute(config, "hardener", [{"category": "mutation", "metric_value": 80}], None, 0, None)
    assert gate(results, "mutation-score")["passed"] is True


def test_coverage_is_informational_never_blocks(config):
    results = compute(config, "hardener",
                      [{"category": "mutation", "metric_value": 95},
                       {"category": "coverage", "metric_value": 10}], None, 0, None)
    cov = gate(results, "coverage-informational")
    assert cov["passed"] is True
    assert all(r["passed"] for r in results)


def test_complexity_equal_to_baseline_passes(config):
    results = compute(config, "cleaner", [{"category": "complexity", "metric_value": 11},
                                          {"category": "duplication", "metric_value": 3.0}],
                      {"complexity": 11, "duplication": 3.0}, 0, None)
    assert gate(results, "complexity-baseline")["passed"] is True
    assert gate(results, "duplication-baseline")["passed"] is True


def test_complexity_worse_than_baseline_fails(config):
    results = compute(config, "cleaner", [{"category": "complexity", "metric_value": 14},
                                          {"category": "duplication", "metric_value": 3.0}],
                      {"complexity": 11, "duplication": 3.0}, 0, None)
    g = gate(results, "complexity-baseline")
    assert g["passed"] is False
    assert "baseline" in g["diagnosis"]


def test_first_run_without_baseline_passes_and_notes_capture(config):
    results = compute(config, "cleaner", [{"category": "complexity", "metric_value": 14},
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
    assert "degraded" in g["diagnosis"]


def test_missing_mutation_metric_fails(config):
    results = compute(config, "hardener", [], None, 0, None)
    assert gate(results, "mutation-score")["passed"] is False
