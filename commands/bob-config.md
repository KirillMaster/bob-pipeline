---
description: Show or change the frozen bob-pipeline configuration — thresholds, models, gates, tools — with validation before anything is written
argument-hint: "[show | \"<change request>\"]"
---

# /bob-config — inspect and change pipeline configuration

Config file: `.claude/bob-pipeline.yaml`. Plugin assets under `${CLAUDE_PLUGIN_ROOT}`.

## Preconditions

No `.claude/bob-pipeline.yaml` → **STOP**, outcome `not-initialized`: suggest `/bob-init`. Never create the config here.

## Mode 1 — show (no arguments, or "show")

Read the config and present it as compact tables:

- **Roles**: role | enabled | model | gates
- **Tools**: category | tool | run command | enabled
- **Human gates**: gherkin_approval, qa_report
- **Thresholds**: mutation_score_min, coverage_policy, complexity_policy, duplication_policy
- **Flow**: send_back_routes, return_limit, parallel_limit, night_mode_default
- **BDD framework**: value or "none (plain Gherkin + test tags)"

## Mode 2 — change (arguments describe a change)

1. Interpret the request against the config structure (e.g. "raise mutation threshold to 90", "hardener on opus", "disable QA report gate", "switch mutation tool to X").
2. **Tool changes**: if the requested tool is not in `${CLAUDE_PLUGIN_ROOT}/registry/tool-registry.yaml` for this stack, research it (WebSearch), confirm with the user (tool, run command, report format), and require a `report_parser` supported by `scripts/parse_reports.py`; no fitting parser → refuse the change and explain.
3. Apply the change to a proposed new config **in memory**.
4. Validate: `python ${CLAUDE_PLUGIN_ROOT}/scripts/validate_config.py <proposed> --schema ${CLAUDE_PLUGIN_ROOT}/schemas/bob-pipeline.schema.json`.
   - **Exit non-zero** → outcome `invalid-change`: show the JSON violations in plain language (e.g. "coder cannot be disabled — Specifier and Coder are non-skippable"), leave the file untouched.
   - **Exit 0** → write the file.
5. Report a diff of what changed (`setting: old → new`) and note it takes effect on the next `/bob-run` (a run already in progress keeps its frozen values).

Guardrails: never disable `specifier` or `coder`; `mutation_score_min` 0–100; send-back routes must target existing enabled roles — these are enforced by the validator, but say so up front instead of round-tripping when the request obviously violates them.
