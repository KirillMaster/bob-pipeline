<!-- GENERATED FILE — DO NOT EDIT BY HAND.
     This file is rendered from the corresponding .yaml artifact and will be
     overwritten the next time it is regenerated. Edit the .yaml source instead. -->

# Feature Specification: bob-pipeline — Claude Code plugin: development pipeline following Uncle Bob's flow

**Branch**: `master` | **Created**: 2026-07-29 | **Status**: Draft

**Input**: Claude Code plugin "bob-pipeline": development pipeline following Uncle Bob's flow (SwarmForge) — 6 subagent roles (Specifier, Coder, Cleaner, Architect, Hardener, QA) replacing human code review, a "test gauntlet" as the quality gate. Two modes (standalone and on top of yamlkit artifacts), config via an interview on /bob-init, per-feature override of skipped steps, configurable human gates (default: approval of Gherkin+QA scenarios before code + final QA report), per-role models, one worktree per run + role commit before handoff, stack adaptation via a tool registry with fallback research, Gherkin as a traceable document (BDD framework optional), in-place auto-fix + pipeline send-back only on semantic failures (limit 3), night mode, parallel slices, /bob-config. v1 includes everything.

## User Scenarios & Testing

### User Story 1 - Installing and setting up the pipeline in a project (/bob-init) (Priority: P1)

A developer installs the plugin in a project and, with a single /bob-init command, goes through a short interview: the plugin scans the project, determines the technology stack, selects quality tools (mutation, coverage, duplication/complexity) from a registry, deploys six role agents adapted to the project's domain and stack, and records all decisions in a config file.

**Why this priority**: Nothing else works without initialization — this is the plugin's entry point.

**Motivation**:
- **Problem**: A disciplined AI flow (TDD, test gauntlet, roles) currently has to be assembled by hand for every project: role prompts, stack-specific tools, quality thresholds.
- **Value**: A single /bob-init call turns any project into a platform for Bob's pipeline: roles, tools, and thresholds are chosen for the stack and recorded reproducibly.
- **Consequence if skipped**: Every project is configured by hand, configs drift apart, colleagues can't reuse the flow.

**Independent Test**: In a fresh project with a known stack, call /bob-init, answer the interview questions, and verify that the config and role agents are created and the selected tools match the stack.

**Acceptance Scenarios**:

1. **Given** A C# project with no bob-pipeline config, **When** The developer calls /bob-init and answers the interview questions, **Then** A .claude/bob-pipeline.yaml config is created with roles, models, thresholds, and tools (mutation/coverage/duplication) for C#, and 6 role agents adapted to the stack are deployed into the project
2. **Given** A project on a stack absent from the tool registry, **When** The developer calls /bob-init, **Then** The plugin searches the internet for suitable tools, offers the findings to the developer for confirmation, and records the choice in the config; for categories with no tool found, the step is marked disabled with an explicit warning
3. **Given** A project with an existing bob-pipeline config, **When** The developer calls /bob-init again, **Then** The plugin shows the existing config and asks whether to recreate or keep it; it never silently overwrites anything

**Acceptance Criteria**:

- [ ] `AC-1` After /bob-init, the project has a machine-readable config listing enabled roles, per-role model, gate thresholds, and selected quality tools
- [ ] `AC-2` Role agents are deployed into the project with project-specific values (name, domain, stack) substituted in place of placeholders
- [ ] `AC-3` For stacks present in the registry (C#, TS/JS, Python, Java), tools are selected without any internet access
- [ ] `AC-4` Re-running /bob-init does not overwrite the existing config without explicit confirmation

**Test Scenarios**:

- `TS-1` (integration)
  - Given: A fresh C# project with a csproj and a test project
  - When: /bob-init is run with default interview answers
  - Then: The config is created and passes structural validation; The config selects mutation and coverage tools from the registry for C#; 6 role agents are deployed with no remaining placeholders
  - Verification: manual
- `TS-2` (e2e)
  - Given: A project on an exotic stack (not in the registry)
  - When: /bob-init is run
  - Then: Internet-found tools are proposed, or the step is marked disabled with a warning
  - Verification: manual

### User Story 2 - Running a feature through the pipeline (/bob-run, standalone) (Priority: P1)

A developer describes a feature in text and calls /bob-run. The Specifier turns the description into Gherkin specs, QA scenarios, and a cut into behavior slices; after human approval, each slice sequentially passes through the roles Coder (TDD) → Cleaner (refactoring) → Architect (boundaries/dependencies) → Hardener (mutation gauntlet) → QA (executable checks). Code is never shown to the human; each role commits its result before handing off to the next.

**Why this priority**: The main use case the plugin exists for.

**Motivation**:
- **Problem**: Without a pipeline, AI writes code with no discipline: no executable specification, no mechanical quality gates, and the human is forced to read and review the agent's code, losing the whole benefit.
- **Value**: The human approves only the intent (Gherkin) and gets a final QA report; code quality is guaranteed by the test and metrics gauntlet, not by eyeballing.
- **Consequence if skipped**: The plugin fails to perform its core function — this is the product's heart.

**Independent Test**: In an initialized project, run /bob-run with a description of a small feature, approve the Gherkin, wait for the final QA report, and verify that all gates passed and the git history has a commit from every role.

**Acceptance Scenarios**:

1. **Given** An initialized project and a text description of a feature, **When** The developer calls /bob-run with the description, **Then** The Specifier presents Gherkin specs, QA scenarios, and a slice breakdown for approval before coding starts
2. **Given** Approved Gherkin specs and slice breakdown, **When** The pipeline executes a slice, **Then** Roles run sequentially (Coder → Cleaner → Architect → Hardener → QA), each role finishes with a commit tagged with its role, the run happens in an isolated worktree and does not touch the developer's working copy
3. **Given** All slices passed their gates, **When** The pipeline finishes, **Then** The developer receives a final QA report (scenario statuses, gate metrics, links to role commits) and the changes are merged from the worktree into the feature branch
4. **Given** The developer rejected the Gherkin specs at the gate, **When** They leave feedback, **Then** The Specifier reworks the specs based on the feedback and resubmits them; no code is written before approval

**Acceptance Criteria**:

- [ ] `AC-1` Not a single line of implementation code is created before Gherkin approval
- [ ] `AC-2` Each role leaves a separate commit before handoff — every role's contribution is recoverable from git history
- [ ] `AC-3` The run happens in a separate worktree; the developer's working copy is unchanged until the final merge
- [ ] `AC-4` The final QA report contains the status of every Gherkin scenario, gate metric values per slice, and the run's overall outcome
- [ ] `AC-5` Acceptance tests are traceable to Gherkin scenarios (via tag or name); test coverage of scenarios is 100% of approved scenarios

**Test Scenarios**:

- `TS-1` (e2e)
  - Given: An initialized test project; A feature description with 2-3 behavior scenarios
  - When: A full /bob-run pass is executed with Gherkin approval
  - Then: The git history contains commits from all enabled roles; A QA report is produced, all scenarios green; The working copy was unchanged before the merge
  - Verification: manual
- `TS-2` (integration)
  - Given: Gherkin rejected with feedback
  - When: The Specifier reworks the spec
  - Then: The new version addresses the feedback; No code is created before re-approval
  - Verification: manual

### User Story 3 - Integration with yamlkit (mode on top of spec artifacts) (Priority: P2)

In a project where a feature has already gone through yamlkit (spec/plan/tasks), /bob-run automatically detects the artifacts: the specification becomes the Specifier's input (Gherkin is generated from it instead of free text), the slice breakdown comes from tasks, and the pipeline executes the slices instead of the standard yamlkit-implement.

**Why this priority**: Valuable for the user's existing yamlkit projects, but the standalone mode is self-sufficient.

**Motivation**:
- **Problem**: Teams working a spec-driven flow already have a specification and tasks — making the Specifier reinvent the breakdown means duplicating work and creating divergence.
- **Value**: One source of truth: spec artifacts produce Gherkin and slices, and Bob's pipeline becomes an execution discipline inside the familiar flow.
- **Consequence if skipped**: Two unrelated flows in one project: the spec on one side, the pipeline on the other, manual synchronization.

**Independent Test**: In a project with ready spec.yaml/tasks.yaml, call /bob-run with no feature description and verify Gherkin is generated from the spec and slices match the tasks.

**Acceptance Scenarios**:

1. **Given** A project with a yamlkit feature directory (spec and tasks present), **When** The developer calls /bob-run, **Then** The plugin automatically detects integration mode, builds Gherkin from the specification, and forms slices from the tasks; no free-text feature description is requested
2. **Given** A project with no yamlkit artifacts, **When** The developer calls /bob-run with a text description, **Then** The plugin works in standalone mode with no requirement for yamlkit to be present
3. **Given** A project with partial artifacts (a specification exists, no tasks), **When** The developer calls /bob-run, **Then** Gherkin is built from the specification, and the Specifier performs the slice breakdown and presents it at the same approval gate

**Acceptance Criteria**:

- [ ] `AC-1` The mode (standalone/integration) is determined automatically from artifact presence, with no user flag
- [ ] `AC-2` In integration mode, each Gherkin scenario traces to a specification requirement, and each slice traces to a task
- [ ] `AC-3` The plugin is fully functional in a project where yamlkit is not installed

**Test Scenarios**:

- `TS-1` (e2e)
  - Given: A project with ready yamlkit spec and tasks artifacts
  - When: /bob-run is executed
  - Then: Pipeline slices match the tasks; Gherkin references the spec's requirements
  - Verification: manual

### User Story 4 - Per-feature step skipping and config override (Priority: P2)

Before running a feature, the developer explicitly specifies which roles to skip ("skip Hardener and Architect") or which parameters to override; the pipeline executes only the remaining roles, recording the deviation from the base config in the report.

**Why this priority**: A key user requirement, but it operates on top of an already-working pipeline.

**Motivation**:
- **Problem**: Not every feature needs the full gauntlet: for small changes, mutation testing and architectural review are extra time and tokens (Bob himself: "often I only use unit tests").
- **Value**: Flexible calibration of rigor to the task's criticality with a single argument, without editing the base config.
- **Consequence if skipped**: Either the full pipeline runs always (expensive and slow), or the config is manually edited back and forth.

**Independent Test**: Run /bob-run specifying two roles to skip and verify they didn't execute and the report records the skip.

**Acceptance Scenarios**:

1. **Given** An initialized project, **When** The developer calls /bob-run specifying to skip Hardener, **Then** The Hardener role does not execute, there are no commits or gates from it, and the final report explicitly lists the skipped roles
2. **Given** A request to skip a mandatory role (Coder), **When** The developer calls /bob-run, **Then** The plugin refuses, explaining which roles cannot be disabled (Specifier and Coder), and does not start the run

**Acceptance Criteria**:

- [ ] `AC-1` Skipped roles do not execute and do not consume tokens
- [ ] `AC-2` The run report lists the skipped roles and overridden parameters
- [ ] `AC-3` Specifier and Coder cannot be skipped; an attempt is rejected with an explanation

**Test Scenarios**:

- `TS-1` (integration)
  - Given: An initialized project
  - When: /bob-run is executed skipping Hardener and QA
  - Then: The commit history has no commits from Hardener/QA; The report lists the skips
  - Verification: manual

### User Story 5 - Human gates and night autonomous mode (Priority: P2)

By default, the pipeline stops twice: approval of Gherkin+QA scenarios before code, and the final QA report. The set of gates is configurable. In night mode, the pipeline runs with zero interactive questions: gates are disabled, a failing slice is marked and skipped, and in the morning the developer receives a summary report across all slices.

**Why this priority**: Autonomy is the second most important value of Bob's flow after the gauntlet.

**Motivation**:
- **Problem**: During the day, intent control is needed; at night, the pipeline must run autonomously — any interactive pause kills a night run.
- **Value**: Maximum autonomy without losing control: the human controls intent and sees the outcome, while the pipeline runs while the developer sleeps.
- **Consequence if skipped**: The pipeline sits idle at night or stalls on the first question; or, conversely, there's no intent control during the day.

**Independent Test**: Run a pass in night mode on a feature with a deliberately failing slice and verify the run finishes with no questions and the morning report includes statuses for all slices, including the failed one.

**Acceptance Scenarios**:

1. **Given** Config with default gates, **When** A normal run is in progress, **Then** The pipeline stops exactly twice: Gherkin approval before code, and the final report
2. **Given** A run started in night mode, **When** The pipeline executes all slices, **Then** Not a single interactive question is asked; the Gherkin gate is replaced by auto-approval with a note in the report
3. **Given** In a night run, a slice exhausted its iteration limit, **When** The gate remains unpassed, **Then** The slice is marked failed, its changes don't go into the merge, the pipeline moves to the next independent slice, and the morning report contains the diagnosis

**Acceptance Criteria**:

- [ ] `AC-1` The default configuration gives exactly two gates: Gherkin approval and the final report
- [ ] `AC-2` Night mode asks not a single interactive question during the entire run
- [ ] `AC-3` A slice failure at night does not crash the run: the slice is marked, independent slices are executed, and a summary report is produced
- [ ] `AC-4` Changes from a failed slice do not go into the final merge

**Test Scenarios**:

- `TS-1` (e2e)
  - Given: A feature with two independent slices, one of which is deliberately failing
  - When: The night run finishes
  - Then: The healthy slice is merged, the failing one is not; The summary report contains both statuses and the failure diagnosis
  - Verification: manual

### User Story 6 - Quality gauntlet: auto-fix, send-backs, and thresholds (Priority: P1)

Each checking role fixes in place whatever falls within its competence (Hardener finishes off surviving mutants with tests itself, Cleaner cleans up itself), and sends back through the pipeline only semantic failures: a failed QA scenario → Coder, a rejected structure → Cleaner/Coder. Send-backs are limited by an iteration cap; gate thresholds: mutation score no lower than the threshold (default 80%), coverage — informational, complexity/duplication — no worse than the baseline.

**Why this priority**: The gauntlet is the very thing replacing code review — the core of the method.

**Motivation**:
- **Problem**: Without mechanical gates, "no one reads the code" turns into "no one controls quality"; without limits, agents chew endlessly on their own mess.
- **Value**: Quality is guaranteed by an executable gauntlet with measurable thresholds; fix cycles either converge or stop honestly with a diagnosis.
- **Consequence if skipped**: Bob's flow loses its load-bearing structure — trust in code with no human review has no basis.

**Independent Test**: Feed a slice with weak tests and verify Hardener pushed the mutation score up to the threshold itself; feed a slice with incorrect behavior and verify that after a QA failure the work returned to the Coder and the cycle is bounded by the limit.

**Acceptance Scenarios**:

1. **Given** After the Coder, mutants survived (score below threshold), **When** The Hardener works, **Then** The Hardener writes additional tests itself until the threshold is reached, without sending work back to the Coder
2. **Given** A QA scenario failed (behavior is incorrect), **When** QA records the failure, **Then** The slice is sent back to the Coder with a diagnosis; after the fix, the slice goes through the subsequent roles again
3. **Given** A slice has been sent back for fixing the maximum number of times (default 3), **When** The gate fails again, **Then** The pipeline stops the slice and produces a report with a diagnosis (in night mode — marks the slice and continues)
4. **Given** The Cleaner made the complexity metric worse relative to the baseline, **When** The "no worse than baseline" gate is computed, **Then** The gate fails, and the Cleaner cleans up further in place

**Acceptance Criteria**:

- [ ] `AC-1` Surviving mutants are eliminated by the Hardener in place, with no pipeline send-back
- [ ] `AC-2` Pipeline send-back happens only on semantic failures (QA-fail, Architect-fail); send-back routes are defined in the config
- [ ] `AC-3` The number of send-backs per slice is limited by a configurable cap (default 3); exceeding it stops the run with a diagnosis
- [ ] `AC-4` Gates are computed mechanically: mutation score ≥ threshold, complexity/duplication no worse than baseline; coverage is reported informationally and does not block the run

**Test Scenarios**:

- `TS-1` (integration)
  - Given: A slice with tests that let mutants survive
  - When: The Hardener finishes its work
  - Then: Mutation score is no lower than the threshold; There were no send-backs to the Coder
  - Verification: manual
- `TS-2` (integration)
  - Given: A slice with incorrect behavior that the Coder cannot fix
  - When: The send-back limit is exhausted
  - Then: The slice run is stopped with a diagnosis, no infinite loop occurs
  - Verification: manual

### User Story 7 - Parallel slices (Priority: P3)

Independent feature slices (with no mutual dependencies) execute simultaneously, each in its own worktree pipeline, with sequential merging of results per protocol; dependent slices wait for their predecessors.

**Why this priority**: A speed optimization; pipeline correctness doesn't depend on it.

**Motivation**:
- **Problem**: A sequential run of a long feature made of independent pieces takes the sum of all slice durations, even though the slices don't interfere with each other.
- **Value**: The feature's run time approaches the duration of the longest slice rather than the sum of all of them.
- **Consequence if skipped**: A night run may not finish overnight; the pipeline loses on speed to Bob's original scheme.

**Independent Test**: A feature with two independent slices: verify the slices ran simultaneously (overlapping execution intervals), both results merged without loss.

**Acceptance Scenarios**:

1. **Given** A breakdown with independent slices and parallelism enabled, **When** A run is started, **Then** Independent slices execute simultaneously in separate worktrees, the number of concurrent pipelines is limited by a setting
2. **Given** Slice B depends on slice A, **When** Execution is scheduled, **Then** B does not start before A's successful merge
3. **Given** Merging a parallel slice produces a conflict, **When** The merge is performed, **Then** The conflict is resolved per the merge protocol; if unresolvable, the slice is flagged for manual merge in the report, other slices are unaffected

**Acceptance Criteria**:

- [ ] `AC-1` Dependencies between slices are honored: a dependent slice never starts before its predecessor's successful completion
- [ ] `AC-2` The number of concurrent pipelines is limited by a configurable cap
- [ ] `AC-3` An unresolvable merge conflict does not crash the run: the slice is flagged, the rest complete

**Test Scenarios**:

- `TS-1` (e2e)
  - Given: A feature with two independent slices
  - When: A run with parallelism enabled completes
  - Then: The slices' execution intervals overlap; Both slices are merged, the result is consistent
  - Verification: manual

### User Story 8 - Configuration management (/bob-config) (Priority: P3)

At any time, the developer calls /bob-config to discuss and change recorded decisions: replace a quality tool, change thresholds, role models, the set of gates, or send-back routes; changes are validated and applied to subsequent runs.

**Why this priority**: A maintenance convenience; doesn't affect the first run.

**Motivation**:
- **Problem**: Tool and threshold choices frozen at init go stale: new tools appear, rigor requirements change.
- **Value**: The configuration lives and changes in an explicit, managed way, rather than by manually editing YAML at random.
- **Consequence if skipped**: The only way to change anything is recreating the config via /bob-init or manual editing with no validation.

**Independent Test**: Call /bob-config, replace the mutation tool and threshold, verify the next run uses the new values.

**Acceptance Scenarios**:

1. **Given** An initialized project, **When** The developer calls /bob-config and asks to replace the mutation tool, **Then** The plugin discusses options, applies the choice to the config, and confirms the change; the next run uses the new tool
2. **Given** An invalid change is requested (threshold out of range, unknown role), **When** The change is applied, **Then** The plugin rejects the change with an explanation, the config remains valid

**Acceptance Criteria**:

- [ ] `AC-1` Changes made via /bob-config apply to subsequent runs without recreating the config
- [ ] `AC-2` Invalid changes are rejected with an explanation, the config is never left in an invalid state

**Test Scenarios**:

- `TS-1` (integration)
  - Given: A project with a default config
  - When: The mutation score threshold is changed via /bob-config
  - Then: The config is valid and contains the new threshold; The next run applies the new threshold
  - Verification: manual


## Edge Cases

- `EC-1` A project with no test infrastructure (no test framework/project) → /bob-init detects the absence and offers to set up test infrastructure as part of initialization; /bob-run refuses to start without it, with an explanation
- `EC-2` No mutation tool exists for the stack even after research → The Hardener role degrades to strengthening tests via heuristics (boundary values, negative cases), with an explicit note in the config and report that the mutation gate is unavailable
- `EC-3` A dirty working copy (uncommitted changes) at the time of /bob-run → The run starts anyway, since it works in a separate worktree from the branch's latest commit; the user is warned that uncommitted changes will not be included in the run
- `EC-4` The project is not a git repository → /bob-run refuses to start with an explanation (worktree and the audit trail require git); /bob-init offers to initialize the repository
- `EC-5` A run is interrupted midway (session dropped, limits, error) → The run's state (current slice, role, iteration) is recorded in a state file inside the worktree; a subsequent /bob-run detects the unfinished run and offers to resume from the last role commit or discard it
- `EC-6` Gherkin gate: the user doesn't respond, and the mode is not night mode → The pipeline waits for a response; there is no timeout auto-approval in day mode
- `EC-7` No metrics baseline exists (first run in the project) → The first run records a baseline from the state before changes and evaluates "no worse than baseline" relative to it
- `EC-8` A per-feature override conflicts with the config (a role is already disabled globally, and it's requested to be skipped) → The run proceeds, the duplication is noted in the report with no error
- `EC-9` In integration mode, yamlkit artifacts changed between Gherkin approval and execution → The pipeline detects the divergence via a checksum of the input artifacts and requires re-approval of the affected slices

## Functional Requirements

- **FR-001**: The plugin MUST provide an initialization command that scans the project, determines the technology stack, and through an interview with the user creates a machine-readable pipeline config (roles, models, gates, thresholds, tools, modes). (stories: US1)
- **FR-002**: The plugin MUST contain a registry of quality tools (mutation, coverage, complexity/duplication) for at least C#, TypeScript/JavaScript, Python, and Java, and select tools from the registry without any internet access. (stories: US1)
- **FR-003**: WHEN the project's stack is absent from the registry, the plugin MUST search the internet for suitable tools, offer the result to the user for confirmation, and record the choice in the config; if no tool is found, the category is marked disabled with a warning. (stories: US1)
- **FR-004**: The plugin MUST deploy six role agents (Specifier, Coder, Cleaner, Architect, Hardener, QA) with prompts adapted to the project's name, domain, and stack. (stories: US1, US2)
- **FR-005**: The run command MUST present the user with Gherkin specifications, QA scenarios, and a slice breakdown before coding starts, and wait for explicit approval (except in night mode); on rejection, the Specifier MUST rework the artifacts based on the feedback. (stories: US2, US5)
- **FR-006**: The pipeline MUST execute each slice through a sequence of enabled roles, where each role starts as a subagent with a clean context and MUST finish its work with a git commit tagged with its role before handing off to the next. (stories: US2)
- **FR-007**: A feature run MUST execute in a separate git worktree; the user's working copy is not changed until the final merge, performed per the merge protocol. (stories: US2, US7)
- **FR-008**: Acceptance tests MUST be traceable to Gherkin scenarios via tag or name; by default Gherkin is a human-readable document, and tests are written with the project's standard test framework; a full BDD framework is enabled via a config option. (stories: US2)
- **FR-009**: WHEN yamlkit spec artifacts for the current feature are detected in the project, the plugin MUST automatically switch to integration mode: Gherkin is generated from the specification, slices come from the tasks; WHEN there are no artifacts — work standalone from a text description. (stories: US3)
- **FR-010**: The plugin MUST accept, at run start, an explicit list of roles to skip and parameters to override; Specifier and Coder MUST be non-disableable; all deviations from the base config MUST be recorded in the report. (stories: US4)
- **FR-011**: The execution model for each role MUST be settable in the config per-role (default: Specifier/Coder/Cleaner/Architect — sonnet, Hardener/QA — haiku) and passed explicitly to the subagent at launch. (stories: US1, US2)
- **FR-012**: The plugin MUST support a night mode: zero interactive questions during the run, auto-approval of Gherkin with a note, failing slices are marked and skipped, and a summary report across all slices is produced at completion. (stories: US5)
- **FR-013**: Checking roles MUST fix defects within their own competence in place (Hardener — finish off surviving mutants with tests, Cleaner — clean up metrics further); sending a slice back through the pipeline is allowed only on semantic failures via routes from the config (default: QA-fail → Coder, Architect-fail → Cleaner/Coder). (stories: US6)
- **FR-014**: The number of send-backs per slice MUST be limited by a configurable cap (default 3); when exhausted, the pipeline MUST stop the slice with a diagnosis (in night mode — mark it and continue with the rest). (stories: US6, US5)
- **FR-015**: Quality gates MUST be computed mechanically from tool output: mutation score no lower than a configurable threshold (default 80%), complexity/duplication metrics no worse than the baseline; coverage MUST be reported informationally and must not block the run. (stories: US6)
- **FR-016**: The final QA report MUST include the status of every Gherkin scenario, gate metric values per slice, the list of skipped roles and overrides, links to role commits, and the run's overall status. (stories: US2, US4, US5)
- **FR-017**: WHEN parallelism is enabled, independent slices MUST execute simultaneously in separate worktree pipelines with a configurable concurrency cap; dependent slices MUST wait for their predecessors' successful merge; an unresolvable merge conflict MUST flag the slice without derailing the rest. (stories: US7)
- **FR-018**: The plugin MUST provide a configuration management command allowing tools, thresholds, models, gates, and send-back routes to be discussed and changed with validation; invalid changes MUST be rejected with an explanation. (stories: US8)
- **FR-019**: The run state (slice, role, iteration) MUST be persisted; WHEN a run is interrupted, a subsequent invocation MUST offer to resume from the last role commit or discard the run. (stories: US2, US5)
- **FR-020**: The plugin MUST be distributed as a single installable Claude Code plugin package (commands, agents, templates, registry) requiring no manual file copying by the recipient. (stories: US1)

## Key Entities

- **PipelineConfig** (`E-1`): Machine-readable pipeline configuration in the project: enabled roles, per-role model, human gates, quality thresholds, selected tools, send-back routes, iteration and parallelism limits, modes (night, BDD).
- **Role** (`E-2`): One of the pipeline's six roles (Specifier, Coder, Cleaner, Architect, Hardener, QA): prompt template, area of responsibility, completion criteria, execution model.
- **Slice** (`E-3`): A behavior slice — a unit of passage through the pipeline: a related group of Gherkin scenarios, dependencies on other slices, status, send-back counter, links to role commits.
- **GherkinSpec** (`E-4`): A human-readable specification of feature behavior (Given/When/Then scenarios) traceable to the original spec's requirements (in integration mode) and to acceptance tests.
- **ToolRegistry** (`E-5`): A registry mapping "stack → quality tools" (mutation, coverage, complexity/duplication) with run commands and a way to read the results.
- **GateResult** (`E-6`): The result of computing a gate: metric, threshold/baseline, pass/fail, diagnosis on failure.
- **RunReport** (`E-7`): The final run report: slice and Gherkin scenario statuses, gate metrics, skips and overrides, links to commits, failure diagnoses.
- **RunState** (`E-8`): Persistent state of an unfinished run: current slice, role, iteration, checksums of input artifacts.

## Success Criteria

- **SC-001**: In a project on a supported stack, initialization from the command call to a ready config takes a single interview of no more than 10 questions. (measured via: Run /bob-init on reference projects (C#, TS, Python); count interview questions.)
- **SC-002**: A feature is implemented by the pipeline such that the human interacts only with Gherkin specs and the final report — code is never shown to the human during a run. (measured via: Audit of the run transcript: list of all points of user interaction.)
- **SC-003**: No slice with an unpassed gate ever makes it into the final merge. (measured via: Test runs with deliberately failing slices: verify their changes are absent from the final branch.)
- **SC-004**: Per-feature role skipping reduces run time and cost proportionally: skipped roles do not run and do not spend tokens. (measured via: Compare the number of subagents run and tokens spent between runs with and without skips.)
- **SC-005**: A night run of a multi-slice feature completes with not a single interactive question and produces a summary report by morning. (measured via: A night e2e run on a reference project: verify the absence of input-wait pauses and the presence of a report.)
- **SC-006**: Every role's contribution to every slice is recoverable from the git history of any run. (measured via: Check the commit history of a reference run: each handoff is a separate commit tagged with a role.)
- **SC-007**: The plugin works equally well in projects with and without yamlkit. (measured via: Two e2e runs: a project with spec artifacts and a clean project with a free-text description.)
- **SC-008**: A colleague installs the plugin and brings their project to its first successful run without the author's help. (measured via: Field test: a second person installs the plugin following the README, time to first green run is measured.)

## Assumptions

- `A-1` The plugin runs inside Claude Code with access to subagents (Agent tool), git, and the project's file system.
- `A-2` The user's project is under git, or the user agrees to initialize it.
- `A-3` Sonnet- and haiku-tier models are available in the user's session; if unavailable, a role falls back to the session's model.
- `A-4` The reference flow is Uncle Bob's public material on SwarmForge (6 roles, gauntlet instead of review, "I don't read the agents' code"); literal compatibility with SwarmForge (tmux) is not required.
- `A-5` Patterns from model-tiered-team-kit (agent templates with placeholders, the worktree-merge protocol, per-role memory) are available as a reference during implementation.
- `A-6` The /bob-init interview and /bob-config discussions are conducted in the user's language; pipeline artifacts (Gherkin, reports) are in the language selected in the config.
