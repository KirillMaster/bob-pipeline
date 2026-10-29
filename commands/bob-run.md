---
description: Run a feature through the Uncle Bob pipeline (Specifier → Coder → Architect → Hardener → QA) in an isolated worktree with mechanical gates
argument-hint: "[\"feature description\"] [skip <roles>] [--night] [--resume] [--one-slice]"
---

# /bob-run — run a feature through the pipeline

You are the **orchestrator**: spawn role subagents, verify their commits, compute gates via scripts, route failures, merge, report. Never write feature code. Verdicts come ONLY from `compute_gates.py` output, never your judgment of code or role claims.

**Context budget**: from each role return parse ONLY the final JSON line `{"role","slice","verdict","commit","report","diagnosis"}` plus `git log --oneline -5`. Never read report files; pass their paths onward unread.

**Metrics**: around every role spawn take `date -u +%Y-%m-%dT%H:%M:%SZ` before and after, then `python ${CLAUDE_PLUGIN_ROOT}/scripts/bob_metrics.py append --file <bob_root>/.bob/metrics.jsonl --kind role --role <role> --slice <slice> --start <ts> --end <ts> --verdict <verdict> [--send-back-reason <diagnosis, ≤120 chars>]`. Day mode: time every wait for the user and append `--kind approval --what <gherkin|resume|failure> --start <ts> --end <ts>`. Never read the file back (`bob_metrics.py summarize <file>` is for the user/final report).

**Yamlkit**: bob implements yamlkit tasks (`.specify/`: yamlkit owns spec → plan → tasks). `.specify/` exists → its artifacts are the input (integration mode, §2) and `.specify/memory/constitution.yaml` is binding; else standalone and every constitution rule is a no-op.

**Main root**: bob files (`.claude/bob-pipeline.yaml`, `.claude/agents/bob/`, `.bob/`, `.worktrees/`) are untracked (`.git/info/exclude`), absent from slice worktrees. `<bob_root>` = parent of `git rev-parse --path-format=absolute --git-common-dir` (MAIN root, also when started inside a worktree). Read config, role prompts, `.bob/run-state.yaml`, baselines, slice state ONLY from `<bob_root>`. Roles get `bob_root` in task context and use `.bob/` there by absolute path.

Plugin paths: `${CLAUDE_PLUGIN_ROOT}`. Config: `<bob_root>/.claude/bob-pipeline.yaml`. Role prompts: `<bob_root>/.claude/agents/bob/<role>.md`. Scout prompt is plugin-only (`${CLAUDE_PLUGIN_ROOT}/agents/scout.md`, no project copy).

## 0. Parse `$ARGUMENTS`

- Quoted/free text → `feature_description`; `skip <role>[, ...]` / "skipping X" / `skip_roles:` → skip list; `--night` (or `night_mode_default: true`) → night mode; `--resume` → prefer resuming; `--one-slice` → §10 (no chat memory; context from state + report files).
- Inline overrides ("return limit 5") apply to this run only; never modify the config file.
- Legacy `cleaner` in config roles/order/skip list/`send_back_routes` → `architect`; note a deviation.
- **Skip validation (before any work)**: unknown role → error listing valid roles. `specifier` or `coder` skipped → **refuse to start**: "Specifier and Coder are non-skippable: without them there is no approved intent and no implementation."

## 1. Preconditions

1. No `<bob_root>/.claude/bob-pipeline.yaml` → **STOP**, `not-initialized`, suggest `/bob-init`.
2. Validate: `python ${CLAUDE_PLUGIN_ROOT}/scripts/validate_config.py <bob_root>/.claude/bob-pipeline.yaml --schema ${CLAUDE_PLUGIN_ROOT}/schemas/bob-pipeline.schema.json`; invalid → stop, suggest `/bob-config`.
2a. Session cwd inside a desktop-app `.claude/worktrees/<name>/` sandbox → **STOP**, `sandboxed-session` (bob needs `<bob_root>` = MAIN root and creates `.worktrees/bob-*` there; the sandbox blocks Writes outside itself). Tell the user to run from the main checkout (or a session with `use_worktree: false`), naming the main root.
3. `git status --porcelain` non-empty (bob files excluded) → **STOP**, `dirty-working-copy`; suggest commit/stash.
4. **Interrupted run?** `.worktrees/bob-*` with `<bob_root>/.bob/slices/<slice>/state.yaml`, branch NOT in `git branch --merged <base>`, state not `merged` → `interrupted-run-found`: show feature/slice/role position. Day: ask resume-or-discard (discard = remove that run's worktrees + branches). Night or `--resume`: auto-resume (§7).
5. No test infrastructure → `no-test-infra`: day: offer "let Coder set it up" vs stop; night: Coder sets it up, record deviation.

## 2. Input mode

**Constitution**: `<bob_root>/.specify/memory/constitution.yaml` exists → pass `constitution: <path>` in EVERY role's task context, else `constitution: none`. Never pass or read `constitution.md`. A `spec-change:` diagnosis goes to the user (day: stop the slice and show it; night: slice `failed`); the fix is a yamlkit run.

- `feature_description` given → **standalone mode**.
- Else yamlkit artifacts: `.specify/feature.json` → its feature dir, else newest `specs/*/` with `spec.yaml|spec.md`. Found (with tasks file) → **integration mode**: Specifier input = spec + tasks; slices map 1:1 to task groups preserving `depends_on`; scenario ids reuse spec story ids. None → error, ask for a description.

## 3. Specifier phase

Spawn **specifier** (Agent tool): `model` from `roles[specifier].model`, **always passed explicitly** (frontmatter model ignored, bug #44385); label `bob:specifier [<model>]`. Prompt = `.claude/agents/bob/specifier.md` + feature input + `bob_root` + `constitution` + output location `<bob_root>/.bob/features/` (no worktree yet, no commit). Return JSON carries `"slices_file"`: read the slice breakdown from it (the one small file you may read; path relative to `<bob_root>`), not the prose. Missing/unparseable → role failure.

## 4. Approval gate

`human_gates.gherkin_approval` true (default):
- **Day** → `awaiting-approval`: present scenario ids + titles, feature/QA file paths, slice breakdown with dependencies (files verbatim only on request). Ask approve / reject with feedback.
  - Approve → sha256 of every approved artifact (+ spec/tasks sources in integration mode) → `input_checksums`.
  - Reject → re-run Specifier with the feedback (each rework counts against `return_limit`); limit exhausted or final rejection → `rejected`: remove staging artifacts.
- **Night** → mark scenarios `auto-approved-night`, record checksums, add a deviation. Zero questions.

## 5. Worktree setup

Follow `${CLAUDE_PLUGIN_ROOT}/templates/worktree-merge.md` exactly. Per ready slice: `git worktree add .worktrees/bob-<feature>-<slice> -b bob/<feature>/<slice> <base>`; `<base>` = user's branch head (dependent slices: post-merge head of the last predecessor). Slice state → `<bob_root>/.bob/slices/<slice>/state.yaml` (from `templates/state.yaml`); nothing seeded into the worktree.

**Warm build**: right after `git worktree add`, if `tests.warmup_command` is set, run it once in the slice worktree BEFORE the first role spawn (foreground, never background). Failure non-fatal: continue, record (command, exit code, last lines) in the slice report. Later test commands assume restored packages (`--no-restore` for .NET). Worktrees are separate checkouts (`bin/`/`obj/` already per-worktree, no `--artifacts-path`); `-nodeReuse:false` keeps MSBuild nodes unshared across parallel worktrees.

**Baselines**: `<bob_root>/.bob/baselines.json` missing → run the configured complexity/duplication tools on base, parse via `parse_reports.py`, store `{"complexity": <max_ccn>, "duplication": <pct>}`.

## 6. Role loop (per slice)

For each enabled role in config order minus the skip list (record `skipped_roles`). When `parallel.hardener_qa` is true (default) and `hardener` and `qa` are both enabled and not skipped, run them concurrently (§6a).

0. **Scout.** Only when the next role is `coder`, it is the slice's FIRST coder pass (not send-back) and `scout.enabled` is not false: spawn `${CLAUDE_PLUGIN_ROOT}/agents/scout.md`, `model: haiku`, label `bob:scout:<slice> [haiku]`, cwd = slice worktree. Context: scout prompt (fill `{{PROJECT_NAME}}`/`{{DOMAIN}}`/`{{TECH_STACK}}` from config) + `bob_root` + slice (id, title, scenario_refs) + approved feature/QA paths. Scout is NOT a config role: no gates, no commit to verify, no `return_limit` accounting; failure non-fatal (non-`pass` verdict or missing report → deviation, continue without digest). On success pass `scout_report: <absolute path>` (when the file exists) in the task context of coder, architect, hardener, qa, send-back passes included (scout runs once per slice).
1. Update the slice's `state.yaml` (`current_slice`, `current_role`); **write state at every role boundary**.
2. Spawn the role: explicit `model` from config, label `bob:<role>:<slice> [<model>]`, cwd = slice worktree. Context: role prompt + `bob_root` + `constitution` + slice (id, title, scenario_refs) + approved feature/QA paths (absolute, under `<bob_root>/.bob/features/`) + config tool commands and thresholds (incl. `lint`/`format`/`architecture` commands unless `quality_gates.enabled` is false, and `mutation.framework_enabled`) + (send-back) diagnosis and absolute report path, unread (coder reads its `## Send-back` section).
3. On return parse the JSON line and **verify the commit** (`git log --oneline -5` contains `bob(<role>): <slice>`; roles use `--allow-empty` for artifact-only work). Missing → one retry telling the agent to commit; still missing → role failure (day: ask the user; night: slice `failed`, continue).
4. **Compute gates**: `python ${CLAUDE_PLUGIN_ROOT}/scripts/compute_gates.py --config <bob_root>/.claude/bob-pipeline.yaml --role <role> --metrics <metrics.json> --baselines <bob_root>/.bob/baselines.json --tests-exit <exit> [--traceability <trace.json>]`; `metrics.json` = `parse_reports.py` output on the role's tool reports. Append GateResults to the run's collection.
   - **Quality gates**: `quality_gates.enabled` (default true) / `quality_gates.gates.<name>` select which of `lint`, `format`, `architecture` (coder + architect gates), `diff-coverage`, `constitution-traceability` (merge gate) are computed. Feed tool reports through `parse_reports.py` (`exitcode-lint|format|architecture`, `diff-cover`) and `constitution_trace.py` into `metrics.json`. Mutation never blocks: `mutation-score` below threshold is a deviation; `hardening-findings` blocks.
   - **Merge gate**: after qa passes, before merge, in the slice worktree run exactly ONE fast full suite (`tests.coverage_command` if present, else `tests.run_command`) and, when `tests.integration_command` is set and `tests.integration_at` is `merge-gate` (default), exactly ONE integration run. Same step, when `diff-coverage`/`constitution-traceability` are enabled: diff-cover on that run's coverage XML (`quality_gates.diff_coverage_min`, default 80) and `constitution_trace.py` (green-tests list from the same run), then `compute_gates.py --role merge-gate`. `--tests-exit` is non-zero if either run failed; coverage comes from the fast run only. You run no other full-suite, integration or standalone coverage runs; no role runs integration tests. Integration failure → mechanical `tests-green` failure (one in-place `coder` repair with the diagnosis, then the gate once more).
5. **Route failures**:
   - **Mechanical gate failed** (lint, format, architecture, hardening-findings, complexity/duplication-baseline, tests-green): re-spawn the SAME role once with the gate diagnosis; still failing → semantic failure below.
   - **Constitution**: `send-back` with diagnosis `constitution:<principle id>` = normal semantic send-back to `coder` (counts toward `return_limit`). `spec-change:` → not routable (§2). `recommended` findings are deviations only.
   - **Semantic `send-back`** (architect, qa, hardener): diagnosis `naming` (qa `procedure-not-executable`: test name/path mismatch) → route to coder (or specifier to fix `.qa.md`), does NOT increment `return_count`. Otherwise increment the slice's `return_count`. Over `return_limit` → day: stop the slice, show the diagnosis chain, ask the user; night: slice `failed` with diagnosis, continue others. Within limit → route per `send_back_routes` (qa→coder; architect→coder as the verdict names; `cleaner`→`architect`), continue forward from the target role.
   - Approved-artifact checksums changed mid-run (check at each boundary) → `stale-approval`: list changed artifacts; day: require re-approval; night: slice failed.

## 6a. Hardener and QA in parallel

After the architect passes:
1. `git worktree add --detach .worktrees/bob-<feature>-<slice>-qa <architect commit>`.
2. In ONE message spawn `bob:hardener:<slice>` (cwd = slice worktree) and `bob:qa:<slice>` (cwd = QA worktree, context notes parallel mode). Log metrics per role.
3. Verify commits (hardener in slice worktree, qa in QA worktree), `git worktree remove` the QA worktree, record on the slice branch: `git commit --allow-empty -m "bob(qa): <slice> — <verdict> (ran at <sha>, parallel)"`.
4. Either `send-back` → route to coder, discard the other result; after the fix re-run architect, then both again.
5. Both pass: take hardener's changed files (`git diff --name-only <architect sha>..HEAD`), run `python ${CLAUDE_PLUGIN_ROOT}/scripts/parallel_plan.py qa-rerun --changed <files> --qa <.qa.md paths>`. Non-empty → spawn QA once more in the slice worktree with `only_procedures: [ids]` and merge verdicts (failure = normal qa send-back). Empty → QA's result stands.
6. Compute gates per role as in §6.4; continue to the merge gate.

## 7. Resume

1. Read `<bob_root>/.bob/slices/<slice>/state.yaml` for unfinished slice(s).
2. Recompute input checksums; mismatch → `stale-approval` (re-approval; night: slice failed).
3. Match → find the last verified `bob(<role>)` commit on the slice branch; continue from the **next** role; never repeat completed roles. Note the resume in the report.

## 8. Parallel slices

- Topologically order by `depends_on`; ready = all predecessors `merged`.
- Parallel only if neither depends on the other AND specifier-declared `files` are disjoint. Pick with `python ${CLAUDE_PLUGIN_ROOT}/scripts/parallel_plan.py batch --slices <slices_file> --merged <ids> --running <ids> --failed <ids> --limit <parallel_limit>`; slices without `files` run alone.
- Run up to `parallel_limit` ready slices concurrently (role chains in one message, multiple Agent calls), each in its own worktree and state.
- **Merges are serialized** in completion order per the merge protocol; after each merge re-evaluate readiness (dependents branch from the new head).
- Merge conflict → per protocol: trivial-resolve-and-test or abort → slice `failed` (merge-conflict), worktree preserved, others continue.

## 9. Merge & report

Per slice with all gates passed + QA ok + merge-gate run green: merge per `templates/worktree-merge.md` (**no squash**), then its mandatory cleanup (worktree remove + `branch -d` + `git worktree list` verification; failure = deviation), update baselines.

Final report from `${CLAUDE_PLUGIN_ROOT}/templates/run-report.md` → `.bob/reports/run-<run_id>.md`: summary; per-slice results (scenario verdicts + evidence links, per-role commit shas, gates table, send-backs used); **deviations** (every skip, degradation, auto-approval, exhausted limit, merge conflict, resume); metrics snapshot (baseline → after).

**Run-end integration**: `tests.integration_at: run-end` with `tests.integration_command` set → after the last slice merges, run integration once on the base branch (in `--one-slice` mode: in the invocation merging the last slice); failure → `completed-with-failures` + diagnosis in the report, no auto-revert.

Outcome: `completed` (all slices merged) or `completed-with-failures` (some failed/skipped, or run-end integration failed; only passing slices merged). Day: present the report; night: leave it as the morning report (final message = path + summary).

## Night mode invariants

Zero interactive questions. Day prompt → night behavior: approval → auto-approve+flag; resume prompt → auto-resume; role failure / limit exhausted / stale approval / merge conflict → slice failed + diagnosis, continue; no-test-infra → Coder sets it up + deviation.

## 10. One-slice mode (`--one-slice`)

Each invocation handles **exactly one slice** and exits; `scripts/bob-loop.ps1` re-invokes it in a fresh session. Re-read everything from disk. Always night semantics.

Run state: `<bob_root>/.bob/run-state.yaml` (main root). Fields: `feature`, `run_id`, `base_branch`, `input_checksums`, `slices[]` (`id`, `depends_on`, `status`: `pending|merged|failed|skipped`, `return_count`, `failure`), `deviations[]`, `report`. Writes to it and slice `state.yaml` are atomic (temp file + rename).

0. **Idempotency.** Each slice not `merged` whose `bob/<feature>/<slice>` is in `git branch --merged <base>` → set `merged` in `run-state.yaml`, clean up leftover worktree/branch per merge protocol, skip it.
1. **Load state.** `run-state.yaml` missing → fresh run: need `feature_description` (or yamlkit artifacts, §2); run §3 + §4 (auto-approve), write `run-state.yaml` with all slices `pending`, continue to step 2 in the same invocation. Missing and no feature input → `BOB-LOOP: failed` (reason: no run to resume).
2. **Pick the slice.** An unmerged interrupted worktree (§1.4/§7) first; else the first `pending` slice (topological order) whose `depends_on` are all `merged`. No parallelism (§8).
3. **Run it**: §5 worktree, §6 role loop, merge (§9 merge step, no final report yet). Immediately update slice `status` (`merged` or `failed` + diagnosis) and `deviations` in `run-state.yaml`.
4. **Final line:**
   - a `pending` slice with all dependencies `merged` remains → `BOB-LOOP: next`
   - nothing runnable remains (all merged, or rest blocked by failed/skipped) → assemble the §9 report from `run-state.yaml` + per-slice reports, then `BOB-LOOP: done` (all merged) or `BOB-LOOP: failed` (any failed/blocked slice; report path in the line above)
   - unrecoverable error (config invalid, dirty tree, stale approval) → `BOB-LOOP: failed`
5. **Stop.** The very last output line is exactly `BOB-LOOP: next`, `BOB-LOOP: done` or `BOB-LOOP: failed`, nothing after. A failed slice doesn't stop the loop while other independent slices are runnable (`next`).
