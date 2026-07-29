---
description: Initialize the bob-pipeline in this project — detect the stack, interview for configuration (Bob-flow defaults), freeze quality tools from the registry
argument-hint: "[stack_override, e.g. 'python']"
---

# /bob-init — initialize the bob-pipeline

Set up the Uncle Bob pipeline in the current project. All decisions made here are frozen into `.claude/bob-pipeline.yaml` so later runs are deterministic and offline. `$ARGUMENTS` may contain an explicit stack override.

Plugin files referenced below live under `${CLAUDE_PLUGIN_ROOT}` (registry, templates, schemas, scripts).

## 1. Preconditions

1. `.claude/bob-pipeline.yaml` already exists → **STOP** with outcome `already-initialized`: show the config path, suggest `/bob-config` for changes. Never overwrite.
2. `git rev-parse --git-dir` fails → **STOP** with outcome `not-a-git-repo`: the pipeline requires git (worktrees, per-role commits); suggest `git init`.
3. Detect test infrastructure (a test runner config / test project). Missing → record a warning for the final `warnings[]`; do not stop (Coder can set it up during the first run).

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

Ask **one question at a time**, defaults preselected (the defaults ARE Bob's flow):

1. Roles: full six-role pipeline? (default: yes; specifier and coder cannot be disabled)
2. Per-role models (default: sonnet for specifier/coder/cleaner/architect, haiku for hardener/qa)
3. Human gates (default: Gherkin approval before code — ON; final QA report — ON)
4. Mutation score threshold (default: 80)
5. Send-back limit / parallel slice limit (defaults: 3 / 3)
6. BDD framework binding? (default: none — plain Gherkin document + test tags; options: reqnroll / cucumber-js / behave, offer only what fits the stack)

If the user says "defaults" / "accept all", skip the remaining questions.

## 5. Write config and role agents

1. Instantiate `${CLAUDE_PLUGIN_ROOT}/templates/bob-pipeline.yaml`: fill `{{PROJECT_NAME}}` (repo/dir name), `{{STACK}}`, `{{TOOLS}}` (the frozen YAML list from step 3), apply interview answers.
2. Write to `.claude/bob-pipeline.yaml`.
3. Validate: `python ${CLAUDE_PLUGIN_ROOT}/scripts/validate_config.py .claude/bob-pipeline.yaml --schema ${CLAUDE_PLUGIN_ROOT}/schemas/bob-pipeline.schema.json`. Non-zero exit → fix the config per the JSON violations and re-validate; never leave an invalid config behind.
4. Instantiate the six role templates from `${CLAUDE_PLUGIN_ROOT}/agents/*.md` into `.claude/agents/bob/`: replace `{{PROJECT_NAME}}`, `{{DOMAIN}}` (one line inferred from the README/codebase), `{{TECH_STACK}}`, `{{TOOLS}}` (tool names + run commands relevant to that role). These project-local copies are what `/bob-run` spawns.

## 6. Report — outcome `initialized`

Output exactly:
- `config_path`: `.claude/bob-pipeline.yaml`
- `stack`: detected/confirmed stack
- `tools_selected`: table of category → tool (mark `enabled: false` rows)
- `warnings`: missing test infra, disabled categories (empty list if none)
- Next step hint: `/bob-run "<feature description>"`.
