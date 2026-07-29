# Research — 001-bob-pipeline-plugin

All key unknowns were resolved during the grilling interview (14 decisions) and web research into Uncle Bob's primary sources. This document consolidates them with rationale.

## 1. Reference flow — SwarmForge (Uncle Bob)

- **Decision**: Reproduce the SwarmForge pipeline: Specifier → Coder → Cleaner → Architect → Hardener → QA; a "test gauntlet" instead of code review; the human reads only Gherkin and QA reports.
- **Rationale**: This is the author's documented, battle-tested flow (github.com/unclebob/swarm-forge, empire-2025, the "Clean AI: Agentic Discipline" series on cleancoders.com; @unclebobmartin X posts 2025–2026). Key quotes: "I don't read any of the code written by my agents", "messy code slows my agents down".
- **Alternatives considered**: A custom role scheme (no authoritative grounding); a literal SwarmForge port (tmux+shell — does not map onto Claude Code).

## 2. Roles — Claude Code subagents, not long-lived tmux agents

- **Decision**: Each role = a subagent via the Agent tool, clean context, `model` passed explicitly at spawn. Orchestration lives in the `/bob-run` command in the main session.
- **Rationale**: The verifier's clean context is Bob's load-bearing idea (the verifier must not inherit the writer's self-deception); subagents provide it out of the box. Bob's tmux model exists to serve role *overlap*, which cannot be reproduced on ephemeral subagents and is not needed (see §7).
- **Alternatives considered**: "Hat switching" within one session (no context isolation — rejected); a literal tmux orchestrator (outside the Claude Code plugin model).

## 3. Form factor — a Claude Code plugin

- **Decision**: A full plugin: `.claude-plugin/plugin.json` (manifest), `commands/` (bob-init.md, bob-run.md, bob-config.md), `agents/` (6 role templates), `templates/`, `registry/`, `scripts/`. Distribution — the git repository (KirillMaster/bob-pipeline) as a marketplace source.
- **Rationale**: The user's requirement is to share it with colleagues as a single package. A plugin installs with one command, no manual copying.
- **Alternatives considered**: A pair of skills in a local skills directory (not shareable as a unit); a standalone CLI tool (extra installation, disconnected from Claude Code).

## 4. Quality tool registry

- **Decision**: `registry/tool-registry.yaml` with categories: mutation, coverage, complexity, duplication. Mutation/coverage are per-stack: C# → Stryker.NET + coverlet; TS/JS → StrykerJS (+ the runner's built-in coverage); Python → mutmut + coverage.py; Java → PIT + JaCoCo. Complexity/duplication default to language-agnostic tools: **lizard** (cyclomatic complexity; supports C#/TS/Python/Java and more) and **jscpd** (duplication, multi-language), with per-stack overrides allowed.
- **Rationale**: Mutation tools are inherently language-specific — a registry is unavoidable. For complexity/duplication, multi-language tools shrink the registry and give a uniform report format. Bob solves the same problem with his crap4java/crap4go/dry4java family — we replace it with the registry.
- **Alternatives considered**: The CRAP metric as Bob uses it (no ready multi-language tools; requires stitching coverage×complexity — kept as a possible extension); recommendations only, no registry (non-deterministic, burns tokens on every init).

## 5. Gherkin — document + tag traceability, BDD framework as an option

- **Decision**: By default Gherkin lives as `.feature` documents in `.bob/features/`; acceptance tests are written with the project's regular test framework, tagged/named with the scenario id (`[Trait("scenario","US2-AS1")]`, `describe('@US2-AS1')`, `@pytest.mark.scenario("US2-AS1")`). Gate: every approved scenario has ≥1 traced test. The `bdd_framework` config option enables Reqnroll/cucumber-js/behave.
- **Rationale**: For Bob, Gherkin's value is a human-readable contract for approval, not a runtime. Forcing BDD tooling onto every project is an imposed dependency.
- **Alternatives considered**: Mandatory BDD framework (heavy for small projects); Gherkin only inside the report (loses the persistent contract).

## 6. Worktree protocol and role commits

- **Decision**: One worktree per run (`.worktrees/bob-<feature>-<slice>` — per slice when running in parallel), branch `bob/<feature>/<slice>`. Every role must finish with a commit `bob(<role>): <slice> — <gist>`. Merging into the feature branch follows the worktree-merge protocol adapted from the model-tiered-team-kit reference (no squash — the role history is the audit trail).
- **Rationale**: Isolation from the working copy (P4) + per-role diff audit (P3) without the cost of a worktree per role (sequential execution has no contention). Settled during grilling after analyzing why Bob uses a worktree per role.
- **Alternatives considered**: Worktree per role as Bob does (extra merges with no benefit under sequential execution); working in the user's working copy (violates P4, blocks night mode).

## 7. Parallelism — across slices, not roles

- **Decision**: Independent slices (per the dependency graph from tasks/Specifier) run as parallel worktree pipelines, concurrency limit in the config (default 3). A dependent slice waits for its predecessor's merge.
- **Rationale**: Data parallelism scales better than Bob's pipeline parallelism (not bottlenecked by the slowest stage); single-slice latency is identical in both schemes.
- **Alternatives considered**: Pipeline role overlap (does not map onto ephemeral subagents); sequential only (loses on features with many independent slices).

## 8. Night mode

- **Decision**: A `--night` flag (or `night_mode: true` per run): the Gherkin gate is replaced by auto-approval marked in the report, interactive questions are forbidden, a slice that exhausts its send-back limit is marked `failed` and skipped, and a consolidated report is produced in the morning. Launch/report pattern follows the night-implement skill.
- **Rationale**: P7; an overnight run is the primary autonomy scenario of Bob's flow.
- **Alternatives considered**: Timeout-based auto-approval in day mode (dangerous: silence ≠ consent — rejected, EC-6).

## 9. Run state and resume

- **Decision**: `.bob/state.yaml` inside the worktree: current slice/role/iteration, checksums of input artifacts (spec/tasks/Gherkin), metric baselines. An interrupted run is detected by state + worktree presence; the user is offered resume from the last role commit, or discard.
- **Rationale**: FR-019, EC-5; role commits provide natural recovery points.
- **Alternatives considered**: State outside the worktree in `.claude/` (litters the project, breaks under parallel runs); no state (an interruption loses all work).

## 10. Per-role models

- **Decision**: Defaults: Specifier/Coder/Cleaner/Architect — sonnet; Hardener/QA — haiku. The model is passed as an explicit `model` parameter at subagent spawn (frontmatter `model:` is ignored — known bug #44385). Overridable in the config.
- **Rationale**: The user's tiering policy: never downgrade subtle roles; mechanical ones (running tools, executing ready-made procedures) — haiku.
- **Alternatives considered**: Everything on sonnet (more expensive with no gain on mechanical work); Coder on haiku (risk on a subtle task = a bug).

## 11. Stack detection and fallback research at init

- **Decision**: `/bob-init` scans project markers (`*.csproj`, `package.json`, `pyproject.toml`, `pom.xml`/`build.gradle`), picks tools from the registry; for a stack outside the registry — web research (WebSearch/firecrawl) presenting candidates to the user; the result is frozen into the config. A category with no tool → `enabled: false` + a warning, and Hardener degrades to heuristic test strengthening (EC-2).
- **Rationale**: FR-002/003, P6: deterministic runs, explicit degradation.
- **Alternatives considered**: Research on every run (non-deterministic); hard refusal for unknown stacks (narrows applicability).
