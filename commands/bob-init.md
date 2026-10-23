---
description: Initialize the bob-pipeline in this project — detect the stack, interview for configuration (Bob-flow defaults), freeze quality tools from the registry
argument-hint: "[stack_override, e.g. 'python'] | --upgrade [--dry-run]"
---

# /bob-init — initialize the bob-pipeline

Set up the Uncle Bob pipeline in the current project. All decisions made here are frozen into `.claude/bob-pipeline.yaml` so later runs are deterministic and offline. `$ARGUMENTS` may contain an explicit stack override, or `--upgrade` (see "Upgrade mode" at the end).

Plugin files referenced below live under `${CLAUDE_PLUGIN_ROOT}` (registry, templates, schemas, scripts).

## 1. Preconditions

1. `.claude/bob-pipeline.yaml` already exists → **STOP** with outcome `already-initialized`: show the config path, suggest `/bob-config` for changes. Never overwrite.
2. `git rev-parse --git-dir` fails → **STOP** with outcome `not-a-git-repo`: the pipeline requires git (worktrees, per-role commits); suggest `git init`.
3. Detect test infrastructure (a test runner config / test project). Also detect **integration tests**: projects/dirs/files named `*Integration*`, `Category=Integration` traits, `@pytest.mark.integration`, Testcontainers/docker-compose usage in tests. Missing → record a warning for the final `warnings[]`; do not stop (Coder can set it up during the first run).

## 2. Stack detection

If `$ARGUMENTS` names a stack, use it. Otherwise scan project markers:

| Marker | Stack |
|---|---|
| `*.csproj` / `*.sln` | csharp |
| `package.json` (+`tsconfig.json`) | typescript |
| `pyproject.toml` / `setup.py` / `setup.cfg` | python |
| `pom.xml` / `build.gradle*` | java |

Multiple or zero matches → ask the user which stack this project is (one question, offer the detected candidates).

## 3. Tool selection

Load `${CLAUDE_PLUGIN_ROOT}/registry/tool-registry.yaml`. For each category (mutation, coverage, complexity, duplication), resolve in order: stack-specific entry → `any` fallback.

**Unresolved category** (stack outside the registry) → outcome path `unknown-stack-research`:
1. WebSearch for maintained tools of that category for the stack (e.g. "mutation testing tool for <stack> 2026").
2. Present candidates (tool, run command, report format) and ask the user to confirm one or decline.
3. Confirmed → freeze into the config as a tool entry (`report_parser` must be one of the handlers in `scripts/parse_reports.py`; if no handler fits the tool's report format, treat as declined).
4. Declined / nothing usable → category `enabled: false` + warning; the dependent role will run degraded (recorded per run as a deviation).

## 4. Interview

Ask **one question at a time**, defaults preselected. Every default is read from `${CLAUDE_PLUGIN_ROOT}/templates/bob-pipeline.yaml` (single source — never restate values from memory):

1. Roles: full five-role pipeline? (default: yes; specifier and coder cannot be disabled)
2. Per-role models (defaults: the `roles[].model` values in the template)
3. Human gates (default: Gherkin approval before code — ON; final QA report — ON)
4. Mutation score threshold (template `thresholds.mutation_score_min`)
5. Send-back limit / parallel slice limit (template `return_limit` / `parallel_limit`)
6. Integration tests found → propose the split: fast `tests.run_command`/`scoped_command`/`coverage_command` get the stack's `exclude_integration` filter (template `#@ <stack>.exclude_integration`, scoped: `scoped_exclude_integration` where defined), `tests.integration_command` = the stack's `#@ <stack>.integration_command` (adapt to the project's real integration project/marker), and ask `tests.integration_at` (default `merge-gate`; `run-end` = once after the last merge). None found → leave both keys out.
7. Quality gates (D20, default ON; `quality_gates.enabled`): lint, format, architecture blocking; diff-coverage ≥80 and constitution-traceability at the merge gate. Mutation frameworks off by default (`mutation.framework_enabled: false`, the hardener is semantic). Ask only if the user wants to turn gates off.
8. BDD framework binding? (default: none — plain Gherkin document + test tags; options: reqnroll / cucumber-js / behave, offer only what fits the stack)

If the user says "defaults" / "accept all", skip the remaining questions.

## 5. Write config and role agents

1. Instantiate `${CLAUDE_PLUGIN_ROOT}/templates/bob-pipeline.yaml`: fill `{{PROJECT_NAME}}` (repo/dir name), `{{STACK}}`, `{{TOOLS}}` (the frozen YAML list from step 3, including each tool's registry `scope_flag`), `{{TESTS_RUN_COMMAND}}` / `{{TESTS_SCOPED_COMMAND}}` / `{{TESTS_COVERAGE_COMMAND}}` (the `#@ <stack>.<key>` default lines in the template for the detected stack, with `{sln}` replaced by the detected solution/project file; keep `{filter}` literally; unknown stack → ask the user for the commands, omit scoped/coverage if none), apply interview answers (uncomment `integration_command` / `integration_at` only when the integration split was accepted).
2. Write to `.claude/bob-pipeline.yaml`.
3. Validate: `python ${CLAUDE_PLUGIN_ROOT}/scripts/validate_config.py .claude/bob-pipeline.yaml --schema ${CLAUDE_PLUGIN_ROOT}/schemas/bob-pipeline.schema.json`. Non-zero exit → fix the config per the JSON violations and re-validate; never leave an invalid config behind.
4. Instantiate the five role templates from `${CLAUDE_PLUGIN_ROOT}/agents/*.md` into `.claude/agents/bob/`: replace `{{PROJECT_NAME}}`, `{{DOMAIN}}` (one line inferred from the README/codebase), `{{TECH_STACK}}`, `{{TOOLS}}` (tool names + run commands relevant to that role). These project-local copies are what `/bob-run` spawns.
5. Local-only files and permissions: `python ${CLAUDE_PLUGIN_ROOT}/scripts/upgrade_project.py --project . --steps support` — writes `.claude/bob-pipeline.yaml`, `.claude/agents/bob/`, `.bob/`, `.worktrees/` to `.git/info/exclude` (via `git rev-parse --git-common-dir`; local, shared by all worktrees; NOT `.gitignore`, so teammates see nothing), and merges `permissions.allow` entries for the configured test/scoped/coverage/mutation commands into `.claude/settings.json` (existing entries are kept, nothing is overwritten).

6. **Quality-gate wiring (D23)**, C# only: run `python ${CLAUDE_PLUGIN_ROOT}/scripts/upgrade_project.py --project . --steps qg --dry-run`, show the report and ask once whether to apply it (default yes). It handles only `net8.0`+ projects (legacy `net4x` are listed as skipped): `Directory.Build.props` PackageReference of the Build package, an arch test project skeleton, constitution principles (when `.specify/memory/constitution.yaml` exists) and the config's QG tools/gates. Package ids follow the git remote: `tenengroup` → `TenenGroup.QualityGates.Build` (0.3.0) / `TenenGroup.ArchitectureRules` (2.0.0), else `KirillMaster.QualityGates.Build` / `.Architecture`. Other stacks get the registry's lint/format tools from step 3 only.

## 6. Report — outcome `initialized`

Output exactly:
- `config_path`: `.claude/bob-pipeline.yaml`
- `stack`: detected/confirmed stack
- `tools_selected`: table of category → tool (mark `enabled: false` rows)
- `warnings`: missing test infra, disabled categories (empty list if none)
- Next step hint: `/bob-run "<feature description>"`.

## Upgrade mode — `/bob-init --upgrade [--dry-run]`

For a project initialized with 1.0.x/1.1.x. Requires `.claude/bob-pipeline.yaml` (else `not-initialized`). Never asks interview questions.

1. Always start with the dry run and show the JSON report: `python ${CLAUDE_PLUGIN_ROOT}/scripts/upgrade_project.py --project . --dry-run`. With `--dry-run` in `$ARGUMENTS`, stop here.
2. Otherwise run it without `--dry-run`. Deterministic parts: config migration (`cleaner` merged into `architect`, `tests.*` added from the template defaults, `scope_flag` added to mutation tools; old file kept as `bob-pipeline.yaml.bak-pre-1.2`, comments are not preserved), `.git/info/exclude` entries (never `.gitignore`), the integration-exclusion filter on the test commands when `tests.integration_command` is set, `permissions.allow` merge, removal of `.claude/agents/bob/cleaner.md`.
3. Agent files are merged 3-way per role: base = the old plugin template (read from the plugin git history; refs `v1.1.0`, `3456188`, `v1.0.0`, `d7caca1`, or `--old-ref <ref>`) rendered with the placeholder values recovered from the project copy; ours = the project copy; theirs = the new template rendered with the same values; combined by `git merge-file`. Filled placeholders and project customizations survive; new template text is taken. Exit 1 means conflict markers (`project` / `old-template` / `new-template`) were left in the reported files — resolve them by hand (or ask the user). Placeholders new in 1.2.0 that had no old value are listed in `unresolved`; fill them as in step 5.4 of init. No usable old template (`no-old-template`) → regenerate that file as in init and re-apply customizations manually.
4. Validate the migrated config (`validate_config.py`) and report: changes, files merged/conflicted/removed, permissions and ignore entries added.
5. Quality gates (opt-in, 1.3.0): `--steps qg` (dry run first) adds the `quality_gates`/`mutation`/`parallel` config sections and tools/gates, and for C# net8+ the Directory.Build.props wiring, arch test skeleton and constitution principles (D23). Never part of the default steps; offer it, apply only on a yes.
6. Tracked bob files (committed by an earlier version): run once more with `--steps untrack` (`git rm -r --cached`, files stay on disk, nothing committed) and tell the user to commit the removal — one PR per repo. Without agent copies in the project (config-only) use `--steps config,support`.
