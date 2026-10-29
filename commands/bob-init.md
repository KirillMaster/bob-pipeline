---
description: "Initialize the bob-pipeline: detect stack, interview for config, freeze quality tools from the registry; --upgrade migrates a project"
argument-hint: "[stack_override, e.g. 'python'] | --upgrade [--dry-run]"
---

# /bob-init — initialize the bob-pipeline

Set up the pipeline in the current project; decisions are frozen into `.claude/bob-pipeline.yaml` (deterministic, offline later runs). `$ARGUMENTS`: optional stack override, or `--upgrade` (see "Upgrade mode"). Plugin files (registry, templates, schemas, scripts) live under `${CLAUDE_PLUGIN_ROOT}`.

## 1. Preconditions

1. `.claude/bob-pipeline.yaml` exists → **STOP**, outcome `already-initialized`: show the path, suggest `/bob-config`. Never overwrite.
2. `git rev-parse --git-dir` fails → **STOP**, outcome `not-a-git-repo` (needs worktrees, per-role commits): suggest `git init`.
3. Detect test infrastructure (runner config / test project) and **integration tests**: projects/dirs/files named `*Integration*`, `Category=Integration` traits, `@pytest.mark.integration`, Testcontainers/docker-compose in tests. Missing test infra → warning for final `warnings[]`; don't stop (Coder can set it up).

## 2. Stack detection

`$ARGUMENTS` names a stack → use it. Else scan markers:

| Marker | Stack |
|---|---|
| `*.csproj` / `*.sln` | csharp |
| `package.json` (+`tsconfig.json`) | typescript |
| `pyproject.toml` / `setup.py` / `setup.cfg` | python |
| `pom.xml` / `build.gradle*` | java |

Multiple or zero matches → ask which stack (one question, offer detected candidates).

## 3. Tool selection

Load `${CLAUDE_PLUGIN_ROOT}/registry/tool-registry.yaml`. Per category (mutation, coverage, complexity, duplication) resolve: stack-specific entry → `any` fallback.

**Unresolved category** (stack outside registry) → outcome path `unknown-stack-research`:
1. WebSearch maintained tools for that category and stack (e.g. "mutation testing tool for <stack> 2026").
2. Present candidates (tool, run command, report format); user confirms one or declines.
3. Confirmed → freeze as a tool entry (`report_parser` must be a handler in `scripts/parse_reports.py`; none fits → treat as declined).
4. Declined/none usable → category `enabled: false` + warning; the dependent role runs degraded (deviation per run).

## 4. Interview

**One question at a time**, defaults preselected, read from `${CLAUDE_PLUGIN_ROOT}/templates/bob-pipeline.yaml` (single source; never restate from memory):

1. Roles: full five-role pipeline? (default yes; specifier and coder can't be disabled)
2. Per-role models (template `roles[].model`)
3. Human gates (default ON: Gherkin approval before code; final QA report)
4. Mutation score threshold (`thresholds.mutation_score_min`)
5. Send-back limit / parallel slice limit (`return_limit` / `parallel_limit`)
6. Integration tests found → propose the split: fast `tests.run_command`/`scoped_command`/`coverage_command` get the stack's `exclude_integration` filter (template `#@ <stack>.exclude_integration`; scoped: `scoped_exclude_integration` where defined); `tests.integration_command` = the stack's `#@ <stack>.integration_command` (adapt to the real integration project/marker); ask `tests.integration_at` (default `merge-gate`; `run-end` = once after the last merge). None found → leave both keys out.
7. Quality gates (default ON, `quality_gates.enabled`): lint, format, architecture blocking; diff-coverage ≥80 and constitution-traceability at the merge gate. Mutation frameworks off by default (`mutation.framework_enabled: false`; hardener is semantic). Ask only if the user wants gates off.
8. Plan conformance (default ON, `plan_conformance.enabled`; coder gate `plan-conformance`) and escalation (`escalation.max_red_iterations`, `on_exhaust`: `specifier` | `stronger_model` + `escalation_model`). Offer the cheap-coder preset: `roles[coder].model: haiku` (specifier/architect stay strong). Ask only if the user wants to change defaults; optional `plan_conformance.protected_paths` / `module_paths` / `edge_check_command` (e.g. the project's architecture-test command).
9. BDD framework binding? (default none: plain Gherkin + test tags; offer only reqnroll / cucumber-js / behave as fits the stack)

"defaults" / "accept all" → skip remaining questions.

## 5. Write config and role agents

1. Instantiate `${CLAUDE_PLUGIN_ROOT}/templates/bob-pipeline.yaml`: fill `{{PROJECT_NAME}}` (repo/dir name), `{{STACK}}`, `{{TOOLS}}` (frozen YAML list from step 3, incl. each tool's registry `scope_flag`), `{{TESTS_RUN_COMMAND}}`/`{{TESTS_SCOPED_COMMAND}}`/`{{TESTS_COVERAGE_COMMAND}}` (template `#@ <stack>.<key>` default lines for the detected stack, `{sln}` → detected solution/project file, `{filter}` kept literally; also `tests.warmup_command` from `<stack>.warmup_command` if present; unknown stack → ask for the commands, omit scoped/coverage if none). Apply interview answers (uncomment `integration_command`/`integration_at` only if the split was accepted).
2. Write `.claude/bob-pipeline.yaml`.
3. Validate: `python ${CLAUDE_PLUGIN_ROOT}/scripts/validate_config.py .claude/bob-pipeline.yaml --schema ${CLAUDE_PLUGIN_ROOT}/schemas/bob-pipeline.schema.json`. Non-zero → fix per the JSON violations and re-validate; never leave an invalid config.
4. Instantiate the five role templates `${CLAUDE_PLUGIN_ROOT}/agents/*.md` into `.claude/agents/bob/`: replace `{{PROJECT_NAME}}`, `{{DOMAIN}}` (one line inferred from README/codebase), `{{TECH_STACK}}`, `{{TOOLS}}` (tool names + run commands relevant to the role). These project-local copies are what `/bob-run` spawns.
5. Local-only files and permissions: `python ${CLAUDE_PLUGIN_ROOT}/scripts/upgrade_project.py --project . --steps support` — writes `.claude/bob-pipeline.yaml`, `.claude/agents/bob/`, `.bob/`, `.worktrees/` to `.git/info/exclude` (via `git rev-parse --git-common-dir`; local, shared by all worktrees; NOT `.gitignore`), and merges `permissions.allow` for the configured test/scoped/coverage/mutation commands into `.claude/settings.json` (existing entries kept).
6. **Quality-gate wiring**, C# only: run `python ${CLAUDE_PLUGIN_ROOT}/scripts/upgrade_project.py --project . --steps qg --dry-run`, show the report, ask once whether to apply (default yes). Only `net8.0`+ projects (legacy `net4x` listed as skipped): `Directory.Build.props` PackageReference of the Build package, arch test project skeleton, constitution principles (when `.specify/memory/constitution.yaml` exists), config QG tools/gates. Package ids follow the git remote: `tenengroup` → `TenenGroup.QualityGates.Build` (0.3.0) / `TenenGroup.ArchitectureRules` (2.0.0), else `KirillMaster.QualityGates.Build` / `.Architecture`. Other stacks get only the registry's lint/format tools from step 3.

## 6. Report — outcome `initialized`

Output exactly:
- `config_path`: `.claude/bob-pipeline.yaml`
- `stack`: detected/confirmed stack
- `tools_selected`: table category → tool (mark `enabled: false` rows)
- `warnings`: missing test infra, disabled categories (empty list if none)
- Next step hint: `/bob-run "<feature description>"`.

## Upgrade mode — `/bob-init --upgrade [--dry-run]`

Requires `.claude/bob-pipeline.yaml` (else `not-initialized`). Never asks interview questions.

1. Start with the dry run and show the JSON report: `python ${CLAUDE_PLUGIN_ROOT}/scripts/upgrade_project.py --project . --dry-run`. `--dry-run` in `$ARGUMENTS` → stop here.
2. Otherwise run without `--dry-run`. Deterministic parts: config migration (`cleaner` merged into `architect`, `tests.*` added from template defaults, `scope_flag` added to mutation tools; old file kept as `bob-pipeline.yaml.bak-pre-1.2`, comments not preserved), `.git/info/exclude` entries (never `.gitignore`), integration-exclusion filter on test commands when `tests.integration_command` is set, `permissions.allow` merge, removal of `.claude/agents/bob/cleaner.md`.
3. Agent files merge 3-way per role: base = old plugin template (from plugin git history; refs `v1.1.0`, `3456188`, `v1.0.0`, `d7caca1`, or `--old-ref <ref>`) rendered with placeholder values recovered from the project copy; ours = project copy; theirs = new template rendered with the same values; combined by `git merge-file`. Filled placeholders and customizations survive; new template text is taken. Exit 1 = conflict markers (`project` / `old-template` / `new-template`) left in the reported files: resolve by hand (or ask the user). Placeholders with no old value are listed in `unresolved`; fill them as in step 5.4. `no-old-template` → regenerate that file as in init, re-apply customizations manually.
4. Validate the migrated config (`validate_config.py`); report changes, files merged/conflicted/removed, permissions and ignore entries added.
5. Plan conformance (1.8.0, step `plan`, in the default steps): adds the coder gate `plan-conformance` and the `plan_conformance` / `escalation` sections with template defaults; old config kept as `bob-pipeline.yaml.bak-1.7`, changed agent files as `<role>.md.bak-1.7`. Ask once whether to enable it (default yes); no → run `--steps config,agents,support`. Rollout from 1.7.x: `--steps agents,plan --old-ref <1.7.0 commit>`.
6. Quality gates (opt-in): `--steps qg` (dry run first) adds `quality_gates`/`mutation`/`parallel` config sections and tools/gates, and for C# net8+ the Directory.Build.props wiring, arch test skeleton, constitution principles. Never in default steps; offer, apply only on yes.
7. Tracked bob files (committed by an earlier version): run once more with `--steps untrack` (`git rm -r --cached`, files stay, nothing committed); tell the user to commit the removal, one PR per repo. Config-only projects (no agent copies) → `--steps config,support`.
