import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "parse_reports.py"

sys.path.insert(0, str(ROOT / "scripts"))
import parse_reports  # noqa: E402


def run(parser, content, tmp_path, suffix=".txt"):
    f = tmp_path / f"report{suffix}"
    f.write_text(content, encoding="utf-8")
    return subprocess.run([sys.executable, str(SCRIPT), parser, str(f)],
                          capture_output=True, text=True)


def test_stryker_mutation_score_field():
    out = parse_reports.parse_stryker(json.dumps({"mutationScore": 72.5}))
    assert out == {"category": "mutation", "metric": "mutation_score", "metric_value": 72.5}


def test_stryker_schema_format_computed():
    report = {"files": {"a.cs": {"mutants": [
        {"status": "Killed"}, {"status": "Killed"}, {"status": "Survived"}, {"status": "Timeout"},
    ]}}}
    out = parse_reports.parse_stryker(json.dumps(report))
    assert out["metric_value"] == 75.0


def test_mutmut_summary():
    out = parse_reports.parse_mutmut("Killed 8 out of stuff\nSurvived 2\n")
    assert out["metric_value"] == 80.0


def test_pit_xml():
    xml = """<mutations>
      <mutation detected='true'/><mutation detected='true'/>
      <mutation detected='true'/><mutation detected='false'/>
    </mutations>"""
    out = parse_reports.parse_pit(xml)
    assert out["metric_value"] == 75.0


def test_cobertura():
    out = parse_reports.parse_cobertura("<coverage line-rate='0.914'></coverage>")
    assert out == {"category": "coverage", "metric": "line_coverage", "metric_value": 91.4}


def test_lcov():
    out = parse_reports.parse_lcov("SF:a.ts\nLF:10\nLH:9\nend_of_record\nSF:b.ts\nLF:10\nLH:5\nend_of_record\n")
    assert out["metric_value"] == 70.0


def test_jacoco():
    xml = "<report><counter type='LINE' missed='5' covered='15'/></report>"
    out = parse_reports.parse_jacoco(xml)
    assert out["metric_value"] == 75.0


def test_lizard_max_ccn():
    csv_text = "12,3,60,2,14,foo@1-14@a.py,a.py,foo,foo(),1,14\n30,11,200,1,40,bar@1-40@b.py,b.py,bar,bar(),1,40\n"
    out = parse_reports.parse_lizard(csv_text)
    assert out == {"category": "complexity", "metric": "max_ccn", "metric_value": 11}


def test_jscpd():
    out = parse_reports.parse_jscpd(json.dumps({"statistics": {"total": {"percentage": 4.2}}}))
    assert out["metric_value"] == 4.2


@pytest.mark.parametrize("parser,content", [
    ("stryker", "{}"),
    ("mutmut", "no mutants here"),
    ("pit", "<mutations></mutations>"),
    ("cobertura", "<coverage></coverage>"),
    ("lcov", "SF:a.ts\nend_of_record\n"),
    ("jscpd", "{}"),
    ("lizard", ""),
])
def test_malformed_reports_exit_nonzero(parser, content, tmp_path):
    r = run(parser, content, tmp_path)
    assert r.returncode == 1
    assert "error" in json.loads(r.stderr)


def test_cli_happy_path(tmp_path):
    r = run("stryker", json.dumps({"mutationScore": 90}), tmp_path, ".json")
    assert r.returncode == 0
    assert json.loads(r.stdout)["metric_value"] == 90.0
