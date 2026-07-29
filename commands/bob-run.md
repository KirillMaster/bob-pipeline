---
description: Run a feature through the Uncle Bob pipeline — Specifier → Coder → Cleaner → Architect → Hardener → QA in an isolated worktree, gauntlet of mechanical gates, merge on pass
argument-hint: "[\"feature description\"] [skip <roles>] [--night] [--resume]"
---

# /bob-run — run a feature through the pipeline

You are the **orchestrator**. You spawn role subagents, verify their commits, compute gates via scripts, route failures, merge, and report. You never write feature code yourself, and verdicts come ONLY from `compute_gates.py` output — never from your own judgment of the code (P1).

Plugin paths below are under `${CLAUDE_PLUGIN_ROOT}`. Config: `.claude/bob-pipeline.yaml`. Role prompts: `.claude/agents/bob/<role>.md` (instantiated by /bob-init).

## 0. Parse arguments from `$ARGUMENTS`

- Quoted/free text → `feature_description`.
- `skip <role>[, <role>...]` / "skipping X" / `skip_roles:` → skip list.
- `--night` → night mode (also on if `night_mode_default: true` in config).
- `--resume` → prefer resuming an interrupted run.
- Inline overrides ("return limit 5") → per-run overrides. **Overrides apply to this run only — never modify the config file.**

**Skip validation (before any work)**: unknown role name → error listing valid roles. `specifier` or `coder` in the skip list → **refuse to start**: "Specifier and Coder are non-skippable: without them there is no approved intent and no implementation." (FR-010)

## 1. Preconditions

1. No `.claude/bob-pipeline.yaml` → **STOP**, outcome `not-initialized`: suggest `/bob-init`.
2. Validate config (`python ${CLAUDE_PLUGIN_ROOT}/scripts/validate_config.py .claude/bob-pipeline.yaml --schema ${CLAUDE_PLUGIN_ROOT}/schemas/bob-pipeline.schema.json`); invalid → stop, suggest `/bob-config`.
3. `git status --porcelain` non-empty → **STOP**, outcome `dirty-working-copy`: uncommitted changes prevent a clean worktree base; suggest commit/stash. (EC-3)
4. **Interrupted run?** Any `.worktrees/bob-*` containing `.bob/state.yaml` → outcome `interrupted-run-found`: show feature/slice/role position from the state. Day mode: ask resume-or-discard. Night mode or `--resume`: resume automatically. See §7. Discard = remove worktrees + branches of that run.
5. No test infrastructure detected → outcome `no-test-infra`: day mode — offer "let Coder set it up" vs stop; night mode — let Coder set it up, record deviation. (EC-1)

## 2. Input mode (FR-009)

- `feature_description` given → **standalone mode**.
- No description → look for yamlkit artifacts: `.specify/feature.json` → its feature dir, else newest `specs/*/` containing `spec.yaml|spec.md`. Found (with tasks file) → **integration mode**: Specifier input = spec content + tasks list; slices map 1:1 to task groups preserving `depends_on`; Gherkin scenario ids reuse the spec's story ids. Nothing found → error: ask for a feature description.

## 3. Specifier phase

Spawn the **specifier** subagent (Agent tool):
- `model`: from config `roles[specifier].model` — **always pass model explicitly** (frontmatter model is ignored, bug #44385). Label: `bob:specifier [<model>]`.
- Prompt: `.claude/agents/bob/specifier.md` content + the feature input + where to write (`.bob/features/` in a temp staging dir for now — pre-worktree).
- Return: slices + feature files + scenario count.

## 4. Approval gate (P2, FR-005)

`human_gates.gherkin_approval` is true (default):
- **Day mode** → outcome `awaiting-approval`: present the Gherkin scenarios, QA procedures, and slice breakdown (with dependencies) verbatim. Ask: approve / reject with feedback.
  - **Approve** → compute sha256 checksums of every approved artifact (+ spec/tasks sources in integration mode) → these go into `input_checksums`.
  - **Reject with feedback** → re-run Specifier with the feedback (each rework counts against `return_limit`); limit exhausted or final rejection → outcome `rejected`: remove any staging artifacts, nothing else was created.
- **Night mode** → mark every scenario `auto-approved-night`, record checksums, add a deviation entry. Zero questions (P7).

## 5. Worktree setup (P4, FR-007)

Follow `${CLAUDE_PLUGIN_ROOT}/templates/worktree-merge.md` exactly. Per slice ready to run:

```
git worktree add .worktrees/bob-<feature>-<slice> -b bob/<feature>/<slice> <base>
```

`<base>` = user's branch head (or post-merge head of the last predecessor for dependent slices). Seed `.bob/features/`, `.bob/state.yaml` (from `templates/state.yaml`), and baselines.

**Baselines (EC-7)**: if `.bob/baselines.json` doesn't exist in the project, capture now: run the configured complexity/duplication tools on the base, parse via `parse_reports.py`, store `{"complexity": <max_ccn>, "duplication": <pct>}`.

## 6. Role loop (per slice)

For each enabled role in config order, minus this run's skip list (skipped slices get `skipped_roles` recorded):

1. Update `.bob/state.yaml`: `current_slice`, `current_role`. **State is written at every role boundary.**
2. Spawn the role subagent: explicit `model` from config, label `bob:<role>:<slice> [<model>]`, cwd = the slice worktree. Context: role prompt + slice (id, title, scenario_refs) + approved feature file paths + tool run commands and thresholds from config + (if send-back) the diagnosis.
3. On return, **verify the labeled commit exists** (`git log --oneline -5` contains `bob(<role>): <slice>`). Missing → one retry instructing the agent to commit; still missing → treat as role failure (day: ask the user; night: mark the slice `failed`, continue).
4. **Compute gates** (P1):
   ```
   python ${CLAUDE_PLUGIN_ROOT}/scripts/compute_gates.py --config .claude/bob-pipeline.yaml \
     --role <role> --metrics <metrics.json> --baselines .bob/baselines.json \
     --tests-exit <exit> [--traceability <trace.json>]
   ```
   `metrics.json` = outputs of `parse_reports.py` for the tools this role ran (from its return / re-run the parse on report files). Append all GateResults to the run's collection.
5. **Route failures** (FR-013):
   - **Mechanical gate failed** (mutation-score, complexity/duplication-baseline, tests-green): re-spawn the SAME role once with the gate diagnosis — in-place repair. Still failing after the repair attempt → treat like a semantic failure below.
   - **Semantic verdict `send-back`** (from architect or qa returns): increment the slice's `return_count`. Over `return_limit` → day: stop the slice, show the diagnosis chain, ask the user; night: mark slice `failed` with the diagnosis, continue with other slices. Within limit → route per config `send_back_routes` (qa→coder; architect→cleaner or coder as the verdict names), then continue forward again from the target role.
   - Checksums of approved artifacts changed mid-run (check at each boundary) → outcome `stale-approval`: list changed artifacts, require re-approval (day) / mark slice failed (night). (EC-9)

## 7. Resume (FR-019, EC-5)

On resume of an interrupted run:
1. Read `.bob/state.yaml` from the worktree(s).
2. Recompute input checksums. Mismatch → outcome `stale-approval` (re-approval required; night: slice failed).
3. Match → find the last verified `bob(<role>)` commit on the slice branch; continue the role loop from the **next** role. Completed roles are never repeated. Note the resume in the report.

## 8. Parallel slices (FR-017)

- Topologically order slices by `depends_on`. Ready = all predecessors `merged`.
- Run up to `parallel_limit` ready slices concurrently — spawn their role chains in parallel (one message, multiple Agent calls), each in its own worktree with its own state.
- **Merges are serialized** in completion order per the merge protocol; after each merge re-evaluate readiness (dependent slices branch from the new head).
- Merge conflict → per protocol: trivial-resolve-and-test or abort → slice `failed` (merge-conflict), worktree preserved, others continue.

## 9. Merge & report (FR-007, FR-016)

Per slice with all gates passed + QA ok: merge per `templates/worktree-merge.md` (**no squash**), clean up its worktree, update baselines.

Assemble the final report from `${CLAUDE_PLUGIN_ROOT}/templates/run-report.md` into `.bob/reports/run-<run_id>.md`:
- summary; per-slice results (scenario verdicts + evidence links, per-role commit shas, gates table, send-backs used);
- **deviations** — every skip, degradation, auto-approval, exhausted limit, merge conflict, resume (P7);
- metrics snapshot (baseline → after).

Outcome: `completed` (all slices merged) or `completed-with-failures` (some failed/skipped — only passing slices merged). Present the report to the user (day) / leave it as the morning report (night: surface the path + summary as the final message).

## Night mode invariants (FR-012, P7)

Audit before running in night mode: the night path contains **zero** interactive questions. Every day-mode prompt has a defined night behavior: approval → auto-approve+flag; resume prompt → auto-resume; role failure / limit exhausted / stale approval / merge conflict → mark slice failed + diagnosis, continue; no-test-infra → Coder sets it up + deviation.
