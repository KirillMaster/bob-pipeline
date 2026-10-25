# Changelog

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
