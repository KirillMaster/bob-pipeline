<!-- GENERATED FILE — DO NOT EDIT BY HAND.
     This file is rendered from the corresponding .yaml artifact and will be
     overwritten the next time it is regenerated. Edit the .yaml source instead. -->

# Tasks: 001-bob-pipeline-plugin

## `T001` Create plugin scaffold and manifest [US1]

Create the Claude Code plugin skeleton: .claude-plugin/plugin.json manifest and the directory layout from plan.yaml (commands/, agents/, templates/, registry/, scripts/, tests/, docs/).

**Context**: Everything else lands inside this structure; the manifest is what makes the repo installable as a plugin.

- **Depends on**: —
- **Requirements**: FR-020
- **Entities**: —
- **Contracts**: —

**Steps**:

1. **Create .claude-plugin/plugin.json** — Fields: name 'bob-pipeline', version '0.1.0', description 'Uncle Bob (SwarmForge) development pipeline: 6 role subagents, test gauntlet instead of code review', author, repository https://github.com/KirillMaster/bob-pipeline.
2. **Create directory layout** — commands/, agents/, templates/, registry/, scripts/, tests/fixtures/, docs/ — each non-empty dir gets its first real file in later tasks; add .gitkeep only where nothing lands in this phase.
3. **Add repo hygiene files** — .gitignore (Python caches, .worktrees/, .bob/), LICENSE (MIT), root README.md stub pointing to docs/.

**Technical Notes**:

- `.claude-plugin/plugin.json`: Manifest format per Claude Code plugin docs; commands and agents are discovered from commands/ and agents/ automatically.

**Acceptance Criteria**:

- [ ] `AC-1` plugin.json parses as JSON and declares name bob-pipeline.
- [ ] `AC-2` All directories from plan.yaml project_structure exist in the repo.

**Test Scenarios**:

- `TS-1` (integration)
  - Given: a clone of the repository
  - When: the plugin is installed into Claude Code from the repo
  - Then: installation succeeds and the plugin is listed as bob-pipeline
  - Verification: automated

## `T002` Author the quality tool registry [P] [US1]

Write registry/tool-registry.yaml with entries (stack, category, tool, run_command, report_parser, enabled) for csharp, typescript, python, java plus language-agnostic complexity/duplication tools.

**Context**: The registry is how the pipeline stays stack-agnostic: tools are looked up, never hardcoded (P6).

- **Depends on**: T001
- **Requirements**: FR-002
- **Entities**: tool-registry-entry
- **Contracts**: —

**Steps**:

1. **Define the registry YAML shape** — Top-level list of entries matching the ToolRegistryEntry entity: stack, category (mutation|coverage|complexity|duplication), tool, run_command, report_parser, enabled.
2. **Fill per-stack mutation/coverage entries** — csharp: Stryker.NET (dotnet stryker) + coverlet; typescript: StrykerJS (npx stryker run) + runner coverage; python: mutmut (mutmut run) + coverage.py; java: PIT (mvn org.pitest:pitest-maven:mutationCoverage) + JaCoCo.
3. **Fill language-agnostic entries** — stack 'any': lizard for complexity (lizard --csv), jscpd for duplication (npx jscpd --reporters json); report_parser points to scripts/parse_reports.py handlers.

**Technical Notes**:

- `registry/tool-registry.yaml`: One entry per (stack, category); 'any' entries are the fallback when no stack-specific entry exists.

**Acceptance Criteria**:

- [ ] `AC-1` Registry contains mutation+coverage entries for csharp, typescript, python, java and 'any' entries for complexity and duplication.
- [ ] `AC-2` Every entry names an existing report_parser handler in scripts/.

**Test Scenarios**:

- `TS-1` (unit)
  - Given: the registry file
  - When: scripts/validate_config.py --registry registry/tool-registry.yaml runs
  - Then: validation exits 0; all four stacks resolve a full category set (with 'any' fallbacks)
  - Verification: automated

## `T003` Author the pipeline config template [P] [US1]

Write templates/bob-pipeline.yaml — the config template /bob-init instantiates — with Bob-flow defaults for roles, models, human gates, thresholds, limits, and modes.

**Context**: Every behavior parameter must come from config, and the defaults must reproduce Bob's flow (P5); this file is the single source of those defaults.

- **Depends on**: T001
- **Requirements**: FR-001, FR-011
- **Entities**: pipeline-config, role
- **Contracts**: —

**Steps**:

1. **Write the template with placeholders** — Placeholders {{STACK}}, {{PROJECT_NAME}}, {{TOOLS}} filled by /bob-init; static defaults inline.
2. **Encode Bob-flow defaults** — roles: all six enabled, models sonnet/sonnet/sonnet/sonnet/haiku/haiku; human_gates: gherkin_approval true, final_qa_report true; thresholds: mutation_score_min 80, coverage informational, complexity/duplication not-worse-than-baseline; return_limit 3; parallel_limit 3; night_mode_default false; send-back routes qa->coder, architect->cleaner+coder; specifier and coder marked non-skippable.
3. **Write the config JSON Schema** — schemas/bob-pipeline.schema.json inside the plugin (used by scripts/validate_config.py); mirrors the PipelineConfig entity.

**Technical Notes**:

- `templates/bob-pipeline.yaml`: Instantiated to .claude/bob-pipeline.yaml in the target project by /bob-init.
- `schemas/bob-pipeline.schema.json`: Validation source of truth for /bob-config changes too.

**Acceptance Criteria**:

- [ ] `AC-1` Template with placeholders substituted validates against the config schema.
- [ ] `AC-2` Defaults match the spec: full pipeline, both human gates, mutation 80, limits 3/3, per-role sonnet/haiku split.

**Test Scenarios**:

- `TS-1` (unit)
  - Given: the template instantiated with stack csharp
  - When: scripts/validate_config.py runs on the result
  - Then: exit 0
  - Verification: automated

## `T004` Implement config validation and report-parsing scripts [US6]

Write scripts/validate_config.py (config + registry validation) and scripts/parse_reports.py (extract metrics from Stryker/mutmut/PIT/lizard/jscpd/coverage outputs), with pytest coverage.

**Context**: Gates must be computed from tool output by scripts, not by model judgment (P1); these parsers are that mechanical layer.

- **Depends on**: T002, T003
- **Requirements**: FR-015
- **Entities**: tool-registry-entry, gate-result
- **Contracts**: —

**Steps**:

1. **Implement scripts/validate_config.py** — Validates a bob-pipeline.yaml against schemas/bob-pipeline.schema.json and cross-checks tools against registry entries; exits non-zero with JSON violations on stderr.
2. **Implement scripts/parse_reports.py** — One handler per tool: stryker (mutation-report.json mutationScore), mutmut (results summary), pit (mutations.xml), lizard (CSV avg/max CCN), jscpd (json percentage), coverage (cobertura/lcov line rate). Output: normalized JSON {category, metric_value}.
3. **Implement scripts/compute_gates.py** — Takes normalized metrics + thresholds/baselines from config, emits GateResult JSON list ({gate, role, metric_value, threshold, baseline, passed, diagnosis}); coverage never sets passed=false.
4. **Write pytest suite** — tests/test_scripts/ with fixture report files per tool; cover threshold pass/fail, baseline comparison, coverage-informational, malformed report error paths.

**Technical Notes**:

- `scripts/parse_reports.py`: Handlers referenced by name from registry report_parser fields (T002 AC-2).
- `scripts/compute_gates.py`: The only place gate verdicts are computed; commands must call it, never eyeball reports.

**Acceptance Criteria**:

- [ ] `AC-1` pytest passes for all parser and gate-computation cases.
- [ ] `AC-2` compute_gates.py marks coverage informational (never blocking) and mutation < threshold as failed with a diagnosis.

**Test Scenarios**:

- `TS-1` (unit)
  - Given: a Stryker mutation-report.json fixture with score 72
  - When: compute_gates.py runs with mutation_score_min 80
  - Then: gate mutation-score has passed=false and a diagnosis naming the shortfall
  - Verification: automated
- `TS-2` (unit)
  - Given: a lizard CSV fixture equal to the stored baseline
  - When: compute_gates.py runs with not-worse-than-baseline policy
  - Then: gate complexity-baseline has passed=true
  - Verification: automated

## `T005` Author the six role agent templates [P] [US2]

Write agents/specifier.md, coder.md, cleaner.md, architect.md, hardener.md, qa.md — role prompts with {{PROJECT_NAME}}/{{DOMAIN}}/{{TECH_STACK}}/{{TOOLS}} placeholders, each ending with the mandatory role commit.

**Context**: The roles are the pipeline; each must carry Bob's discipline for its stage and the clean-context/commit contract (P3).

- **Depends on**: T001
- **Requirements**: FR-004, FR-006, FR-013
- **Entities**: role, gherkin-spec, gate-result
- **Contracts**: —

**Steps**:

1. **Write specifier.md** — Input: feature description or yamlkit artifacts. Output: .bob/features/*.feature (Gherkin scenarios with stable ids), QA procedures per scenario, slice breakdown with depends_on graph. Never writes implementation code.
2. **Write coder.md** — TDD against approved Gherkin: failing acceptance test traced to scenario id first, then implementation; runs the project test suite; commit 'bob(coder): <slice> — <gist>'.
3. **Write cleaner.md** — Behavior-preserving refactoring only; runs tests after every change; runs complexity/duplication tools via registry commands and improves toward baseline; commit 'bob(cleaner): ...'.
4. **Write architect.md** — Checks module boundaries and dependency direction; semantic findings produce a send-back verdict (to cleaner/coder per config routes), mechanical fixes done in place; commit 'bob(architect): ...'.
5. **Write hardener.md** — Runs mutation tool from config; kills surviving mutants by adding tests (in-place repair, FR-013); if mutation category disabled — documented heuristic degradation (boundary values, error paths); commit 'bob(hardener): ...'.
6. **Write qa.md** — Executes QA procedures per approved scenario, captures outputs, computes gherkin-traceability gate via scripts, assembles the RunReport section; semantic failure → send-back verdict to coder; commit 'bob(qa): ...'.
7. **Add the shared role contract block to every template** — Common footer: work only inside the run worktree; finish with the labeled commit; return a compact structured summary (status, gate results JSON, send-back verdict if any); never ask the user questions.

**Technical Notes**:

- `agents/`: Placeholder style follows the model-tiered-team-kit reference; model is NOT set in frontmatter (bug #44385) — /bob-run passes it explicitly.

**Acceptance Criteria**:

- [ ] `AC-1` Six templates exist; each contains the placeholders, the commit instruction with the role label, and a no-user-questions rule.
- [ ] `AC-2` Checking roles (cleaner/architect/hardener/qa) each define in-place repair scope vs send-back conditions matching FR-013.

**Test Scenarios**:

- `TS-1` (e2e)
  - Given: templates instantiated for a fixture project
  - When: a slice runs through the full pipeline
  - Then: git log of the run branch shows exactly one commit per enabled role, labeled bob(<role>)
  - Verification: automated

## `T006` Author shared templates: Gherkin, reports, merge protocol [P] [US2]

Write templates/gherkin.feature (scenario skeleton with stable ids), templates/run-report.md, templates/state.yaml, and templates/worktree-merge.md (the merge protocol roles and /bob-run follow).

**Context**: Uniform artifacts make runs auditable and the merge deterministic; the merge protocol is the single exit point for changes (P4).

- **Depends on**: T001
- **Requirements**: FR-007, FR-016
- **Entities**: gherkin-spec, run-report, run-state
- **Contracts**: —

**Steps**:

1. **Write templates/gherkin.feature** — Feature header + scenario blocks tagged @<scenario-id>; companion note on test traceability conventions per stack ([Trait], describe('@id'), pytest marker).
2. **Write templates/run-report.md** — Sections mirroring RunReport: summary, per-slice results with gates, deviations (skips/degradations/auto-approvals/exhausted limits), commit links, merged flag.
3. **Write templates/state.yaml** — RunState shape: run_id, feature, mode, current_slice, current_role, input_checksums, baselines, slices[].
4. **Write templates/worktree-merge.md** — Adapted from model-tiered-team-kit: preconditions (all gates passed), no squash, merge order for dependent slices, conflict handling (flag slice, continue others), worktree cleanup.

**Technical Notes**:

- `templates/`: Commands copy these into the target project's .bob/ at run time; they are data, not prompts.

**Acceptance Criteria**:

- [ ] `AC-1` All four templates exist and state.yaml matches the RunState entity field-for-field.

**Test Scenarios**:

- `TS-1` (integration)
  - Given: a completed fixture run
  - When: the generated report is compared to templates/run-report.md sections
  - Then: every section is present and populated
  - Verification: automated

## `T007` Implement /bob-init command [US1]

Write commands/bob-init.md: stack detection from project markers, interview with Bob-flow defaults, tool selection from the registry, fallback web research for unknown stacks, config creation, and edge-case outcomes.

**Context**: Init freezes all pipeline decisions into the project config so later runs are deterministic and offline.

- **Depends on**: T002, T003, T004
- **Requirements**: FR-001, FR-002, FR-003, FR-004, FR-020
- **Entities**: pipeline-config, tool-registry-entry, role
- **Contracts**: cmd-bob-init

**Steps**:

1. **Implement precondition checks** — Existing .claude/bob-pipeline.yaml → outcome already-initialized (suggest /bob-config); no .git → outcome not-a-git-repo (suggest git init); missing test runner → warning recorded for warnings[].
2. **Implement stack detection** — Scan markers: *.csproj/*.sln → csharp; package.json (+tsconfig) → typescript; pyproject.toml/setup.py → python; pom.xml/build.gradle → java; honor stack_override; ambiguous/multiple → ask (day mode only).
3. **Implement tool selection** — Resolve each category from registry (stack-specific first, 'any' fallback); category unresolved → registry research path: WebSearch for candidates, present to user, on confirmation freeze into config, on none → enabled:false + warning (outcome unknown-stack-research when the whole stack is unknown).
4. **Implement the interview** — One question at a time: confirm roles/models/gates/thresholds/limits/BDD option, defaults preselected from the template; write answers into the instantiated config.
5. **Instantiate config and role agents** — Fill templates/bob-pipeline.yaml placeholders, write .claude/bob-pipeline.yaml, validate via scripts/validate_config.py; instantiate agents/*.md placeholders with project name/domain/stack into the project's .claude/agents/bob/ directory.
6. **Emit the initialized outcome** — Report config_path, stack, tools_selected, warnings per the cmd-bob-init contract.

**Technical Notes**:

- `commands/bob-init.md`: Command prompt; heavy lifting (validation) delegated to scripts via Bash calls.

**Acceptance Criteria**:

- [ ] `AC-1` On a C# fixture, /bob-init produces a valid config with Stryker.NET/coverlet/lizard/jscpd frozen and defaults matching Bob's flow.
- [ ] `AC-2` Re-running yields already-initialized without overwriting; non-git dir yields not-a-git-repo.
- [ ] `AC-3` A stack with no registry mutation tool ends with that category enabled:false and a warning.

**Test Scenarios**:

- `TS-1` (e2e)
  - Given: fixture tests/fixtures/csharp-calculator, no existing config
  - When: /bob-init runs accepting defaults
  - Then: .claude/bob-pipeline.yaml validates (exit 0); tools frozen from registry; warnings empty
  - Verification: automated
- `TS-2` (integration)
  - Given: a directory without .git
  - When: /bob-init runs
  - Then: outcome not-a-git-repo, no config written
  - Verification: automated

## `T008` Implement /bob-run core orchestration (standalone, day mode) [US2]

Write commands/bob-run.md: preconditions, Specifier phase, human approval gate, worktree creation, sequential role execution with explicit models and role commits, gate checks between handoffs, merge, and report.

**Context**: This is the pipeline itself — the whole feature exists to make this run happen the way Bob runs SwarmForge.

- **Depends on**: T005, T006, T007
- **Requirements**: FR-005, FR-006, FR-007, FR-008, FR-011, FR-016
- **Entities**: pipeline-config, slice, gherkin-spec, gate-result, run-report
- **Contracts**: cmd-bob-run

**Steps**:

1. **Implement preconditions** — No config → not-initialized; dirty working copy → dirty-working-copy (EC-3); no test infra → no-test-infra with offer to let Coder set it up (EC-1); existing .bob/state.yaml + worktree → interrupted-run-found (handled fully in T009).
2. **Implement the Specifier phase** — Spawn specifier subagent (model from config, passed explicitly) with the feature description; receive Gherkin + QA procedures + slice breakdown; compute input checksums.
3. **Implement the approval gate** — Present features/QA/slices → outcome awaiting-approval; on approval record checksums and approval status; on rejection with feedback re-run Specifier (counts against return_limit); on final rejection → outcome rejected, clean up.
4. **Implement worktree setup** — git worktree add .worktrees/bob-<feature>-<slice> -b bob/<feature>/<slice> from the current branch head; copy .bob/ skeleton (features, state.yaml from template, baselines: capture via tools if first run — EC-7).
5. **Implement the role loop** — For each enabled, non-skipped role in config order: spawn subagent with explicit model, worktree cwd, instantiated role prompt + slice context; on return verify the labeled commit exists (create-check, not trust); run compute_gates.py for the role's gates; route failures per config (in-place already done by role; semantic → send-back respecting return_limit, T012 details).
6. **Implement merge and report** — All slices passed → merge per templates/worktree-merge.md into the user's branch, remove worktree; assemble RunReport from templates/run-report.md with gate results, commit links, deviations; outcomes completed / completed-with-failures.

**Technical Notes**:

- `commands/bob-run.md`: Orchestrator prompt; spawns agents via the Agent tool with model parameter from config (never frontmatter).
- `scripts/compute_gates.py`: Called between handoffs; verdicts come only from here (P1).

**Acceptance Criteria**:

- [ ] `AC-1` On a fixture, a run produces per-role labeled commits, gates computed from tool output, a merge, and a full report; the user's working copy is untouched until merge.
- [ ] `AC-2` No implementation code exists before approval; rejection stops the run with no worktree left behind.

**Test Scenarios**:

- `TS-1` (e2e)
  - Given: initialized csharp fixture; feature description 'add percent operation'
  - When: /bob-run executes and the user approves
  - Then: run branch has bob(specifier|coder|cleaner|architect|hardener|qa) commits; report lists every Gherkin scenario status; working copy clean during the run
  - Verification: automated
- `TS-2` (e2e)
  - Given: the approval prompt is answered with rejection
  - When: /bob-run continues
  - Then: outcome rejected; no implementation commits exist
  - Verification: automated

## `T009` Implement run state persistence and resume [US2]

Persist RunState to .bob/state.yaml at every role boundary; detect interrupted runs and offer resume from the last role commit or discard; detect stale approvals via checksums.

**Context**: An overnight or long run must survive interruption without losing paid-for work (EC-5) and must not silently run against edited inputs (EC-9).

- **Depends on**: T008
- **Requirements**: FR-019
- **Entities**: run-state, slice
- **Contracts**: cmd-bob-run

**Steps**:

1. **Write state at boundaries** — Update .bob/state.yaml before spawning each role and after each gate: current_slice, current_role, return counts, slice statuses.
2. **Implement detection and resume** — On /bob-run start, existing state + worktree → outcome interrupted-run-found with position; resume: recompute input checksums, match → continue from the role after the last verified commit; discard: remove worktree and branch.
3. **Implement stale-approval handling** — Checksum mismatch on resume (or mid-run artifact edit detected at role boundary) → outcome stale-approval listing changed artifacts; require re-approval before continuing.

**Technical Notes**:

- `templates/state.yaml`: Shape defined in T006; keep in worktree so parallel runs don't collide.

**Acceptance Criteria**:

- [ ] `AC-1` Killing a run after the coder commit and re-invoking /bob-run offers resume; resuming does not repeat the coder role.
- [ ] `AC-2` Editing the approved .feature file before resume yields stale-approval.

**Test Scenarios**:

- `TS-1` (e2e)
  - Given: a run interrupted after bob(coder) commit
  - When: /bob-run is invoked again and resume is chosen
  - Then: execution continues at cleaner; final report notes the resume
  - Verification: automated

## `T010` Implement yamlkit artifact auto-detection mode [P] [US3]

Extend /bob-run: when spec/tasks artifacts exist for the current feature, derive Gherkin from the spec and slices from tasks instead of a free-text description; keep the approval gate.

**Context**: Teams already using spec-driven flows should plug the pipeline in without re-describing features.

- **Depends on**: T008
- **Requirements**: FR-009
- **Entities**: slice, gherkin-spec
- **Contracts**: cmd-bob-run

**Steps**:

1. **Implement detection** — Look for .specify/feature.json → feature dir, else newest specs/*/ containing spec.(yaml|md); found + no description argument → integration mode; nothing found + no description → error asking for one.
2. **Adapt the Specifier input** — Integration mode: Specifier receives spec content (user stories, acceptance criteria) and tasks list; generates Gherkin traced to story ids and maps slices 1:1 to task groups with their depends_on.
3. **Keep gates identical** — Approval, checksums (over spec/tasks sources too), role loop, and report are unchanged; report names the source artifacts.

**Technical Notes**:

- `commands/bob-run.md`: Mode selection happens before the Specifier phase; both modes converge on the same slice/Gherkin structures.

**Acceptance Criteria**:

- [ ] `AC-1` In a project with yamlkit artifacts, /bob-run without arguments enters integration mode and traces Gherkin to spec story ids.

**Test Scenarios**:

- `TS-1` (e2e)
  - Given: a fixture with specs/001-x/spec.yaml and tasks.yaml
  - When: /bob-run runs with no description
  - Then: slices mirror tasks with dependencies; approval gate still shown
  - Verification: automated

## `T011` Implement per-feature role skip and overrides [P] [US4]

Accept an explicit skip list and parameter overrides at run start ('skip Hardener'); refuse to skip Specifier/Coder; record every deviation in the report.

**Context**: Small features shouldn't pay for the full gauntlet, but skips must stay visible, never silent (P7).

- **Depends on**: T008
- **Requirements**: FR-010
- **Entities**: slice, run-report
- **Contracts**: cmd-bob-run

**Steps**:

1. **Parse skip/override arguments** — Natural-language and structured forms ('skip hardener', skip_roles: [hardener]); normalize to role names; unknown role → invalid argument error before any work.
2. **Enforce non-skippable roles** — specifier/coder in the skip list → refuse with explanation, run does not start.
3. **Apply and record** — Skipped roles excluded from the role loop (zero subagent spawns); slices carry skipped_roles; report deviations list every skip and override with origin 'per-feature'.

**Technical Notes**:

- `commands/bob-run.md`: Overrides apply to this run only; the base config file is never modified by a run.

**Acceptance Criteria**:

- [ ] `AC-1` A run with 'skip Hardener' has no bob(hardener) commit and lists the skip under deviations.
- [ ] `AC-2` 'skip Coder' is refused before the worktree is created.

**Test Scenarios**:

- `TS-1` (e2e)
  - Given: an initialized fixture
  - When: /bob-run '...' skipping Hardener completes
  - Then: no hardener commit; deviations contains the skip
  - Verification: automated

## `T012` Implement night mode [US5]

Add --night: auto-approve Gherkin with a report flag, forbid interactive questions, mark-and-skip slices that exhaust limits, and produce the consolidated morning report.

**Context**: The autonomy payoff of Bob's flow is the overnight run; it must never stall on a question and never hide a failure (P7).

- **Depends on**: T008, T009
- **Requirements**: FR-012, FR-005, FR-014, FR-016
- **Entities**: run-state, run-report, gherkin-spec
- **Contracts**: cmd-bob-run

**Steps**:

1. **Implement mode switching** — --night flag or night_mode config; mode recorded in RunState; day-mode-only branches (interview questions, approval prompt, resume prompt) each get a defined night behavior.
2. **Implement auto-approval** — Gherkin approval set to auto-approved-night with checksums recorded; report deviations list every auto-approval.
3. **Implement failure policy** — Slice exhausting return_limit or hitting an unanswerable question → status failed with diagnosis, pipeline continues with remaining slices; merge only passing slices.
4. **Produce the morning report** — Single consolidated RunReport across all slices: auto-approvals, failures with diagnoses, merges performed; written to .bob/reports/ and surfaced on session return.

**Technical Notes**:

- `commands/bob-run.md`: Audit rule: grep the night path for any AskUserQuestion/approval prompt — there must be none (P7 gate).

**Acceptance Criteria**:

- [ ] `AC-1` A night run over a feature with one deliberately failing slice completes, merges the passing slices, and reports the failure with a diagnosis — zero questions asked.

**Test Scenarios**:

- `TS-1` (e2e)
  - Given: initialized fixture; --night flag; one slice engineered to fail its gates
  - When: the run completes unattended
  - Then: no interactive prompt occurred; failed slice marked and skipped; morning report lists auto-approval and the failure
  - Verification: automated

## `T013` Implement gate enforcement, in-place repair, and send-back routing [US6]

Wire compute_gates.py verdicts into the role loop: threshold/baseline gates block handoff, checking roles repair in place, semantic failures route back per config with the iteration limit.

**Context**: This is the gauntlet: quality enforced by tool-derived verdicts and bounded repair loops instead of human review (P1, P7).

- **Depends on**: T008
- **Requirements**: FR-013, FR-014, FR-015
- **Entities**: gate-result, slice, run-state
- **Contracts**: cmd-bob-run

**Steps**:

1. **Enforce gates at handoff** — After each role commit run its configured gates via compute_gates.py; failed mechanical gate → same role repairs in place and re-runs the gate (bounded by return_limit iterations of its inner loop).
2. **Implement send-back routing** — Semantic failure verdicts from roles (qa-fail, architect-fail) → route per config (default qa→coder, architect→cleaner/coder); increment slice return_count; target role reruns from its stage with the failure diagnosis as input.
3. **Enforce the limit** — return_count > return_limit → day mode: stop slice with diagnosis and ask the user; night mode: mark failed, continue (per T012); all send-backs and repairs logged into gate_results diagnoses.
4. **Implement baseline management** — First run captures complexity/duplication baselines into .bob/baselines/ (EC-7); subsequent gates compare not-worse-than; baselines updated on successful merge.

**Technical Notes**:

- `scripts/compute_gates.py`: Extended here if send-back verdict schema needs fields; verdict JSON is part of every checking role's return contract (T005 step 7).

**Acceptance Criteria**:

- [ ] `AC-1` A surviving-mutant fixture drives Hardener to add tests until mutation ≥ threshold without any send-back.
- [ ] `AC-2` A QA semantic failure sends the slice back to Coder at most return_limit times, then stops with a diagnosis.

**Test Scenarios**:

- `TS-1` (e2e)
  - Given: fixture code with a known surviving mutant
  - When: the hardener stage runs
  - Then: new test kills the mutant; mutation gate passes; return_count unchanged
  - Verification: automated
- `TS-2` (e2e)
  - Given: QA procedure engineered to fail semantically 4 times
  - When: the slice runs with return_limit 3
  - Then: slice stops failed after 3 send-backs with the diagnosis chain in the report
  - Verification: automated

## `T014` Implement parallel execution of independent slices [US7]

Run independent slices as concurrent worktree pipelines up to parallel_limit; dependent slices wait for predecessors' merges; merge conflicts flag the slice without derailing others.

**Context**: Data parallelism over slices is our substitute for Bob's pipeline overlap — it recovers throughput on multi-slice features.

- **Depends on**: T013, T009
- **Requirements**: FR-017, FR-007
- **Entities**: slice, run-state, run-report
- **Contracts**: cmd-bob-run

**Steps**:

1. **Build the dependency schedule** — Topologically order slices by depends_on; ready set = slices whose predecessors are merged; spawn up to parallel_limit concurrent slice pipelines, each in its own worktree .worktrees/bob-<feature>-<slice> with its own state.yaml.
2. **Serialize merges** — Merges into the feature branch happen one at a time in completion order per the merge protocol; after each merge, re-evaluate the ready set; dependent slices branch from the post-merge head.
3. **Handle conflicts** — Unresolvable merge conflict → slice flagged failed-merge with diagnosis, worktree preserved for inspection, remaining slices continue.

**Technical Notes**:

- `commands/bob-run.md`: Slice pipelines are spawned as parallel subagent chains; the orchestrator owns all merges — roles never merge.

**Acceptance Criteria**:

- [ ] `AC-1` Two independent slices run concurrently in separate worktrees; a third dependent slice starts only after its predecessor merges.
- [ ] `AC-2` An injected merge conflict flags only that slice; the others complete and merge.

**Test Scenarios**:

- `TS-1` (e2e)
  - Given: a feature with slices S1, S2 independent and S3 depends_on S1
  - When: /bob-run executes with parallel_limit 2
  - Then: S1 and S2 overlap in time; S3 starts after S1 merges; wall time ≈ longest chain, not the sum
  - Verification: automated

## `T015` Implement /bob-config command [P] [US8]

Write commands/bob-config.md: show the current config in readable form; discuss and apply changes (models, thresholds, tools, routes, limits, BDD option) with validation; reject invalid changes with reasons.

**Context**: The frozen init decisions must stay revisable through a safe, validated channel instead of hand-editing YAML.

- **Depends on**: T007
- **Requirements**: FR-018
- **Entities**: pipeline-config, role, tool-registry-entry
- **Contracts**: cmd-bob-config

**Steps**:

1. **Implement show mode** — No change request → render config as grouped tables (roles/models, gates/thresholds, tools per category, limits, modes); missing config → not-initialized.
2. **Implement change application** — Parse requested changes; tool changes outside the registry require the research-and-confirm path from /bob-init; apply to a copy, run scripts/validate_config.py, on success overwrite and output the old→new diff.
3. **Implement rejection** — Validation failures → outcome invalid-change listing each violation (unknown role, threshold out of range, tool without parser); config untouched.

**Technical Notes**:

- `commands/bob-config.md`: Reuses validate_config.py and the registry-research flow from bob-init — no duplicated validation logic.

**Acceptance Criteria**:

- [ ] `AC-1` Changing hardener's model and the mutation threshold produces a valid updated config and a two-line diff.
- [ ] `AC-2` Setting mutation threshold to 150 is rejected with an explanation; the file is unchanged.

**Test Scenarios**:

- `TS-1` (integration)
  - Given: an initialized fixture
  - When: /bob-config applies 'hardener model sonnet, mutation 85'
  - Then: config validates; diff shows both changes
  - Verification: automated

## `T016` Build fixture mini-projects [P] [US2]

Create tests/fixtures/csharp-calculator, ts-todo, and python-stats: minimal git projects with test runners, seeded defects (a surviving mutant, a duplication hotspot) for gate testing.

**Context**: Every e2e scenario in quickstart needs a small real project where tool output is predictable.

- **Depends on**: T001
- **Requirements**: FR-002, FR-015
- **Entities**: tool-registry-entry
- **Contracts**: —

**Steps**:

1. **Create csharp-calculator** — xUnit + coverlet configured; Calculator class with a branch not killed by existing tests (surviving mutant seed).
2. **Create ts-todo** — vitest configured; a deliberately duplicated helper for the jscpd gate.
3. **Create python-stats** — pytest configured; mutmut-compatible layout; one over-complex function for the lizard baseline test.
4. **Script fixture reset** — tests/fixtures/reset.py re-initializes each fixture's git state so e2e runs are repeatable.

**Technical Notes**:

- `tests/fixtures/`: Each fixture is its own git repo (init on reset), not a submodule of the plugin repo.

**Acceptance Criteria**:

- [ ] `AC-1` Each fixture's native test suite passes; seeded defects are detected by the corresponding registry tool.

**Test Scenarios**:

- `TS-1` (integration)
  - Given: a reset csharp fixture
  - When: Stryker.NET runs
  - Then: at least one surviving mutant is reported
  - Verification: automated

## `T017` Run e2e validation per quickstart and write user docs [US2]

Execute all eight quickstart scenarios against the fixtures, fix findings, and write docs/README.md (installation from the marketplace repo, first run, config reference, troubleshooting).

**Context**: The plugin ships to colleagues; the quickstart scenarios are the acceptance gauntlet for the plugin itself, and the README is what colleagues actually read.

- **Depends on**: T007, T008, T009, T010, T011, T012, T013, T014, T015, T016
- **Requirements**: FR-020, FR-016
- **Entities**: run-report
- **Contracts**: cmd-bob-init, cmd-bob-run, cmd-bob-config

**Steps**:

1. **Execute quickstart scenarios 1–8** — Follow specs/001-bob-pipeline-plugin/quickstart.md exactly on the fixtures; record outcome per scenario; fix defects and re-run until all pass.
2. **Write docs/README.md** — Sections: what this is (Bob's flow, 30-second pitch), install (plugin marketplace add from the GitHub repo), /bob-init walkthrough, daily usage (/bob-run, skips, night mode), config reference table, troubleshooting (EC outcomes and what to do).
3. **Final repo pass** — Root README links to docs; plugin.json version bumped to 1.0.0; all English-language check on shipped files.

**Technical Notes**:

- `docs/README.md`: Written for a colleague who has never seen SwarmForge; no internal jargon.

**Acceptance Criteria**:

- [ ] `AC-1` All eight quickstart scenarios pass on the fixtures.
- [ ] `AC-2` A fresh install following only docs/README.md reaches a successful first run.

**Test Scenarios**:

- `TS-1` (e2e)
  - Given: a machine with Claude Code and none of this plugin
  - When: docs/README.md installation and first-run steps are followed
  - Then: /bob-init and a first /bob-run succeed on a fixture
  - Verification: automated

