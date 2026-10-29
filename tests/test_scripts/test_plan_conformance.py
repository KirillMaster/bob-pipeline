import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import compute_gates as cg  # noqa: E402
import parallel_plan as pp  # noqa: E402
import plan_conformance as pc  # noqa: E402

SCRIPT = ROOT / "scripts" / "plan_conformance.py"
MANIFEST = {
    "slices": [{
        "slice": "S1",
        "feature_module": "Billing",
        "allowed_paths": ["src/Billing/**", "tests/Billing.Tests/**"],
        "new_types": [{"name": "Invoice", "module": "Billing", "kind": "record"}],
        "allowed_new_edges": ["Billing -> Core"],
        "locked_tests": ["tests/Billing.Tests/Locked/**"],
    }]
}


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True, text=True)


def write(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    write(repo, "src/Billing/Existing.cs", "namespace Billing;\npublic class Existing { }\n")
    write(repo, "tests/Billing.Tests/Locked/LockedTests.cs", "public class LockedTests { }\n")
    write(repo, ".bob/baselines.json", "{}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return repo, base


def gate(tmp_path, repo, base, config=None):
    mf = tmp_path / "manifest.yaml"
    mf.write_text(yaml.safe_dump(MANIFEST), encoding="utf-8")
    cmd = [sys.executable, str(SCRIPT), "--manifest", str(mf), "--slice", "S1", "--repo", str(repo), "--base", base]
    if config:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(yaml.safe_dump(config), encoding="utf-8")
        cmd += ["--config", str(cfg)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r, (json.loads(r.stdout) if r.stdout.strip() else None)


def commit(repo):
    git(repo, "add", "-A", "-f")
    git(repo, "commit", "-q", "-m", "coder")


def rules(report):
    return sorted({o["rule"] for o in report["offenders"]})


def test_clean_diff_passes(tmp_path):
    repo, base = make_repo(tmp_path)
    write(repo, "src/Billing/Invoice.cs", "namespace Billing;\npublic sealed record Invoice(int Id);\n")
    write(repo, "tests/Billing.Tests/InvoiceTests.cs", "public class InvoiceTests { }\n")
    commit(repo)
    r, rep = gate(tmp_path, repo, base)
    assert r.returncode == 0, r.stdout
    assert rep["passed"] and rep["offenders"] == []
    assert rep["allowed_new_edges"] == ["Billing -> Core"]


def test_out_of_scope_file_fails_with_fix(tmp_path):
    repo, base = make_repo(tmp_path)
    write(repo, "src/Other/Thing.cs", "// x\n")
    commit(repo)
    r, rep = gate(tmp_path, repo, base)
    assert r.returncode == 1
    assert rules(rep) == ["out-of-scope"]
    assert rep["offenders"][0]["path"] == "src/Other/Thing.cs" and rep["offenders"][0]["fix"]


def test_undeclared_type_fails(tmp_path):
    repo, base = make_repo(tmp_path)
    write(repo, "src/Billing/Helper.cs", "namespace Billing;\ninternal static class Helper { }\n")
    commit(repo)
    r, rep = gate(tmp_path, repo, base)
    assert r.returncode == 1 and rules(rep) == ["undeclared-type"]
    assert "Helper" in rep["offenders"][0]["detail"]


def test_declared_type_with_wrong_kind_fails(tmp_path):
    repo, base = make_repo(tmp_path)
    write(repo, "src/Billing/Invoice.cs", "namespace Billing;\npublic class Invoice { }\n")
    commit(repo)
    r, rep = gate(tmp_path, repo, base)
    assert r.returncode == 1 and rules(rep) == ["undeclared-type"]


def test_nested_and_existing_types_are_not_new(tmp_path):
    repo, base = make_repo(tmp_path)
    write(repo, "src/Billing/Existing.cs", "namespace Billing;\npublic class Existing\n{\n    private class Inner { }\n}\n")
    commit(repo)
    r, rep = gate(tmp_path, repo, base)
    assert r.returncode == 0, r.stdout


def test_locked_test_edit_fails(tmp_path):
    repo, base = make_repo(tmp_path)
    write(repo, "tests/Billing.Tests/Locked/LockedTests.cs", "public class LockedTests { /* relaxed */ }\n")
    commit(repo)
    r, rep = gate(tmp_path, repo, base)
    assert r.returncode == 1 and rules(rep) == ["locked-test"]


def test_baseline_and_config_edit_fails(tmp_path):
    repo, base = make_repo(tmp_path)
    write(repo, ".bob/baselines.json", '{"complexity": 99}\n')
    write(repo, "src/Billing/complexity-baseline.json", "{}\n")
    commit(repo)
    r, rep = gate(tmp_path, repo, base)
    assert r.returncode == 1 and rules(rep) == ["protected"]
    assert len(rep["offenders"]) == 2


def test_config_protected_paths_and_module_mapping(tmp_path):
    repo, base = make_repo(tmp_path)
    write(repo, "src/Billing/ArchLayout.json", "{}\n")
    write(repo, "src/Billing/Invoice.cs", "namespace Billing;\npublic record Invoice(int Id);\n")
    commit(repo)
    cfg = {"plan_conformance": {"protected_paths": ["src/Billing/ArchLayout.json"], "module_paths": {"Billing": ["src/Billing/Domain/**"]}}}
    r, rep = gate(tmp_path, repo, base, cfg)
    assert r.returncode == 1 and rules(rep) == ["module-mismatch", "protected"]


def test_edge_check_command_failure_fails_gate(tmp_path):
    repo, base = make_repo(tmp_path)
    write(repo, "src/Billing/Invoice.cs", "namespace Billing;\npublic record Invoice(int Id);\n")
    commit(repo)
    ok, _ = gate(tmp_path, repo, base, {"plan_conformance": {"edge_check_command": f'"{sys.executable}" -c "import sys; sys.exit(0)"'}})
    assert ok.returncode == 0
    r, rep = gate(tmp_path, repo, base, {"plan_conformance": {"edge_check_command": f'"{sys.executable}" -c "import sys; sys.exit(3)"'}})
    assert r.returncode == 1 and rules(rep) == ["edge-check"]


def test_type_detection_per_language():
    assert pc.declared_types("a.ts", "export interface A {}\nexport type B = string;\n  class Nested {}\nenum C {}\n") == {"A": "interface", "B": "type", "C": "enum"}
    assert pc.declared_types("a.py", "class A:\n    class Inner:\n        pass\n") == {"A": "class"}
    assert pc.declared_types("A.cs", "namespace X\n{\n    public struct S { }\n    public record struct R(int a);\n        class Deep { }\n}\n") == {"S": "struct", "R": "record"}
    assert pc.declared_types("a.md", "class Foo") == {}


def test_glob_semantics():
    assert pc.matches("src/a/b/c.cs", ["src/**"]) and pc.matches("src/c.cs", ["src/**/*.cs"])
    assert not pc.matches("src/a/c.cs", ["src/*.cs"]) and pc.matches("tests/x/y.cs", ["tests/"])


def test_bad_manifest_is_usage_error(tmp_path):
    repo, base = make_repo(tmp_path)
    mf = tmp_path / "bad.yaml"
    mf.write_text("slices: [{slice: S1}]\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(mf), "--slice", "S1", "--repo", str(repo), "--base", base],
                       capture_output=True, text=True)
    assert r.returncode == 2


def test_compute_gates_plan_conformance_gate():
    config = yaml.safe_load((ROOT / "templates" / "bob-pipeline.yaml").read_text(encoding="utf-8")
                            .replace("{{PROJECT_NAME}}", "p").replace("{{STACK}}", "python")
                            .replace("{{TESTS_RUN_COMMAND}}", "pytest").replace("{{TESTS_SCOPED_COMMAND}}", "pytest -k {filter}")
                            .replace("{{TESTS_COVERAGE_COMMAND}}", "pytest --cov").replace("{{TOOLS}}", "[]"))
    coder = next(r for r in config["roles"] if r["name"] == "coder")
    assert coder["gates"][0] == "plan-conformance"
    assert config["plan_conformance"]["enabled"] is True

    def plan_gate(report, cfg=config):
        res = cg.compute(cfg, "coder", [], None, 0, None, plan_conformance=report)
        return next(g for g in res if g["gate"] == "plan-conformance")

    assert plan_gate({"passed": True, "offenders": []})["passed"]
    red = plan_gate({"passed": False, "offenders": [{"rule": "protected", "path": "a", "fix": "revert a"}]})
    assert not red["passed"] and "revert a" in red["diagnosis"]
    assert not plan_gate(None)["passed"]
    off = {**config, "plan_conformance": {"enabled": False}}
    assert plan_gate(None, off)["passed"]


def test_escalation_decision():
    esc = {"max_red_iterations": 3, "on_exhaust": "stronger_model", "escalation_model": "opus"}
    assert pp.escalate(esc, 2)["escalate"] is False
    assert pp.escalate(esc, 3) == {"escalate": True, "red_iterations": 3, "limit": 3, "action": "stronger_model", "model": "opus"}
    assert pp.escalate({"max_red_iterations": 2, "on_exhaust": "specifier"}, 2)["action"] == "specifier"
    assert pp.escalate(None, 9) == {"escalate": False}


VALIDATOR = ROOT / "scripts" / "validate_config.py"


def _config_text(extra=""):
    text = ((ROOT / "templates" / "bob-pipeline.yaml").read_text(encoding="utf-8")
            .replace("{{PROJECT_NAME}}", "p").replace("{{STACK}}", "python")
            .replace("{{TESTS_RUN_COMMAND}}", "pytest").replace("{{TESTS_SCOPED_COMMAND}}", "pytest -k {filter}")
            .replace("{{TESTS_COVERAGE_COMMAND}}", "pytest --cov").replace("{{TOOLS}}", "[]"))
    return text + extra


def _validate(tmp_path, text):
    f = tmp_path / "c.yaml"
    f.write_text(text, encoding="utf-8")
    return subprocess.run([sys.executable, str(VALIDATOR), str(f)], capture_output=True, text=True)


def test_template_with_plan_sections_validates(tmp_path):
    r = _validate(tmp_path, _config_text())
    assert r.returncode == 0, r.stderr


def test_cheap_coder_and_escalation_model_validate(tmp_path):
    text = _config_text().replace("name: coder\n    model: sonnet", "name: coder\n    model: haiku")
    text = text.replace("on_exhaust: specifier", "on_exhaust: stronger_model\n  escalation_model: opus")
    assert _validate(tmp_path, text).returncode == 0


def test_stronger_model_without_escalation_model_rejected(tmp_path):
    r = _validate(tmp_path, _config_text().replace("on_exhaust: specifier", "on_exhaust: stronger_model"))
    assert r.returncode == 1 and "escalation_model" in r.stderr


def test_bad_escalation_and_plan_keys_rejected(tmp_path):
    assert _validate(tmp_path, _config_text().replace("on_exhaust: specifier", "on_exhaust: ignore")).returncode == 1
    assert _validate(tmp_path, _config_text().replace("max_red_iterations: 3", "max_red_iterations: 0")).returncode == 1
    assert _validate(tmp_path, _config_text().replace("  enabled: true\n  # protected_paths", "  enabled: true\n  bogus: 1\n  # protected_paths")).returncode == 1


def test_manifest_template_matches_schema():
    import jsonschema
    schema = json.loads((ROOT / "schemas" / "slice-manifest.schema.json").read_text(encoding="utf-8"))
    data = yaml.safe_load((ROOT / "templates" / "slice-manifest.yaml").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(data)
    bad = {"slices": [{**data["slices"][0], "new_types": [{"name": "A", "module": "M", "kind": "widget"}]}]}
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(bad))


def test_upgrade_plan_step_adds_keys_and_is_idempotent():
    import upgrade_project as up
    cfg = yaml.safe_load(_config_text())
    cfg.pop("plan_conformance")
    cfg.pop("escalation")
    next(r for r in cfg["roles"] if r["name"] == "coder")["gates"].remove("plan-conformance")
    cfg, changes = up.migrate_plan_config(cfg)
    assert len(changes) == 6  # 3 plan keys + the 1.9.0 coder gates (bugfix, tidy-first, adr)
    assert next(r for r in cfg["roles"] if r["name"] == "coder")["gates"][0] == "plan-conformance"
    assert cfg["escalation"] == {"max_red_iterations": 3, "on_exhaust": "specifier"}
    assert up.migrate_plan_config(cfg)[1] == []


def test_upgrade_project_plan_step_writes_backup(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    cfg = yaml.safe_load(_config_text())
    cfg.pop("plan_conformance")
    next(r for r in cfg["roles"] if r["name"] == "coder")["gates"].remove("plan-conformance")
    (proj / ".claude" / "bob-pipeline.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "upgrade_project.py"), "--project", str(proj), "--steps", "plan"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (proj / ".claude" / "bob-pipeline.yaml.bak-1.7").exists()
    new = yaml.safe_load((proj / ".claude" / "bob-pipeline.yaml").read_text(encoding="utf-8"))
    assert new["plan_conformance"]["enabled"] is True
