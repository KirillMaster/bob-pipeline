# bob-pipeline — user guide

A Claude Code plugin that runs features through an Uncle Bob-style pipeline of six role subagents — **Specifier → Coder → Cleaner → Architect → Hardener → QA** — replacing human code review with a *gauntlet of tests*: mechanical quality gates (mutation score, complexity, duplication, traceability) computed by scripts, never by model judgment. Humans review only two things: the Gherkin scenarios **before** any code exists, and the QA report **after**.

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

1. `/bob-init` detects your stack, freezes quality tools from the registry, interviews you (defaults = Bob's flow), writes `.claude/bob-pipeline.yaml` and instantiates the six role agents into `.claude/agents/bob/`.
2. `/bob-run` sends the Specifier to turn your description into Gherkin scenarios + QA procedures + vertical slices. **You approve or reject that document — this is your main leverage point.**
3. After approval each slice runs through the pipeline in an isolated git worktree (`.worktrees/bob-<feature>-<slice>`). Each role makes exactly one labeled commit — `bob(coder): S1 — …` — so the per-role diff is your audit trail.
4. Between handoffs the orchestrator runs the mechanical gates. Failures are repaired in place (e.g. Hardener kills surviving mutants with new tests) or sent back along fixed routes (QA fail → Coder; Architect fail → Cleaner/Coder), at most `return_limit` times.
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
| any | — | complexity: lizard · duplication: jscpd |

## Daily usage

```
/bob-run "feature description"        # standalone: Specifier writes Gherkin from scratch
/bob-run                              # yamlkit mode: picks up specs/*/spec.yaml + tasks automatically
/bob-run "..." skip hardener          # per-feature role skip (specifier/coder can never be skipped)
/bob-run "..." --night                # night mode: zero questions, auto-approve, morning report
/bob-run --resume                     # continue an interrupted run from the last role commit
/bob-config                           # show frozen configuration
/bob-config "mutation threshold 90"   # change it (validated before writing)
```

**Night mode**: Gherkin is auto-approved and flagged `auto-approved-night`; any failing slice is marked failed with a diagnosis and the run continues; in the morning read `.bob/reports/run-<id>.md`. Only passing slices are merged.

**Parallel slices**: independent slices (by `depends_on`) run concurrently up to `parallel_limit`, each in its own worktree; merges are serialized.

## Configuration reference (`.claude/bob-pipeline.yaml`)

| Key | Default | Meaning |
|---|---|---|
| `roles[].model` | sonnet ×4, haiku (hardener, qa) | model per role, passed explicitly at spawn |
| `roles[].gates` | per role | which mechanical gates run after that role |
| `human_gates.gherkin_approval` | `true` | approve scenarios before code |
| `human_gates.qa_report` | `true` | present QA report at the end |
| `thresholds.mutation_score_min` | `80` | hard gate (Hardener) |
| `thresholds.coverage_policy` | `informational` | never blocks |
| `thresholds.complexity_policy` / `duplication_policy` | `not-worse-than-baseline` | first run captures the baseline |
| `send_back_routes` | `qa: coder`, `architect: [cleaner, coder]` | the only backward edges |
| `return_limit` / `parallel_limit` | `3` / `3` | send-back budget per slice / concurrent slices |
| `night_mode_default` | `false` | make every run a night run |
| `bdd_framework` | none | optional: `reqnroll` / `cucumber-js` / `behave`; default is a plain Gherkin doc + test tags (`[Trait("scenario","S1-AS1")]`, `describe('@S1-AS1')`, `@pytest.mark.scenario("S1-AS1")`, `@Tag("S1-AS1")`) |

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
scripts/      validate_config.py · parse_reports.py · compute_gates.py (the only verdict source)
tests/        pytest suite for the scripts + runnable fixtures (reset via tests/fixtures/reset.py)
```
