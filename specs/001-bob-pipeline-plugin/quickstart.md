# Quickstart — validating the bob-pipeline plugin end-to-end

Runnable scenarios proving the feature works. Entity/contract ids reference [data-model.yaml](data-model.yaml) and [contracts.yaml](contracts.yaml).

## Prerequisites

- Claude Code CLI with plugin support; git 2.40+; Python 3.12+.
- The plugin installed from the repository (marketplace source `KirillMaster/bob-pipeline`).
- A target project under git with a test runner (fixtures under `tests/fixtures/` provide C#, TypeScript, and Python mini-projects).

## Scenario 1 — init on a known stack (`cmd-bob-init` → `initialized`)

1. Open a fixture project (e.g. `tests/fixtures/csharp-calculator/`) in Claude Code.
2. Run `/bob-init`, answer the interview (accept defaults).
3. Expected: `.claude/bob-pipeline.yaml` created (`pipeline-config`); stack detected as `csharp`; tools frozen from the registry (Stryker.NET, coverlet, lizard, jscpd); defaults match Bob's flow (full pipeline, both human gates, mutation ≥ 80, sonnet/haiku per-role split).
4. Re-run `/bob-init` → outcome `already-initialized`, no overwrite.

## Scenario 2 — standalone day run (`cmd-bob-run` → `awaiting-approval` → `completed`)

1. In the initialized fixture, run `/bob-run "add percent operation to calculator"`.
2. Expected: Gherkin scenarios + QA procedures + slice breakdown presented for approval (`gherkin-spec`, `slice`); no implementation code exists yet (P2).
3. Approve. Expected: run executes in a worktree under `.worktrees/` (P4); `git log` on the run branch shows one `bob(<role>): ...` commit per non-skipped role (P3); gates computed from tool output (`gate-result`); final `run-report` shows all slices passed and merge performed; the user's working copy untouched during the run.

## Scenario 3 — per-feature role skip (FR on skip override)

1. Run `/bob-run "..." skipping Hardener`.
2. Expected: no Hardener commit in the run branch; `run-report.deviations` records the skip; zero tokens spent on the skipped role.

## Scenario 4 — night mode (`cmd-bob-run --night`)

1. Run `/bob-run --night "..."` and do not interact.
2. Expected: zero interactive questions; Gherkin marked `auto-approved-night`; a slice exhausting `return_limit` (default 3) is marked `failed` and skipped; morning `run-report` lists auto-approvals, failures with diagnoses, and merges only passing slices (P7).

## Scenario 5 — yamlkit integration (US3)

1. In a project containing `specs/<feature>/spec.md` and `tasks.md`, run `/bob-run` without a description.
2. Expected: artifacts auto-detected; slices derived from tasks; Gherkin traced to the existing spec; approval gate still applies.

## Scenario 6 — degradation and error outcomes

- Unknown stack (fixture without registry coverage): `/bob-init` → `unknown-stack-research` with candidates; nothing frozen without confirmation (P6).
- Registry has no mutation tool for the stack: category `enabled: false`, warning at init; during a run Hardener degrades to heuristic test strengthening and the report records the degradation (EC-2).
- Non-git directory: `/bob-init` → `not-a-git-repo` (EC-4).
- Dirty working copy: `/bob-run` → `dirty-working-copy` (EC-3).
- No test infrastructure: `/bob-run` → `no-test-infra` (EC-1).

## Scenario 7 — interrupt and resume (`run-state`, EC-5)

1. Kill the session mid-run (after at least one role commit).
2. Re-run `/bob-run` → `interrupted-run-found` with slice/role position from `.bob/state.yaml`.
3. Choose resume: the run continues from the last role commit, without repeating completed roles.
4. Modify the approved Gherkin before resuming → `stale-approval`, re-approval required (EC-9).

## Scenario 8 — parallel independent slices (US7)

1. Run a feature whose breakdown contains ≥2 independent slices (`depends_on: []`).
2. Expected: independent slices run in separate worktrees concurrently (up to `parallel_limit`); a dependent slice starts only after its predecessor merges; total wall time ≈ the longest slice, not the sum.

## Automated checks

- `python -m pytest tests/` — unit tests for `scripts/` (config validation, report parsers, gate computation).
- Schema gates: config template and registry validate against their schemas in CI.
