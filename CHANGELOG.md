# Changelog

## 1.9.0

Run kind `bugfix` and design-quality gates, all deterministic (git / file tree / manifest, no LLM judges). Decisions C13, C23, C25, C31, Z16.

- **Run kind `bugfix`** (`/bob-run --bugfix` or a bug report as input). The Specifier plans one `kind: bugfix` slice: `root_cause`, a red `regression_test` committed before the Coder (also `locked_tests`), optional `seam`, `budget` (needs `reason`), `allow` waivers, `test_exempt`. Manifest schema extended; `kind: bugfix` requires `root_cause`.
- **Gate `bugfix`** (new `scripts/bugfix_gates.py`, KISS K1-K5, K7, K8): `missing-root-cause`, `missing-regression`, `root-cause-untouched`, `new-type`, `new-signature`, `test-edited` (existing assertions/literals are immutable), `temp-marker` (TODO/workaround/pragma disable/[Obsolete] without ticket), `budget` (`bugfix.max_added_lines` 30, `max_files` 2). `--run-tests` adds K2/K3: the regression test is red with the `root_cause` files reverted to base and green on head, `bugfix.runs` times (flake guard), needs `bugfix.test_command`.
- **K6 hunk ablation** (new `scripts/bugfix_ablation.py`): every production hunk is reverse-applied in a temporary worktree; tests still green = `unnecessary-hunk`. `bugfix.ablation`: `warn` (default, reported in `warnings`) | `hard` | `off`; capped at 12 hunks.
- **Gate `tidy-first`** (new `scripts/tidy_first.py`, E1 + Z16): commits with a `tidy:`/`refactor:`/`structural:`/`style:`/`format:` subject, or every commit of a slice with `structural: true`, must not change existing test assertions and must not add test methods.
- **Gate `adr`** (new `scripts/adr_gate.py`, G1): a slice with a new `interface` or `allowed_new_edges` needs `adr:` under `docs/adr/**` or `docs/decisions/**` with non-empty Context, Decision, Alternatives sections, or `adr_exempt`.
- **PR description** (new `scripts/pr_description.py`, E3 + E4): renders the PR body from the slice manifest; every `new_types` entry needs a `purpose` (`pr_description.require_purpose`).
- `compute_gates.py`: gates `bugfix`, `tidy-first`, `adr` read reports via repeatable `--gate-report <gate>=<file>`. Shared diff helpers in `scripts/diffkit.py`.
- Config: sections `bugfix`, `tidy_first`, `pr_description`, `adr` (defaults in template and schema); `/bob-init --upgrade` (step `plan`) adds them and the three coder gates.
- Tests: `tests/test_scripts/test_bugfix_gates.py`.
- K8 delta: `complexity-delta` / `nesting-delta` offenders when decision points (branch keywords, `&&`, `||`, `??`, `?:`) or max indentation depth of a changed production file grow beyond `bugfix.max_complexity_delta` (3) / `max_nesting_delta` (1); overridable via `budget` with a reason. Language-agnostic text heuristic, not Roslyn cognitive complexity.
- Not included: K4 Roslyn signature diff (regex heuristic instead).

## 1.8.0

Hard planning, cheap coder: the Specifier plans each slice rigidly, a cheap model (haiku/sonnet) codes, and quality is enforced only by mechanical gates.

- **Slice manifest.** Specifier writes `<bob_root>/.bob/features/<feature>.manifest.yaml` per slice: `feature_module`, `allowed_paths`, `new_types` (`{name, module, kind}`), `allowed_new_edges`, `locked_tests`. New `schemas/slice-manifest.schema.json`, `templates/slice-manifest.yaml`; the return JSON gains `manifest_file`; the manifest is checksummed with the other approved artifacts.
- **Gate `plan-conformance`** (new `scripts/plan_conformance.py`, coder gate, right after the Coder and before the Architect). Fails with a JSON report (offenders + one-line `fix`) on: file outside `allowed_paths`, undeclared new top-level production type (C#/TS/Python regex; test files exempt via `test_paths`) or wrong kind, type outside its `module_paths`, any `locked_tests` change, protected files (baselines, `.claude/bob-pipeline.yaml`, bob agents, config `protected_paths`), failing optional `edge_check_command`. Failure = send-back to the Coder with the report. `compute_gates.py --plan-conformance <report.json>`.
- **Escalation.** Config `escalation: {max_red_iterations, on_exhaust: specifier|stronger_model, escalation_model}`; `parallel_plan.py escalate` decides after N consecutive red gate iterations (slice state `red_iterations`): back to the Specifier (`plan-infeasible`) or one Coder retry on `escalation_model`. Coder prompt: never relax gates, edit baselines/config or locked tests.
- **Models.** Cheap coder = existing `roles[coder].model` (e.g. `haiku`); defaults unchanged. Architect reads `allowed_new_edges` (`undeclared-edge` send-back).
- Config/`validate_config.py`: `plan_conformance`, `escalation`, gate name `plan-conformance`; `on_exhaust: stronger_model` requires `escalation_model`. `/bob-init`: interview item + upgrade step `plan` (default on). `upgrade_project.py`: step `plan`, backups `bob-pipeline.yaml.bak-1.7` and `<role>.md.bak-1.7`.
- Rollout: `python scripts/upgrade_project.py --project <path> --steps agents,plan --old-ref 191c51c` (1.7.0 templates; the config key additions need no manual edit).

## 1.7.0
- Roles: "never run integration tests" generalized to heavy tests (integration/load/fuzz/perf); coder/qa may run a heavy test they wrote/changed in the slice by filter, once.

- perf: prompt diet - agents and commands rewritten in terse imperative English (Russian removed, rationale/history and duplicate rules dropped, design-id references removed); all rules, paths, commands, placeholders, thresholds, schema fields, output formats and send-back conditions kept. Frontmatter `description` shortened (<=200 chars); other frontmatter untouched.
- Size (chars, before -> after): architect 5910 -> 4610, coder 6742 -> 5390, hardener 6982 -> 5821, qa 5486 -> 4617, scout 4008 -> 3005, specifier 5583 -> 4703, bob-config 3171 -> 2881, bob-init 9773 -> 8795, bob-run 21496 -> 18057; total 69151 -> 57879 (-16%).
- Rollout: `python scripts/upgrade_project.py --project <path> --steps agents --old-ref v1.6.2`

## 1.6.2

- coder and hardener `maxTurns` 100 -> 80 (cap for broad roles; the coder's self-stop at ~60 calls stays). Rollout: `python scripts/upgrade_project.py --project <path> --steps agents --old-ref v1.6.1`.

## 1.6.1

- fix: quote `description` in `agents/architect.md` frontmatter — the unquoted `one pass: …` broke YAML, so the agent loaded as `bob-pipeline:architect` with all tools instead of `bob-architect` with its tool list.

## 1.6.0

Exploration tokens (code navigation by grep/cat is the bulk of role context growth).

- **D29: LSP navigation + scout digest for all roles.** All six role agents get `LSP` in `tools:` (Claude Code's built-in tool over the csharp-ls / typescript-language-server / pyright plugins; agents with an explicit `tools:` list only get it when listed). Scout, coder, architect, hardener and qa gain an identical `## Navigation` section: scout digest (`scout_report`) -> injected docs map (SessionStart/SubagentStart hook, full map in `~/.claude/docindex/<repo-slug>.md`) -> `LSP` for symbols (one failure = fall back to Grep, no retry) -> Grep with `path`/`glob` -> Read with `offset`/`limit`. The scout digest gets a `## Key symbols` section (`Symbol — path:line`, resolved via LSP). `/bob-run` now passes `scout_report` to architect, hardener and qa as well as the coder, also on send-back passes.
- **Rollout:** the scout reads the plugin copy (`/plugin update bob-pipeline`). Role copies in a project need `python scripts/upgrade_project.py --project <path> --steps agents --old-ref v1.5.1`, or add `LSP` to `tools:` and the `## Navigation` section by hand.

## 1.5.1

- Scout: explicit `model: haiku` in frontmatter (D28). Measured 23-25.10: subagents on sonnet cost $604.6 (43% of total) vs haiku $3.3; an agent without an explicit `model` inherits `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`. No project rollout needed — the scout prompt is plugin-only.

## 1.5.0

Speed (measured on 23-25.10.2026: `dotnet build/test` = 1161 calls, 24.8 h total, p95 335 s, cold restore and MSBuild node conflicts between parallel worktrees; bob-coder = 69 runs, p50 58 min, p95 170 min, 60% of all subagent time).

- **D26: warm build.** New optional `tests.warmup_command` (schema + template): `/bob-run` runs it once per slice worktree before the first role (restore/install; failure non-fatal, logged in the slice report). C# defaults: `dotnet restore {sln}` warm-up, and `--no-restore -nodeReuse:false` on run/scoped/coverage/integration commands; TypeScript warm-up `npm ci --prefer-offline --no-audit`. Worktrees already isolate bin/obj, so no `--artifacts-path`.
- **D27: slice budget.** Specifier hard rule: at most 5 Gherkin scenarios and 8 `files` per slice (~40 coder tool calls); larger slices split with `depends_on`.
- **Rollout:** existing projects must update `.claude/bob-pipeline.yaml` `tests`: add `warmup_command` and the `--no-restore -nodeReuse:false` flags.

## 1.4.1

- **EC-11: sandboxed-session precondition.** `/bob-run` started from a desktop-app worktree sandbox (`.claude/worktrees/<name>/`) now stops with outcome `sandboxed-session` instead of letting every role die on its first Write. Measured 23-24.10.2026: 165 blocked Write calls, 112 of them in a single session retrying the same path. Bob needs the main project root for `bob_root` and its own `.worktrees/bob-*`; the sandbox forbids writes outside itself.

## 1.4.0

Token budget (measured on 23-24.10.2026: bob-coder = 79 runs, 120 model calls per run, context p50 131K / p90 232K, 34% of the whole period's spend).

- **D25: Scout.** New read-only role template `agents/scout.md`, spawned by `/bob-run` on haiku before the coder's FIRST pass on a slice (skipped on send-back). It returns a digest — where the slice lands, which tests to follow, extension points, traps — written to `.bob/reports/scout-<slice>.md` and passed to the coder as `scout_report`. Not a config role: no gates, no commit, no `return_limit`; a scout failure is a deviation, not a slice failure. Plugin-only prompt (`${CLAUDE_PLUGIN_ROOT}/agents/scout.md`), so projects need no copy and no re-init.
- **Coder token discipline.** `agents/coder.md` gains a `## Token discipline` section: batch independent read-only shell into one call, read ranges instead of whole files, never re-read, lean on the scout's digest; and a self-stop at ~60 tool calls with `send-back` + `slice-too-large: <what is left>` so the Specifier cuts finer instead of the run dying at `maxTurns`.
- Config: optional `scout: {enabled, model}` (schema). Absent = enabled on haiku. No migration needed for existing projects.
- Rollout: `/plugin update bob-pipeline` is enough for the scout. The coder change reaches a project through `python scripts/upgrade_project.py --project <path> --steps agents --old-ref v1.3.3`.

## 1.3.1

- Fix: tenengroup remotes use `TenenGroup.QualityGates.Build` (0.3.0) and `TenenGroup.ArchitectureRules` (2.0.0); arch package was wrongly `TenenGroup.QualityGates`.
- `constitution_trace.py` traces NON-NEGOTIABLE principles by `verified_by` (now in the yamlkit schema) and falls back to `gate_condition`.

## 1.3.0

Design: `docs/design-1.3.0.md` (D16-D24; D1-D15 unchanged).

Speed
- D16: hardener and QA run concurrently after the architect (QA in a detached worktree); merge rule re-runs only QA procedures that reference files the hardener changed (`scripts/parallel_plan.py qa-rerun`). Config `parallel.hardener_qa` (default true).
- D17: specifier declares per-slice `files`; independent slices with disjoint file sets run in parallel worktrees up to `parallel_limit` (`parallel_plan.py batch`).
- D18: send-back reports carry failing procedure ids and the exact failing output (<=40 lines); the coder reads them directly and fixes everything in one pass.
- D19: `.bob/metrics.jsonl` (role runs, send-back reasons, approval waits) and `scripts/bob_metrics.py summarize`.

Quality gates (enabled by default)
- D20/D21: registry categories lint, format, architecture (blocking in the coder's final run and architect), diff-coverage >=80 and constitution-traceability (blocking at the merge gate; new pseudo-role `merge-gate` in `compute_gates.py`). New parsers `exitcode-*`, `diff-cover`, `hardening`; `scripts/constitution_trace.py`. Config: `quality_gates.enabled`, per-gate overrides, `diff_coverage_min`.
- D22: mutation never blocks; hardener is semantic by default, unfixed findings block (`hardening-findings`); Stryker/mutmut only with `mutation.framework_enabled: true`; a low mutation score is a deviation. Behavior change: `mutation-score` no longer fails a slice.
- D23: bob-init offers C# (net8+, net4x skipped) wiring: Directory.Build.props package reference, arch test skeleton, constitution principles; new opt-in upgrade step `qg` (`upgrade_project.py --steps qg`, `--qg-version`).

## 1.2.0

Roles and test policy
- D1: `cleaner` merged into `architect` (one pass: behavior-preserving refactor + module-boundary review, default model sonnet); `agents/cleaner.md` removed; legacy `cleaner` in configs is accepted with a deprecation warning and treated as `architect`.
- D2/D4: no redundant full-suite runs. Coder runs scoped tests and one final full run; architect runs build + `tests.scoped_command`; hardener and qa run no full suite; the orchestrator's merge gate is the single full-suite run and the only place coverage is collected (`tests.coverage_command`).
- D5: mutation testing is scoped to the slice diff via per-tool `scope_flag` in the registry (Stryker.NET `run_command` no longer carries `--mutate`); no changed sources -> hardener skipped with a deviation.
- D6: `.qa.md` procedures must name exact tests, files, commands and expected results; QA separates `procedure-not-executable` (diagnosis `naming`, not counted toward `return_limit`) from real behavior failures.
- D14: integration tests run only at the last step. New keys `tests.integration_command` and `tests.integration_at` (`merge-gate` default | `run-end`); per-stack exclusion filters keep the fast suite clean; `@integration` QA procedures are verified by the integration run; no role ever runs integration tests; bob-init detects integration tests and proposes the split.

Orchestrator
- D3: roles end with a ≤200-word message plus one JSON line; the orchestrator parses only that line and never reads report files.
- D7/D8: mandatory worktree + branch cleanup after merge; idempotent `--one-slice`; atomic state writes.
- D13: runs on top of yamlkit. With `.specify/memory/constitution.yaml` every role receives the path; NON-NEGOTIABLE violations send back with `constitution:<id>`, `recommended` ones are deviations; roles never edit `.specify/` (`spec-change:` diagnosis); the specifier checks `gate_condition`s and the plan's `constitution_check`. No file = no-op. The specifier return gains `"slices_file"`; the orchestrator reads slices from it.
- D15: bob files are never tracked. bob-init/upgrade write `.git/info/exclude` (via `git rev-parse --git-common-dir`), not `.gitignore`; the orchestrator reads config, agents and run state from the main root; per-slice state in `.bob/slices/<slice>/`; roles stage explicit paths only.

Config, tooling, migration
- D9: bob-init writes the `permissions.allow` allowlist for the configured commands into `.claude/settings.json` (merge, never overwrite).
- D10: `templates/bob-pipeline.yaml` is the single source of defaults (per-stack commands as `#@` lines).
- D11: `bob-loop.ps1` (PowerShell 5.1): exit-code checks, UTF-8, prompt via stdin, clear error without state.
- D12: `scripts/upgrade_project.py` / `/bob-init --upgrade`: config migration, 3-way regeneration of `.claude/agents/bob/*.md` preserving placeholders and customizations, exclude entries, permissions; opt-in `untrack` step (`git rm -r --cached`).

## 1.1.0

- Minimal `tools:` per agent.
- `--one-slice` mode for `/bob-run` and the `scripts/bob-loop.ps1` driver (fresh session per slice, `BOB-LOOP: next|done|failed`).
- `compute_gates` scopes enabled categories by stack; BOM-tolerant JSON/YAML reads on Windows.
