import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import bugfix_gates as bg  # noqa: E402
import compute_gates as cg  # noqa: E402
import tidy_first as tf  # noqa: E402

SCRIPTS = ROOT / "scripts"
CALC = "src/Billing/Calc.cs"
REGRESSION = "tests/Billing.Tests/RegressionTests.cs"
ALWAYS_RED = 'python -c "import sys; sys.exit(1)"'
ALWAYS_GREEN = 'python -c "pass"'
FIXED_ONLY = 'python -c "import sys; sys.exit(0 if \'fixed\' in open(\'src/Billing/Calc.cs\').read() else 1)"'
BASE_CALC = "namespace Billing;\npublic class Calc {\n    public int Add(int a, int b) { return a - b; }\n" + "    // filler\n" * 6 + "    private int noise = 1;\n}\n"
FIXED_CALC = BASE_CALC.replace("return a - b;", "return a + b; /* fixed */")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def write(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def commit(repo, msg="coder"):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    write(repo, CALC, BASE_CALC)
    write(repo, "tests/Billing.Tests/CalcTests.cs", "[Fact]\npublic void Adds() {\n    Assert.Equal(5, Calc.Add(2, 3));\n}\n")
    write(repo, REGRESSION, "[Fact]\npublic void Add_returns_sum() {\n    Assert.Equal(7, Calc.Add(3, 4));\n}\n")
    commit(repo, "base")
    return repo, git(repo, "rev-parse", "HEAD")


def manifest(**over):
    slice_ = {"slice": "S1", "feature_module": "Billing", "kind": "bugfix",
              "allowed_paths": ["src/Billing/**", "tests/Billing.Tests/**"], "new_types": [], "allowed_new_edges": [],
              "locked_tests": [REGRESSION], "root_cause": f"{CALC}#Add", "regression_test": [REGRESSION]}
    slice_.update(over)
    slice_ = {k: v for k, v in slice_.items() if v is not None}
    return {"slices": [slice_]}


def run_script(tmp_path, script, repo, base=None, mf=None, config=None, extra=()):
    cmd = [sys.executable, str(SCRIPTS / script)] + ([] if script == "pr_description.py" else ["--repo", str(repo)])
    if base:
        cmd += ["--base", base]
    if mf is not None:
        p = tmp_path / "manifest.yaml"
        p.write_text(yaml.safe_dump(mf), encoding="utf-8")
        cmd += ["--manifest", str(p), "--slice", "S1"]
    if config is not None:
        c = tmp_path / "cfg.yaml"
        c.write_text(yaml.safe_dump(config), encoding="utf-8")
        cmd += ["--config", str(c)]
    r = subprocess.run(cmd + list(extra), capture_output=True, text=True)
    return r, (json.loads(r.stdout) if r.stdout.strip() else None)


def rules(report):
    return sorted({o["rule"] for o in report["offenders"]})


def test_bugfix_clean_fix_passes(tmp_path):
    repo, base = make_repo(tmp_path)
    write(repo, CALC, FIXED_CALC)
    commit(repo)
    r, rep = run_script(tmp_path, "bugfix_gates.py", repo, base, manifest())
    assert r.returncode == 0, r.stdout
    assert rep["applicable"] and rep["files"] == [CALC]


def test_non_bugfix_slice_is_not_applicable(tmp_path):
    repo, base = make_repo(tmp_path)
    mf = manifest()
    del mf["slices"][0]["kind"]
    r, rep = run_script(tmp_path, "bugfix_gates.py", repo, base, mf)
    assert r.returncode == 0 and rep["applicable"] is False


def test_bugfix_offenders_k1_k4_k5_k7_k8(tmp_path):
    repo, base = make_repo(tmp_path)
    write(repo, "src/Billing/Other.cs", "namespace Billing;\npublic class Other {\n    public int Extra(int a) { return a; } // TODO temporary hack\n}\n")
    write(repo, "src/Billing/More.cs", "namespace Billing;\nclass More { }\n")
    write(repo, "src/Billing/Third.cs", "namespace Billing;\nclass Third { }\n")
    write(repo, "tests/Billing.Tests/CalcTests.cs", "[Fact]\npublic void Adds() {\n    Assert.Equal(6, Calc.Add(2, 3));\n}\n")
    commit(repo)
    r, rep = run_script(tmp_path, "bugfix_gates.py", repo, base, manifest(new_types=[{"name": "Other", "module": "Billing", "kind": "class"}]))
    assert r.returncode == 1
    assert rules(rep) == ["budget", "new-signature", "new-type", "root-cause-untouched", "temp-marker", "test-edited"]
    assert all(o["fix"] for o in rep["offenders"])


def test_bugfix_waivers_and_budget_override(tmp_path):
    repo, base = make_repo(tmp_path)
    write(repo, "src/Billing/Other.cs", "namespace Billing;\npublic class Other {\n    public int Extra(int a) { return a; } // TODO later\n}\n")
    write(repo, CALC, FIXED_CALC)
    commit(repo)
    mf = manifest(allow=["new-api", "marker"], budget={"max_files": 3})
    r, rep = run_script(tmp_path, "bugfix_gates.py", repo, base, mf)
    assert rules(rep) == ["budget"] and "without reason" in rep["offenders"][0]["detail"]
    mf = manifest(allow=["new-api", "marker"], budget={"max_files": 3, "reason": "two call sites"})
    r, rep = run_script(tmp_path, "bugfix_gates.py", repo, base, mf)
    assert r.returncode == 0, r.stdout


def test_bugfix_regression_rules(tmp_path):
    repo, base = make_repo(tmp_path)
    write(repo, CALC, FIXED_CALC)
    commit(repo)
    offenders, _ = bg.check(manifest(regression_test=None, root_cause=None)["slices"][0], repo, base, "HEAD")
    assert sorted(o["rule"] for o in offenders) == ["missing-regression", "missing-root-cause"]
    r, rep = run_script(tmp_path, "bugfix_gates.py", repo, base, manifest(root_cause=None))
    assert r.returncode == 2
    r, rep = run_script(tmp_path, "bugfix_gates.py", repo, base, manifest(regression_test=None, test_exempt="config only"))
    assert r.returncode == 0
    r, rep = run_script(tmp_path, "bugfix_gates.py", repo, base, manifest(regression_test=["tests/Billing.Tests/Missing.cs"], locked_tests=["tests/Billing.Tests/Missing.cs"]))
    assert rules(rep) == ["missing-regression"]
    r, rep = run_script(tmp_path, "bugfix_gates.py", repo, base, manifest(locked_tests=[]))
    assert "not in locked_tests" in rep["offenders"][0]["detail"]


def test_bugfix_run_tests_red_on_base_green_on_head(tmp_path):
    repo, base = make_repo(tmp_path)
    write(repo, CALC, FIXED_CALC)
    commit(repo)
    cfg = {"bugfix": {"test_command": FIXED_ONLY, "runs": 1}}
    r, rep = run_script(tmp_path, "bugfix_gates.py", repo, base, manifest(), cfg, ["--run-tests"])
    assert r.returncode == 0, r.stdout
    cfg["bugfix"]["test_command"] = ALWAYS_GREEN
    r, rep = run_script(tmp_path, "bugfix_gates.py", repo, base, manifest(), cfg, ["--run-tests"])
    assert rules(rep) == ["fix-not-needed"]
    cfg["bugfix"]["test_command"] = ALWAYS_RED
    r, rep = run_script(tmp_path, "bugfix_gates.py", repo, base, manifest(), cfg, ["--run-tests"])
    assert rules(rep) == ["regression-red"]
    assert git(repo, "worktree", "list").count("\n") == 0


def test_ablation_flags_unneeded_hunk(tmp_path):
    repo, base = make_repo(tmp_path)
    write(repo, CALC, FIXED_CALC.replace("noise = 1", "noise = 2"))
    commit(repo)
    cfg = {"bugfix": {"test_command": FIXED_ONLY, "ablation": "hard"}}
    r, rep = run_script(tmp_path, "bugfix_ablation.py", repo, base, manifest(), cfg)
    assert r.returncode == 1, r.stdout
    assert [o["rule"] for o in rep["offenders"]] == ["unnecessary-hunk"] and rep["offenders"][0]["path"].startswith(CALC)
    cfg["bugfix"]["ablation"] = "warn"
    r, rep = run_script(tmp_path, "bugfix_ablation.py", repo, base, manifest(), cfg)
    assert r.returncode == 0 and len(rep["warnings"]) == 1 and rep["offenders"] == []
    r, rep = run_script(tmp_path, "bugfix_ablation.py", repo, base, manifest(allow=["refactor"]), {"bugfix": {"test_command": FIXED_ONLY, "ablation": "hard"}})
    assert r.returncode == 0 and rep["applicable"] is False


def test_tidy_first_structural_commits(tmp_path):
    repo, base = make_repo(tmp_path)
    write(repo, CALC, BASE_CALC.replace("noise", "renamed"))
    commit(repo, "tidy: rename field")
    r, rep = run_script(tmp_path, "tidy_first.py", repo, base)
    assert r.returncode == 0 and rep["structural"] == 1
    write(repo, "tests/Billing.Tests/CalcTests.cs", "[Fact]\npublic void Adds() {\n    Assert.Equal(6, Calc.Add(2, 3));\n}\n")
    commit(repo, "fix: change assertion")
    assert run_script(tmp_path, "tidy_first.py", repo, base)[0].returncode == 0
    write(repo, "tests/Billing.Tests/CalcTests.cs", "[Fact]\npublic void Adds() {\n    Assert.Equal(7, Calc.Add(2, 3));\n}\n")
    write(repo, "tests/Billing.Tests/NewTests.cs", "[Fact]\npublic void Brand_new() { }\n")
    commit(repo, "refactor(core): simplify")
    r, rep = run_script(tmp_path, "tidy_first.py", repo, base)
    assert r.returncode == 1 and rules(rep) == ["structural-adds-test", "structural-edits-assertion"]
    assert tf.is_structural("Format: x", tf.DEFAULT_PREFIXES) and not tf.is_structural("fix: x", tf.DEFAULT_PREFIXES)


def test_tidy_first_structural_slice_checks_every_commit(tmp_path):
    repo, base = make_repo(tmp_path)
    write(repo, "tests/Billing.Tests/NewTests.cs", "[Fact]\npublic void Brand_new() { }\n")
    commit(repo, "add test")
    assert run_script(tmp_path, "tidy_first.py", repo, base)[0].returncode == 0
    r, rep = run_script(tmp_path, "tidy_first.py", repo, base, manifest(structural=True))
    assert r.returncode == 1 and rules(rep) == ["structural-adds-test"]


def test_pr_description_purpose_and_markdown(tmp_path):
    types = [{"name": "Invoice", "module": "Billing", "kind": "record"}]
    mf = manifest(kind="feature", new_types=types)
    out = tmp_path / "body.md"
    r, rep = run_script(tmp_path, "pr_description.py", tmp_path, mf=mf, extra=["--out", str(out)])
    assert r.returncode == 1 and rules(rep) == ["missing-purpose"] and "**missing**" in rep["markdown"]
    types[0]["purpose"] = "Holds the billed amount for one order."
    r, rep = run_script(tmp_path, "pr_description.py", tmp_path, mf=manifest(kind="feature", new_types=types), extra=["--out", str(out)])
    assert r.returncode == 0 and "Holds the billed amount" in out.read_text(encoding="utf-8")
    r, rep = run_script(tmp_path, "pr_description.py", tmp_path, mf=mf, config={"pr_description": {"require_purpose": False}})
    assert r.returncode == 0


def test_pr_description_bugfix_section(tmp_path):
    r, rep = run_script(tmp_path, "pr_description.py", tmp_path, mf=manifest())
    assert f"Root cause: `{CALC}#Add`" in rep["markdown"] and REGRESSION in rep["markdown"]


ADR = "# ADR 7\n\n## Context\nWe need a port.\n\n## Decision\nAdd IClock.\n\n## Alternatives considered\nStatic DateTime.\n"


def test_adr_gate(tmp_path):
    repo, base = make_repo(tmp_path)
    iface = [{"name": "IClock", "module": "Billing", "kind": "interface"}]
    r, rep = run_script(tmp_path, "adr_gate.py", repo, mf=manifest(kind="feature", new_types=iface))
    assert r.returncode == 1 and rules(rep) == ["adr-missing"]
    r, rep = run_script(tmp_path, "adr_gate.py", repo, mf=manifest(kind="feature"))
    assert r.returncode == 0 and rep["applicable"] is False
    r, rep = run_script(tmp_path, "adr_gate.py", repo, mf=manifest(new_types=iface, adr_exempt="spike"))
    assert r.returncode == 0
    mf = manifest(allowed_new_edges=["Billing -> Core"], adr="docs/adr/0007-clock.md")
    assert rules(run_script(tmp_path, "adr_gate.py", repo, mf=mf)[1]) == ["adr-not-found"]
    assert rules(run_script(tmp_path, "adr_gate.py", repo, mf=manifest(allowed_new_edges=["A -> B"], adr="notes/x.md"))[1]) == ["adr-bad-path"]
    write(repo, "docs/adr/0007-clock.md", ADR.replace("Static DateTime.\n", ""))
    commit(repo, "adr")
    assert rules(run_script(tmp_path, "adr_gate.py", repo, mf=mf)[1]) == ["adr-incomplete"]
    write(repo, "docs/adr/0007-clock.md", ADR)
    commit(repo, "adr complete")
    r, rep = run_script(tmp_path, "adr_gate.py", repo, mf=mf)
    assert r.returncode == 0 and rep["triggers"] == ["new module edge"]
    r, rep = run_script(tmp_path, "adr_gate.py", repo, mf=manifest(new_types=iface), config={"adr": {"required": False}})
    assert r.returncode == 0


def _config():
    text = ((ROOT / "templates" / "bob-pipeline.yaml").read_text(encoding="utf-8")
            .replace("{{PROJECT_NAME}}", "p").replace("{{STACK}}", "python")
            .replace("{{TESTS_RUN_COMMAND}}", "pytest").replace("{{TESTS_SCOPED_COMMAND}}", "pytest -k {filter}")
            .replace("{{TESTS_COVERAGE_COMMAND}}", "pytest --cov").replace("{{TOOLS}}", "[]"))
    return yaml.safe_load(text)


def test_compute_gates_new_gates():
    cfg = _config()
    cfg["roles"] = [{"name": "coder", "gates": ["bugfix", "tidy-first", "adr"]}]
    ok = {"passed": True, "offenders": []}
    bad = {"passed": False, "offenders": [{"rule": "budget", "path": "-", "detail": "d", "fix": "shrink"}]}
    res = cg.compute(cfg, "coder", [], None, 0, None, reports={"bugfix": [ok, bad], "tidy-first": [ok], "adr": [ok]})
    by = {g["gate"]: g for g in res}
    assert not by["bugfix"]["passed"] and "[budget]" in by["bugfix"]["diagnosis"]
    assert by["tidy-first"]["passed"] and by["adr"]["passed"]
    res = cg.compute(cfg, "coder", [], None, 0, None)
    assert all(not g["passed"] and "no " in g["diagnosis"] for g in res if g["gate"] in ("bugfix", "tidy-first", "adr"))
    cfg.update(bugfix={"enabled": False}, adr={"enabled": False})
    res = {g["gate"]: g for g in cg.compute(cfg, "coder", [], None, 0, None)}
    assert res["bugfix"]["passed"] and res["adr"]["passed"] and not res["tidy-first"]["passed"]


def test_schemas_accept_new_keys_and_reject_bad_bugfix():
    slice_schema = json.loads((ROOT / "schemas" / "slice-manifest.schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(slice_schema)
    assert not list(v.iter_errors(manifest()))
    no_root = manifest(root_cause=None)
    assert list(v.iter_errors(no_root))
    assert list(v.iter_errors(manifest(allow=["anything"])))
    assert not list(v.iter_errors(manifest(kind="feature", new_types=[{"name": "A", "module": "M", "kind": "class", "purpose": "Does a thing well."}])))
    cfg_schema = json.loads((ROOT / "schemas" / "bob-pipeline.schema.json").read_text(encoding="utf-8"))
    cfg = _config()
    assert {"bugfix", "tidy_first", "pr_description", "adr"} <= set(cfg)
    assert not list(jsonschema.Draft202012Validator(cfg_schema).iter_errors(cfg))
    cfg["bugfix"]["ablation"] = "sometimes"
    assert list(jsonschema.Draft202012Validator(cfg_schema).iter_errors(cfg))
