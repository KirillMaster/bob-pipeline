# bob-pipeline — user guide

A Claude Code plugin that runs features through an Uncle Bob-style pipeline of five role subagents — **Specifier → Coder → Architect → Hardener → QA** — replacing human code review with a *gauntlet of tests*: mechanical quality gates (mutation score, complexity, duplication, traceability) computed by scripts, never by model judgment. Humans review only two things: the Gherkin scenarios **before** any code exists, and the QA report **after**.

## Installation

```
/plugin marketplace add KirillMaster/bob-pipeline
/plugin install bob-pipeline
```

Requirements: a git repository, Python 3.10+ on PATH (for the gate scripts), and the quality tools for your stack (installed on demand — see the tool registry below).

## Quick start

```
/bob-init                      # once per project
/bob-run "users can reset their password via email"
```

1. `/bob-init` detects your stack, freezes quality tools from the registry, interviews you (defaults come from `templates/bob-pipeline.yaml`), writes `.claude/bob-pipeline.yaml` and instantiates the six role agents into `.claude/agents/bob/`.
2. `/bob-run` sends the Specifier to turn your description into Gherkin scenarios + QA procedures + vertical slices. **You approve or reject that document — this is your main leverage point.**
3. After approval each slice runs through the pipeline in an isolated git worktree (`.worktrees/bob-<feature>-<slice>`). Each role makes exactly one labeled commit — `bob(coder): S1 — …` — so the per-role diff is your audit trail.
4. Between handoffs the orchestrator runs the mechanical gates. Failures are repaired in place (e.g. Hardener kills surviving mutants with new tests) or sent back along fixed routes (QA fail → Coder; Architect fail → Coder), at most `return_limit` times.
5. Slices that pass everything are merged into your branch with `--no-ff` (no squash — history is the audit trail). You get a run report with scenario verdicts, gates, commits, and every deviation.

## /bob-init walkthrough

| Step | What happens |
|---|---|
| Stack detection | `*.csproj`→C#, `package.json`+`tsconfig.json`→TypeScript, `pyproject.toml`→Python, `pom.xml`/`build.gradle`→Java; ambiguous → one question |
| Tool selection | From `registry/tool-registry.yaml` (see below); unknown stack → web research + your confirmation; nothing usable → category disabled, dependent role runs degraded |
| Interview | One question at a time; answer "defaults" to accept Bob's flow wholesale |
| Output | `.claude/bob-pipeline.yaml` (validated) + `.claude/agents/bob/*.md` |

Default tool registry:

| Stack | Mutation | Coverage |
|---|---|---|
| C# | Stryker.NET | coverlet (cobertura) |
| TypeScript/JS | StrykerJS | test-runner coverage (lcov) |
| Python | mutmut | coverage.py (cobertura) |
| Java | PIT | JaCoCo |

Each mutation tool carries a `scope_flag` (e.g. Stryker.NET `--mutate "{file}"`, mutmut `--paths-to-mutate {files}`) so the Hardener mutates only the files changed by the slice.
| any | — | complexity: lizard · duplication: jscpd |

## Daily usage

```
/bob-run "feature description"        # standalone: Specifier writes Gherkin from scratch
/bob-run                              # yamlkit mode: picks up specs/*/spec.yaml + tasks automatically
/bob-run "..." skip hardener          # per-feature role skip (specifier/coder can never be skipped)
/bob-run "..." --night                # night mode: zero questions, auto-approve, morning report
/bob-run --resume --night --one-slice # process exactly one slice, print BOB-LOOP: next|done|failed
/bob-run --resume                     # continue an interrupted run from the last role commit
/bob-config                           # show frozen configuration
/bob-config "mutation threshold 90"   # change it (validated before writing)
```

**Night mode**: Gherkin is auto-approved and flagged `auto-approved-night`; any failing slice is marked failed with a diagnosis and the run continues; in the morning read `.bob/reports/run-<id>.md`. Only passing slices are merged.

**Parallel slices**: independent slices (by `depends_on`) run concurrently up to `parallel_limit`, each in its own worktree; merges are serialized.

## Configuration reference (`.claude/bob-pipeline.yaml`)

All defaults (roles, models, thresholds, routes, per-stack test commands) live in `templates/bob-pipeline.yaml`; the table below only describes keys. The deprecated `cleaner` role is still accepted (validator warning) and treated as `architect`.

| Key | Value | Meaning |
|---|---|---|
| `roles[].model` | see template | model per role, passed explicitly at spawn |
| `roles[].gates` | per role | which mechanical gates run after that role |
| `human_gates.gherkin_approval` | `true` | approve scenarios before code |
| `human_gates.qa_report` | `true` | present QA report at the end |
| `thresholds.mutation_score_min` | `80` | hard gate (Hardener) |
| `thresholds.coverage_policy` | `informational` | never blocks |
| `thresholds.complexity_policy` / `duplication_policy` | `not-worse-than-baseline` | first run captures the baseline |
| `send_back_routes` | see template | the only backward edges |
| `tests.run_command` | per stack | FAST suite (excludes integration tests): coder's final run and the orchestrator's single merge-gate full-suite run |
| `tests.scoped_command` | per stack | architect's scoped run; must contain `{filter}`; absent = build only |
| `tests.coverage_command` | per stack | merge-gate run only (coverage is never a standalone run); absent = `run_command` |
| `tests.integration_command` | absent | integration suite; run once by the orchestrator only — never by a role. Absent = no integration run |
| `tests.integration_at` | `merge-gate` | `merge-gate` (in each slice's merge gate) or `run-end` (once after the last merge; failure = `completed-with-failures`) |
| `return_limit` / `parallel_limit` | `3` / `3` | send-back budget per slice / concurrent slices |
| `night_mode_default` | `false` | make every run a night run |
| `bdd_framework` | none | optional: `reqnroll` / `cucumber-js` / `behave`; default is a plain Gherkin doc + test tags (`[Trait("scenario","S1-AS1")]`, `describe('@S1-AS1')`, `@pytest.mark.scenario("S1-AS1")`, `@Tag("S1-AS1")`) |

## yamlkit, the constitution, and local files

bob-pipeline runs on top of yamlkit: with `.specify/` present, `/bob-run` uses its spec/tasks as input and passes `.specify/memory/constitution.yaml` to every role (never `constitution.md`). NON-NEGOTIABLE violations: architect/qa `send-back` with diagnosis `constitution:<id>`; `recommended` ones are deviations. Roles never edit `.specify/` — a needed change comes back as `spec-change:` for you to run in yamlkit. No constitution file = rules are a no-op.

Integration tests run only at the last step (`tests.integration_command`); the fast `run_command` excludes them (per-stack filter in the template), and QA procedures needing them are tagged `@integration`.

Bob files are never committed: `/bob-init` and upgrade write them to `.git/info/exclude`, not `.gitignore`. Because worktrees do not contain them, the orchestrator reads config, agents and run state from the main root (`.bob/slices/<slice>/` for per-slice state).

## Upgrading a 1.0/1.1 project

```
/bob-init --upgrade --dry-run   # preview: JSON report, nothing written
/bob-init --upgrade             # apply
```

Backend: `python scripts/upgrade_project.py --project <dir> [--dry-run] [--steps config,agents,support,untrack] [--old-ref <ref>]` (default steps: `config,agents,support`; `untrack` is opt-in). It migrates the config (cleaner -> architect, adds `tests.*` and `scope_flag`; backup `bob-pipeline.yaml.bak-pre-1.2`), 3-way merges `.claude/agents/bob/*.md` with `git merge-file` (base = old plugin template from this repo's git history rendered with the values recovered from your copy, ours = your copy, theirs = new template), deletes `cleaner.md`, writes the bob files to `.git/info/exclude` and merges `permissions.allow` into `.claude/settings.json`; adds the integration-exclusion filter to the test commands when `tests.integration_command` is set. `--steps untrack` runs `git rm -r --cached` on tracked bob files (files stay on disk, nothing is committed — commit the removal yourself). Config-only project (no agent copies): `--steps config,support`. Exit 1 = conflict markers left in agent files (labels `project` / `old-template` / `new-template`); `--prefer-new` resolves conflicting hunks to the new template instead (lossy where you customized the same lines; unfilled placeholders are listed in `unresolved`). Placeholders new in 1.2.0 fall back to other role copies and the config (`project_name`, `stack`, mutation tools).

Quality gates (1.3.0, opt-in step): `--steps qg [--qg-version x.y.z]` (see `docs/design-1.3.0.md` D23) adds the `quality_gates`/`mutation`/`parallel` config sections, the registry lint/format/architecture/diff-coverage/constitution-traceability tools and the QG role gates (backup `bob-pipeline.yaml.bak-pre-1.3`); for C# net8+ (net4x skipped) it wires `Directory.Build.props`, creates an arch test project skeleton and appends NON-NEGOTIABLE principles to `.specify/memory/constitution.yaml`. Package ids follow the git remote (tenengroup vs pet). Use `--dry-run` first.

## Troubleshooting (outcomes you may see)

| Outcome | Meaning | What to do |
|---|---|---|
| `not-initialized` | no config in this project | `/bob-init` |
| `already-initialized` | `/bob-init` re-run | use `/bob-config` for changes |
| `dirty-working-copy` | uncommitted changes | commit or stash, re-run |
| `no-test-infra` | no test runner found | let Coder set it up, or add one yourself |
| `awaiting-approval` | Gherkin ready for review | approve, or reject with feedback |
| `rejected` | you rejected the scenarios | nothing was created; refine and re-run |
| `stale-approval` | approved artifacts changed mid-run (checksum mismatch) | re-approve the changed scenarios |
| `interrupted-run-found` | a previous run left state in `.worktrees/` | resume (continues after the last role commit) or discard |
| `completed-with-failures` | some slices failed (send-back limit, merge conflict, night failure) | read the report; failed worktrees are preserved for inspection |
| `invalid-change` | `/bob-config` change violates the schema/rules | read the violations; specifier/coder can't be disabled |

Degraded modes are always reported, never silent: no mutation tool → Hardener works heuristically (boundary/error/null cases) and the report says so.

## Repository layout

```
commands/     /bob-init, /bob-run, /bob-config
agents/       role templates ({{PROJECT_NAME}}, {{TECH_STACK}}, … filled at init)
templates/    config, Gherkin, run report, state, worktree-merge protocol
registry/     frozen tool registry per stack
schemas/      JSON Schema for the project config
scripts/      validate_config.py · parse_reports.py · compute_gates.py (the only verdict source) · upgrade_project.py
tests/        pytest suite for the scripts + runnable fixtures (reset via tests/fixtures/reset.py)
```

## One slice per session

A single `/bob-run` keeps every slice in one orchestrator context, which grows large on big features. `--one-slice` runs exactly one ready slice (full role loop + merge), persists progress to `.bob/run-state.yaml` (plus per-worktree `.bob/state.yaml` and report files), and ends with a machine-readable last line: `BOB-LOOP: next` (more slices runnable), `BOB-LOOP: done` (all merged, report written) or `BOB-LOOP: failed`. Nothing depends on chat memory, so each run can be a fresh session.

Driver (PowerShell 5.1+), run from anywhere:

```
powershell -File <plugin>/scripts/bob-loop.ps1 -ProjectDir C:\work\myproject -Feature "describe a feature" -MaxIterations 20
```

`-Feature` is used only for the first iteration (Specifier phase); later iterations use `--resume`. Each iteration runs `claude -p "/bob-pipeline:bob-run ... --night --one-slice" --permission-mode bypassPermissions` in the project dir and logs to `<project>/.bob/loop-logs/iter-NN.log`. The prompt is passed via stdin (UTF-8). The loop stops on `done`, `failed`, a non-zero `claude` exit, a missing final line after one retry, or after `-MaxIterations`. A fresh run (no `.bob/run-state.yaml`) without `-Feature` is an error. Re-run it to continue after a stop; it resumes from state.
