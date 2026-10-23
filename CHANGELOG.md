# Changelog

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
