# bob-pipeline 1.2.0 — design contract

Single source of truth for the 1.2.0 changes. Every file change in 1.2.0 must conform to this document.
Motivation: Langfuse + Lineage2 history analysis (2026-10-23) — the full test suite ran 3–4× per slice, the orchestrator pulled whole reports into its context (sessions grew to 266K), ~10 send-backs out of 94 role commits were naming mismatches between `.qa.md` and the code, and merged worktrees leaked.

## D1. Role set
- Roles: `specifier`, `coder`, `architect`, `hardener`, `qa`. **`cleaner` is merged into `architect`.**
- `architect` = one pass: behavior-preserving refactor (old cleaner duties: complexity/duplication toward baseline) **plus** module boundaries/dependency direction review. Default model: `sonnet`.
- Back-compat: a config that still has `roles.cleaner` (or `cleaner` in a role order / skip list / `send_back_routes`) is accepted; the validator emits a deprecation warning and the orchestrator treats it as `architect`. `send_back_routes` targets `cleaner` → `architect`.
- `agents/cleaner.md` is removed; its useful instructions move into `agents/architect.md`.

## D2. Test-run policy (no redundant full-suite runs)
| Who | Runs |
|---|---|
| coder | scoped tests while iterating; **one full-suite run** at the end before committing (TDD green) |
| architect | build + **scoped** tests of affected projects only (`tests.scoped_command` with `{filter}`) after refactor |
| hardener | mutation testing **scoped to the slice diff** (D5); no extra full suite |
| qa | executes only the `.qa.md` procedures; never runs the full suite; no code edits |
| orchestrator | **merge gate**: exactly one full-suite run in the slice worktree after qa passes and before merge; coverage is collected **in this same run** (D4). `tests_exit` for gates comes from this run, not from role claims. |

Config keys (template + schema):
```yaml
tests:
  run_command: "<full suite>"            # used by coder (final) and the merge gate
  scoped_command: "<cmd with {filter}>"   # used by architect; optional — absent → architect runs build only
  coverage_command: "<full suite + coverage>"  # used ONLY by the merge gate; absent → merge gate uses run_command
```

## D3. Role return contract (orchestrator context budget)
- Every role's final message is ≤ 200 words of prose followed by **one last line of JSON**:
  `{"role":"coder","slice":"S1","verdict":"pass|send-back|fail","commit":"<sha>","report":".bob/reports/<role>-<slice>.md","diagnosis":"<≤300 chars, send-back/fail only>"}`
- Full outputs (test logs, verbatim procedure output) go to the report file only.
- The orchestrator parses only that JSON line + `git log --oneline -5`; it must NOT read report files into its context (it passes report paths onward, e.g. qa diagnosis path to coder).
- Gherkin/QA in day-mode approval: show the scenario list (ids + titles) and file paths, not full files verbatim, unless the user asks.

## D4. Coverage
- No standalone coverage run anywhere. Coverage is informational and is collected only by the merge-gate run (`tests.coverage_command`). Default in template: coverage enabled-with-merge-gate.

## D5. Mutation testing scope
- Hardener mutates only files changed by the slice: `git diff --name-only <base>...HEAD` filtered to production sources of the stack.
- The registry entry per tool provides the scoping flag template, e.g. Stryker.NET `--mutate "{file}"` (repeatable) + `--project <unit project>`; mutmut `--paths-to-mutate`; Stryker JS `--mutate`. No changed source files → hardener is skipped with a recorded deviation.

## D6. `.qa.md` precision (avoid naming send-backs)
- Specifier must give, per QA procedure: exact test name(s) / test filter expression, file path(s), command to run, expected observable result. No placeholders like "the login test".
- Coder receives the `.qa.md` paths and must name tests/files exactly as the procedures say (or update `.qa.md` in the same commit with a `qa-rename:` note).
- QA distinguishes `procedure-not-executable` (naming/path mismatch → fix `.qa.md` or route to coder with diagnosis `naming`, does NOT count toward `return_limit`) from a real behavior failure (counts).

## D7. Worktree cleanup (mandatory)
- After a successful merge: `git worktree remove <path>` and `git branch -d bob/<feature>/<slice>`; verify with `git worktree list`. Failure → recorded deviation, not silent.
- Interrupted-run detection (§1.4) considers only worktrees whose branch is NOT merged into the base and whose state is not `merged`.

## D8. Idempotent `--one-slice`
- Before starting a slice: if `bob/<feature>/<slice>` is already merged into the base (`git branch --merged <base>`), mark it `merged` in `.bob/run-state.yaml` and pick the next. State writes are atomic (write temp file + rename).
- `.bob/` runtime files (`run-state.yaml`, `loop-logs/`, worktree states) are git-ignored — bob-init adds the ignore entries.

## D9. Permissions for roles
- Each role's `tools:` must include what its test policy needs (Bash/PowerShell for `dotnet test` etc.). bob-init writes the project's permission allowlist for the configured run/scoped/coverage/mutation commands into `.claude/settings.json` (`permissions.allow`, merge, never overwrite) so roles don't hit permission-denied.

## D10. Defaults in one place
- `templates/bob-pipeline.yaml` is the single source of defaults (roles, models, thresholds, commands per stack).
- `bob-init.md`, `bob-config.md`, schema `default`s and README reference/derive from the template; no duplicated default tables. Default models: specifier sonnet, coder sonnet, architect sonnet, hardener haiku, qa haiku.

## D11. bob-loop.ps1 (PowerShell 5.1)
- Check `$LASTEXITCODE`; set `[Console]::OutputEncoding` / `$OutputEncoding` to UTF-8; pass the prompt via stdin (not argv) to survive Cyrillic; fresh run with no state and no `-Feature` → clear error; stop on non-zero exit or missing `BOB-LOOP:` line after a retry.

## D12. Migration of existing projects
- `bob-init --upgrade` (or `/bob-config upgrade`): migrates `.claude/bob-pipeline.yaml` (cleaner → architect, add `tests.scoped_command`/`coverage_command`, coverage policy), regenerates `.claude/agents/bob/*.md` from 1.2.0 templates preserving project-filled placeholders and any project customizations (3-way: old template / project copy / new template), adds `.gitignore` entries and the permissions allowlist, removes `agents/bob/cleaner.md`.
- New projects get all of the above from `/bob-init` directly.

## D13. yamlkit integration and the constitution
- bob-pipeline runs on top of yamlkit (`.specify/`): yamlkit owns spec → plan → tasks; bob owns implementation of the tasks. When `.specify/` exists, bob-run uses yamlkit artifacts as input (integration mode) and the yamlkit constitution as binding rules.
- Constitution: `.specify/memory/constitution.yaml` (typed: `principles[]` with `id`, `name`, `severity` NON-NEGOTIABLE|recommended, `gate_condition`). `constitution.md` is a rendered view — never read it as input.
- Every role receives the constitution path and must comply. NON-NEGOTIABLE violation = blocking: architect and qa return `send-back` with diagnosis `constitution:<principle id>`; coder/architect/hardener must not introduce one; specifier checks scenarios/slices against `gate_condition`s and the `plan.yaml` `constitution_check[]`.
- `recommended` principle violations are recorded as deviations, not blocking.
- Roles must never edit `.specify/` artifacts (spec/plan/tasks/constitution); a needed change → `send-back` / `fail` with diagnosis `spec-change:` for the user to run yamlkit.
- No `.specify/memory/constitution.yaml` → rule is a no-op (standalone mode).
- Specifier JSON return gets an extra field `"slices_file":"<path to slice breakdown>"` (slice = "-").

## D14. Integration tests only at the very last step
- Tests are split: `tests.run_command` / `scoped_command` = fast suite (unit) — must EXCLUDE integration tests (stack template gives the filter, e.g. .NET `--filter "Category!=Integration"`, pytest `-m "not integration"`, jest `--testPathIgnorePatterns integration`).
- `tests.integration_command` = integration suite. Runs exactly once, at the last step: by default in the slice merge gate (after qa pass, right before merge, together with the coverage run); with `tests.integration_at: run-end` — once after the last slice is merged, on the base branch (failure → run outcome `completed-with-failures` + diagnosis, no auto-revert).
- No role (coder, architect, hardener, qa) ever runs integration tests. A QA procedure that needs integration behavior is marked `@integration` and is verified by the integration run result, not executed by qa.
- Absent `integration_command` → nothing extra runs. bob-init detects integration test projects/markers and proposes the split; upgrade adds the exclusion filter to existing `run_command`.
