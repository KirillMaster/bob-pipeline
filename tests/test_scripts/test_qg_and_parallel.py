import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import bob_metrics  # noqa: E402
import constitution_trace  # noqa: E402
import parallel_plan  # noqa: E402
import parse_reports  # noqa: E402
import upgrade_project as up  # noqa: E402
from compute_gates import compute  # noqa: E402
from test_compute_gates import config as base_config  # noqa: E402,F401


# ── parallel_plan: batch (D17) ──
S = [
    {"id": "S1", "depends_on": [], "files": ["src/a"]},
    {"id": "S2", "depends_on": [], "files": ["src/b", "tests/b"]},
    {"id": "S3", "depends_on": [], "files": ["src/a/sub"]},
    {"id": "S4", "depends_on": ["S1"], "files": ["src/c"]},
    {"id": "S5", "depends_on": []},
]


def test_batch_picks_disjoint_independent_slices_up_to_limit():
    assert parallel_plan.batch(S, [], [], [], 3) == ["S1", "S2"]  # S3 overlaps S1, S4 waits, S5 has no files


def test_batch_respects_limit_and_running():
    assert parallel_plan.batch(S, [], [], [], 1) == ["S1"]
    assert parallel_plan.batch(S, [], ["S1"], [], 2) == ["S2"]


def test_batch_unlocks_dependents_after_merge_and_blocks_on_failed():
    assert "S4" in parallel_plan.batch(S, ["S1"], [], [], 3)
    assert "S4" not in parallel_plan.batch(S, [], [], ["S1"], 3)


def test_slice_without_files_runs_alone():
    assert parallel_plan.batch([{"id": "A"}, {"id": "B", "files": ["x"]}], [], [], [], 3) == ["A"]


def test_overlap_semantics():
    assert parallel_plan.overlaps("src/a", "src/a/b.cs")
    assert parallel_plan.overlaps("src\\a/", "./src/a")
    assert not parallel_plan.overlaps("src/a", "src/ab")


# ── parallel_plan: qa-rerun (D16) ──
QA = """# QA
## S1-AS1 Login ok
Run: dotnet test --filter Login
File: tests/LoginTests.cs
Expect: green
## S1-AS2 Totals
File: tests/Totals/TotalsTests.cs
Expect: 3 passed
"""


def test_qa_rerun_only_procedures_referencing_changed_files():
    assert parallel_plan.qa_rerun(["tests/LoginTests.cs"], [QA]) == ["S1-AS1"]
    assert parallel_plan.qa_rerun(["tests/Totals/TotalsTests.cs", "tests/LoginTests.cs"], [QA]) == ["S1-AS1", "S1-AS2"]
    assert parallel_plan.qa_rerun(["tests/Unrelated.cs"], [QA]) == []
    assert parallel_plan.qa_rerun([], [QA]) == []


def test_qa_rerun_matches_by_basename():
    assert parallel_plan.qa_rerun(["other/dir/TotalsTests.cs"], [QA]) == ["S1-AS2"]


# ── bob_metrics (D19) ──
def test_metrics_append_and_summarize(tmp_path):
    f = tmp_path / ".bob" / "metrics.jsonl"
    t = "2026-10-23T10:{:02d}:00Z"
    bob_metrics.append(f, bob_metrics.build_record("role", t.format(0), t.format(10), "coder", "S1", "pass"))
    bob_metrics.append(f, bob_metrics.build_record("role", t.format(10), t.format(12), "qa", "S1", "send-back", "naming"))
    bob_metrics.append(f, bob_metrics.build_record("role", t.format(12), t.format(14), "coder", "S1", "pass"))
    bob_metrics.append(f, bob_metrics.build_record("approval", t.format(0), t.format(5), what="gherkin"))
    f.write_text(f.read_text(encoding="utf-8") + '{"torn":', encoding="utf-8")
    out = bob_metrics.summarize(bob_metrics.load(f))
    assert out["roles"]["coder"]["runs"] == 2 and out["roles"]["coder"]["wall_s"] == 720.0
    assert out["roles"]["qa"]["send_backs"] == 1 and out["roles"]["qa"]["send_back_rate_pct"] == 100.0
    assert out["roles"]["coder"]["share_pct"] == pytest.approx(85.7, abs=0.1)
    assert out["approval_wait_s"] == 300.0
    assert out["slices"]["S1"]["reasons"] == ["naming"]


def test_metrics_role_record_requires_fields():
    with pytest.raises(ValueError):
        bob_metrics.build_record("role", "2026-10-23T10:00:00Z", "2026-10-23T10:01:00Z", role="coder")


def test_metrics_cli_roundtrip(tmp_path):
    f = tmp_path / "m.jsonl"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "bob_metrics.py"), "append", "--file", str(f),
                        "--kind", "role", "--role", "qa", "--slice", "S2", "--start", "2026-10-23T10:00:00Z",
                        "--end", "2026-10-23T10:00:30Z", "--verdict", "send-back", "--send-back-reason", "behavior"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert json.loads(f.read_text(encoding="utf-8"))["duration_s"] == 30.0
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "bob_metrics.py"), "summarize", str(f)], capture_output=True, text=True)
    assert json.loads(r.stdout)["roles"]["qa"]["send_backs"] == 1


# ── constitution_trace ──
def test_trace_requires_gate_condition_and_green_verified_by():
    c = {"principles": [
        {"id": "P1", "severity": "NON-NEGOTIABLE", "gate_condition": "x", "verified_by": ["ArchTests.NoCycles"]},
        {"id": "P2", "severity": "NON-NEGOTIABLE", "gate_condition": " "},
        {"id": "P3", "severity": "recommended", "gate_condition": ""},
        {"id": "P4", "severity": "NON-NEGOTIABLE", "gate_condition": "y"},
    ]}
    out = constitution_trace.trace(c, ["Ns.ArchTests.NoCycles [PASS]"])
    assert [d["id"] for d in out["details"]] == ["P2"]
    out = constitution_trace.trace(c, [])
    assert [d["id"] for d in out["details"]] == ["P1", "P2"]


def test_trace_missing_constitution_is_noop(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "constitution_trace.py"), "--constitution", str(tmp_path / "none.yaml")],
                       capture_output=True, text=True)
    assert json.loads(r.stdout)["metric_value"] == 0


# ── parsers ──
def test_exitcode_and_diffcover_and_hardening_parsers():
    assert parse_reports.PARSERS["exitcode-lint"]("1\nerror CS8618")["metric_value"] == 1
    assert parse_reports.PARSERS["exitcode-format"]("0\n")["category"] == "format"
    with pytest.raises(parse_reports.ParseError):
        parse_reports.PARSERS["exitcode-architecture"]("boom")
    assert parse_reports.PARSERS["diff-cover"]('{"total_percent_covered": 84.256}')["metric_value"] == 84.26
    assert parse_reports.PARSERS["hardening"]('{"unfixed_findings": 2}')["metric_value"] == 2


# ── compute_gates QG ──
QG_TOOLS = [
    {"stack": "csharp", "category": c, "tool": c, "run_command": "x", "report_parser": "p", "enabled": True}
    for c in ("lint", "format", "architecture")
] + [{"stack": "any", "category": c, "tool": c, "run_command": "x", "report_parser": "p", "enabled": True}
     for c in ("diff-coverage", "constitution-traceability")]


def qgcfg(cfg, **qg):
    cfg["tools"] += QG_TOOLS
    if qg:
        cfg["quality_gates"] = qg
    return cfg


def gate(results, name):
    return next(r for r in results if r["gate"] == name)


def test_coder_lint_blocks(base_config):
    cfg = qgcfg(base_config)
    res = compute(cfg, "coder", [{"category": "lint", "metric_value": 1}, {"category": "format", "metric_value": 0},
                                 {"category": "architecture", "metric_value": 0}], None, 0, None)
    assert gate(res, "lint")["passed"] is False and gate(res, "format")["passed"] is True


def test_qg_gate_without_tool_passes_with_note(base_config):
    res = compute(base_config, "coder", [], None, 0, None)
    g = gate(res, "lint")
    assert g["passed"] is True and "skipped" in g["diagnosis"]


def test_qg_disabled_globally_and_per_gate(base_config):
    cfg = qgcfg(base_config, enabled=False)
    assert gate(compute(cfg, "coder", [], None, 0, None), "architecture")["passed"] is True
    cfg = qgcfg(base_config, enabled=True, gates={"format": False})
    res = compute(cfg, "coder", [{"category": "lint", "metric_value": 0}, {"category": "architecture", "metric_value": 0}], None, 0, None)
    assert gate(res, "format")["passed"] is True and "disabled" in gate(res, "format")["diagnosis"]


def test_enabled_tool_with_missing_metric_fails(base_config):
    res = compute(qgcfg(base_config), "architect", [], None, 0, None)
    assert gate(res, "architecture")["passed"] is False


def test_merge_gate_diff_coverage_threshold_and_traceability(base_config):
    cfg = qgcfg(base_config, enabled=True, diff_coverage_min=85)
    low = compute(cfg, "merge-gate", [{"category": "diff-coverage", "metric_value": 84},
                                      {"category": "constitution-traceability", "metric_value": 0}], None, 0, None)
    assert gate(low, "diff-coverage")["passed"] is False and gate(low, "diff-coverage")["threshold"] == 85
    assert gate(low, "constitution-traceability")["passed"] is True
    base_config.pop("quality_gates")
    ok = compute(base_config, "merge-gate", [{"category": "diff-coverage", "metric_value": 80},
                                                    {"category": "constitution-traceability", "metric_value": 1}], None, 0, None)
    assert gate(ok, "diff-coverage")["passed"] is True  # default 80
    assert gate(ok, "constitution-traceability")["passed"] is False
    assert gate(ok, "tests-green")["passed"] is True


def test_hardening_findings_block_but_low_mutation_does_not(base_config):
    base_config["mutation"] = {"framework_enabled": True}
    res = compute(base_config, "hardener", [{"category": "hardening", "metric_value": 2},
                                            {"category": "mutation", "metric_value": 10}], None, 0, None)
    assert gate(res, "hardening-findings")["passed"] is False
    assert gate(res, "mutation-score")["passed"] is True
    assert compute(base_config, "hardener", [{"category": "hardening", "metric_value": 0}], None, 0, None)
    assert gate(compute(base_config, "hardener", [], None, 0, None), "hardening-findings")["passed"] is False


# ── registry / template / schema consistency ──
def test_registry_valid_and_has_qg_categories():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_config.py"), "--registry", str(ROOT / "registry" / "tool-registry.yaml")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    cats = {(e["stack"], e["category"]) for e in yaml.safe_load((ROOT / "registry" / "tool-registry.yaml").read_text(encoding="utf-8"))["entries"]}
    for c in ("lint", "format", "architecture"):
        assert ("csharp", c) in cats
    assert ("any", "diff-coverage") in cats and ("any", "constitution-traceability") in cats


# ── upgrade step qg ──
def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def csproj(tfm, extra=""):
    return f'<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>{tfm}</TargetFramework></PropertyGroup>{extra}</Project>'


def make_project(tmp_path, remote, with_legacy=False):
    git(tmp_path, "init", "-q")
    git(tmp_path, "remote", "add", "origin", remote)
    (tmp_path / "App").mkdir()
    (tmp_path / "App" / "App.csproj").write_text(csproj("net9.0"), encoding="utf-8")
    (tmp_path / "App.Tests").mkdir()
    (tmp_path / "App.Tests" / "App.Tests.csproj").write_text(csproj("net9.0", "<ItemGroup><PackageReference Include='Microsoft.NET.Test.Sdk' Version='17'/></ItemGroup>"), encoding="utf-8")
    if with_legacy:
        (tmp_path / "Old").mkdir()
        (tmp_path / "Old" / "Old.csproj").write_text(csproj("net48"), encoding="utf-8")
    (tmp_path / "App.sln").write_text("", encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    cfg = {"version": "1", "project_name": "p", "stack": "csharp",
           "roles": [{"name": r, "model": "sonnet", "enabled": True, "gates": ["tests-green"]} for r in ("specifier", "coder", "architect", "hardener", "qa")],
           "tools": [], "human_gates": {"gherkin_approval": True, "final_qa_report": True},
           "thresholds": {"mutation_score_min": 80, "coverage_policy": "informational", "complexity_policy": "off", "duplication_policy": "off"},
           "send_back_routes": {"qa": "coder"}, "return_limit": 3, "parallel_limit": 3, "night_mode_default": False}
    (tmp_path / ".claude" / "bob-pipeline.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (tmp_path / ".specify" / "memory").mkdir(parents=True)
    (tmp_path / ".specify" / "memory" / "constitution.yaml").write_text(
        'project_name: "p"\nversion: "1.0.0"\nratified: "2026-01-01"\nlast_amended: "2026-01-01"\nprinciples:\n'
        '  - id: "P1"\n    name: "n"\n    description: "d"\n    severity: "NON-NEGOTIABLE"\n    gate_condition: "g"\n', encoding="utf-8")


def test_classify_tfm():
    assert up.classify_tfm("net8.0") == "modern" and up.classify_tfm("net10.0") == "modern"
    assert up.classify_tfm("net48") == "legacy" and up.classify_tfm("net472") == "legacy"
    assert up.classify_tfm("netstandard2.0") == "other" and up.classify_tfm("net6.0") == "other"


def test_qg_step_pet_project(tmp_path):
    make_project(tmp_path, "https://github.com/KirillMaster/x.git", with_legacy=True)
    report = up.run(tmp_path, ROOT, False, {"qg"}, [])
    qg = report["steps"]["qg"]
    assert qg["flavor"] == "pet"
    assert qg["csharp"]["skipped_legacy"] == ["Old/Old.csproj"]
    props = (tmp_path / "Directory.Build.props").read_text(encoding="utf-8")
    assert "KirillMaster.QualityGates.Build" in props and "VersionGreaterThanOrEquals" in props
    arch = tmp_path / "tests" / "App.Architecture.Tests"
    assert "KirillMaster.QualityGates.Architecture" in (arch / "App.Architecture.Tests.csproj").read_text(encoding="utf-8")
    assert '"App"' in (arch / "ArchitectureTests.cs").read_text(encoding="utf-8")
    assert "App.Tests" not in (arch / "ArchitectureTests.cs").read_text(encoding="utf-8")
    cons = yaml.safe_load((tmp_path / ".specify" / "memory" / "constitution.yaml").read_text(encoding="utf-8"))
    ids = [p["id"] for p in cons["principles"]]
    assert ids == ["P1", "P2", "P3", "P4", "P5"] and cons["principles"][1]["severity"] == "NON-NEGOTIABLE"
    cfg = yaml.safe_load((tmp_path / ".claude" / "bob-pipeline.yaml").read_text(encoding="utf-8"))
    assert {t["category"] for t in cfg["tools"]} >= {"lint", "format", "architecture", "diff-coverage", "constitution-traceability"}
    assert "lint" in next(r for r in cfg["roles"] if r["name"] == "coder")["gates"]
    assert "hardening-findings" in next(r for r in cfg["roles"] if r["name"] == "hardener")["gates"]
    assert cfg["mutation"] == {"framework_enabled": False}
    assert (tmp_path / ".claude" / "bob-pipeline.yaml.bak-pre-1.3").exists()
    # idempotent
    again = up.run(tmp_path, ROOT, False, {"qg"}, [])["steps"]["qg"]
    assert again["csharp"]["directory_build_props"] == "already wired"
    assert again["csharp"]["arch_tests"] == "exists" and again["config"] == []
    assert again["constitution"]["added"] == []


def test_qg_step_tenengroup_packages_and_dry_run(tmp_path):
    make_project(tmp_path, "git@github.com:tenengroup/svc.git")
    report = up.run(tmp_path, ROOT, True, {"qg"}, [], qg_version="1.2.3")
    assert report["steps"]["qg"]["flavor"] == "tenengroup"
    assert not (tmp_path / "Directory.Build.props").exists() and not (tmp_path / "tests").exists()
    assert report["steps"]["qg"]["config"]
    up.run(tmp_path, ROOT, False, {"qg"}, [], qg_version="1.2.3")
    props = (tmp_path / "Directory.Build.props").read_text(encoding="utf-8")
    assert "TenenGroup.QualityGates.Build" in props and 'Version="1.2.3"' in props


def test_qg_patches_existing_directory_build_props(tmp_path):
    make_project(tmp_path, "https://github.com/KirillMaster/x.git")
    (tmp_path / "Directory.Build.props").write_text("<Project>\n  <PropertyGroup><Nullable>enable</Nullable></PropertyGroup>\n</Project>\n", encoding="utf-8")
    up.run(tmp_path, ROOT, False, {"qg"}, [])
    text = (tmp_path / "Directory.Build.props").read_text(encoding="utf-8")
    assert "<Nullable>enable</Nullable>" in text and "KirillMaster.QualityGates.Build" in text


def test_qg_not_in_default_steps():
    assert "qg" not in up.DEFAULT_STEPS.split(",")
