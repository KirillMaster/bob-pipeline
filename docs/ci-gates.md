# Bob gates in CI (1.11.0)

`scripts/ci_gates.py` runs the mechanical, LLM-free bob gates on any branch, with no bob-run, no worktree and no frozen
`.claude/bob-pipeline.yaml` (the config is optional; defaults apply). It is what makes the gates apply to human PRs.

## What runs

| Gate | Decisions | Needs | Checks |
|---|---|---|---|
| `tidy-first` | E1, Z16 | git only | A commit with a `tidy:` / `refactor:` / `structural:` / `style:` / `format:` subject must not edit or remove existing test assertions/literals, delete test files, or add test methods. |
| `adr` | G1 | git; manifests optional | An architectural change needs an ADR (`docs/adr/**` or `docs/decisions/**`) with non-empty Context, Decision, Alternatives. Trigger without manifests: a new top-level `interface` type (C#/TS/Python) or a new `<ProjectReference>` in a `*.csproj`. With slice manifests: `new_types` of kind `interface` or `allowed_new_edges`. Waiver: commit body line `adr-exempt: <reason>` (manifests: `adr_exempt`). |
| `bugfix` | K1, K4, K5, K7, K8 (+ K2, K3 with `--run-tests`) | slice manifests | Runs for every `*.manifest.yaml` under `.bob/features` added or changed in the range and having `kind: bugfix`; otherwise skipped (`applicable: false`). K2/K3 need `bugfix.test_command` in the config and run the regression test several times, so enable them only on a dedicated stage. |

Not ported: K6 hunk ablation (slow, `bugfix_ablation.py`), E3/E4 PR description (`pr_description.py` needs a manifest), plan-conformance (needs a bob manifest per slice, bob-run only).

## CLI

```
python scripts/ci_gates.py --base origin/develop [--head HEAD] [--repo .] [--config .claude/bob-pipeline.yaml]
    [--gates tidy-first,adr,bugfix] [--manifest f ...] [--manifest-dir .bob/features]
    [--run-tests] [--warn-only] [--annotations plain|github] [--report out.json]
```

- `--base` is resolved to `git merge-base <base> <head>`: pass the target branch. Full history is required (`fetch-depth: 0` / `git fetch --unshallow`); otherwise exit 2.
- JSON report on stdout (`passed`, per-gate `offenders` with `rule`, `path`, `detail`, one-line `fix`); human lines on stderr (`--annotations github` emits `::error file=...` workflow commands).
- Exit 0 = pass, 1 = offenders, 2 = usage or git error. `--warn-only` always exits 0: use it for the report-only phase (1-2 weeks, per the KISS rollout plan), then drop it.
- Config sections `tidy_first`, `adr`, `bugfix` with `enabled: false` switch a gate off; `tidy_first.structural_prefixes`, `adr.paths`, `plan_conformance.test_paths` are honoured when a config is present. The config is local-only in bob projects (git-excluded), so in CI either commit a small `.claude/bob-pipeline.ci.yaml` with only those sections and pass `--config`, or rely on the defaults.
- Dependencies: Python 3.10+, `pyyaml==6.0.2` (`jsonschema==4.23.0` optional, validates manifests).

## Jenkins (declarative, Linux agent with python3 and git)

```groovy
stage('Bob gates') {
  steps {
    sh '''
      git clone --depth 1 --branch v1.11.0 https://github.com/KirillMaster/bob-pipeline.git .bob-pipeline
      python3 -m venv .bob-venv && .bob-venv/bin/pip install --quiet pyyaml==6.0.2
      git fetch origin ${CHANGE_TARGET:-develop}
      .bob-venv/bin/python .bob-pipeline/scripts/ci_gates.py --base origin/${CHANGE_TARGET:-develop} --report bob-gates.json
    '''
  }
  post { always { archiveArtifacts artifacts: 'bob-gates.json', allowEmptyArchive: true } }
}
```

Add `--warn-only` first. `CHANGE_TARGET` is set on multibranch PR builds. Keep the stage on a net8-agnostic Python image; it does not touch the .NET SDK.

## GitHub Actions (private repos: self-hosted runner, not ubuntu-latest)

```yaml
bob-gates:
  runs-on: [self-hosted, linux]
  steps:
    - uses: actions/checkout@v4.2.2
      with: { fetch-depth: 0 }
    - uses: actions/checkout@v4.2.2
      with: { repository: KirillMaster/bob-pipeline, ref: v1.11.0, path: .bob-pipeline }
    - run: python3 -m pip install --quiet pyyaml==6.0.2
    - run: python3 .bob-pipeline/scripts/ci_gates.py --base origin/${{ github.base_ref }} --annotations github --report bob-gates.json
```

The second checkout of a private bob-pipeline needs a token (`token: ${{ secrets.BOB_PIPELINE_READ }}`, stored in the secret store, never in the repo). Locally: `python <plugin>/scripts/ci_gates.py --base origin/develop`.

## Verify

`python -m pytest tests/test_scripts/test_ci_gates.py`; manually: create a branch with `git commit -m "refactor: x"` that changes an `Assert.Equal` value in a test and expect exit 1 with rule `structural-edits-assertion`.
