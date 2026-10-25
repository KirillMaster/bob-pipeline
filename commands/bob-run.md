---
description: Run a feature through the Uncle Bob pipeline — Specifier → Coder → Architect → Hardener → QA in an isolated worktree, gauntlet of mechanical gates, merge on pass
argument-hint: "[\"feature description\"] [skip <roles>] [--night] [--resume] [--one-slice]"
---

# /bob-run — run a feature through the pipeline

You are the **orchestrator**. You spawn role subagents, verify their commits, compute gates via scripts, route failures, merge, and report. You never write feature code yourself, and verdicts come ONLY from `compute_gates.py` output — never from your own judgment of the code or from role claims (P1).

**Context budget (D3)**: from each role return parse ONLY the final JSON line `{"role","slice","verdict","commit","report","diagnosis"}` plus `git log --oneline -5`. Never read report files into your context — pass their paths onward (e.g. qa diagnosis + report path to coder, unread).

**Metrics (D19)**: around every role spawn take `date -u +%Y-%m-%dT%H:%M:%SZ` before and after and append the run: `python ${CLAUDE_PLUGIN_ROOT}/scripts/bob_metrics.py append --file <bob_root>/.bob/metrics.jsonl --kind role --role <role> --slice <slice> --start <ts> --end <ts> --verdict <verdict> [--send-back-reason <diagnosis, ≤120 chars>]`. Day mode: time every wait for the user (approval gate, resume prompt, role-failure question) and append `--kind approval --what <gherkin|resume|failure> --start <ts> --end <ts>`. Never read the file back; `bob_metrics.py summarize <file>` is for the user / the final report.

**Runs on top of yamlkit (D13)**: bob-pipeline is the implementation stage of the yamlkit flow (`.specify/`: yamlkit owns spec → plan → tasks, bob owns implementing the tasks). When `.specify/` exists, its artifacts are the input (integration mode, §2) and `.specify/memory/constitution.yaml` is binding. Without `.specify/` bob runs standalone and every constitution rule below is a no-op.

**Main root (D15)**: bob files (`.claude/bob-pipeline.yaml`, `.claude/agents/bob/`, `.bob/`, `.worktrees/`) are untracked (`.git/info/exclude`), so slice worktrees do not contain them. `<bob_root>` = parent of `git rev-parse --path-format=absolute --git-common-dir` (the MAIN project root, also when you were started inside a worktree). Read the config, role prompts, `.bob/run-state.yaml`, baselines and slice state ONLY from `<bob_root>` — never from a slice worktree. Roles get `bob_root` in their task context and read/write `.bob/` artifacts there by absolute path.

Plugin paths below are under `${CLAUDE_PLUGIN_ROOT}`. Config: `<bob_root>/.claude/bob-pipeline.yaml`. Role prompts: `<bob_root>/.claude/agents/bob/<role>.md` (instantiated by /bob-init). The scout prompt is plugin-only (`${CLAUDE_PLUGIN_ROOT}/agents/scout.md`): it carries no project-specific state beyond the placeholders filled at spawn, so projects need no copy of it.

## 0. Parse arguments from `$ARGUMENTS`

- Quoted/free text → `feature_description`.
- `skip <role>[, <role>...]` / "skipping X" / `skip_roles:` → skip list.
- `--night` → night mode (also on if `night_mode_default: true` in config).
- `--resume` → prefer resuming an interrupted run.
- `--one-slice` → one-slice-per-session mode, see §10. Implies no chat memory: all context comes from state + report files.
- Inline overrides ("return limit 5") → per-run overrides. **Overrides apply to this run only — never modify the config file.**

**Legacy `cleaner`**: in config roles/order/skip list/`send_back_routes` treat as `architect` (merged role, D1); note a deviation.

**Skip validation (before any work)**: unknown role name → error listing valid roles. `specifier` or `coder` in the skip list → **refuse to start**: "Specifier and Coder are non-skippable: without them there is no approved intent and no implementation." (FR-010)

## 1. Preconditions

1. No `<bob_root>/.claude/bob-pipeline.yaml` → **STOP**, outcome `not-initialized`: suggest `/bob-init`.
2. Validate config (`python ${CLAUDE_PLUGIN_ROOT}/scripts/validate_config.py <bob_root>/.claude/bob-pipeline.yaml --schema ${CLAUDE_PLUGIN_ROOT}/schemas/bob-pipeline.schema.json`); invalid → stop, suggest `/bob-config`.
3. `git status --porcelain` non-empty (bob files are excluded, so they never count) → **STOP**, outcome `dirty-working-copy`: uncommitted changes prevent a clean worktree base; suggest commit/stash. (EC-3)
4. **Interrupted run?** Any `.worktrees/bob-*` with a `<bob_root>/.bob/slices/<slice>/state.yaml`, whose branch is NOT merged into the base (`git branch --merged <base>`) and whose state is not `merged` → outcome `interrupted-run-found`: show feature/slice/role position from the state. Day mode: ask resume-or-discard. Night mode or `--resume`: resume automatically. See §7. Discard = remove worktrees + branches of that run.
5. No test infrastructure detected → outcome `no-test-infra`: day mode — offer "let Coder set it up" vs stop; night mode — let Coder set it up, record deviation. (EC-1)

## 2. Input mode (FR-009)

**Constitution (D13)**: if `<bob_root>/.specify/memory/constitution.yaml` exists, pass its path as `constitution: <path>` in EVERY role's task context (else `constitution: none`). Never pass or read `constitution.md` (rendered view). Roles never edit `.specify/`; a `spec-change:` diagnosis is surfaced to the user (day: stop the slice and show it; night: slice `failed`) — the fix is a yamlkit run, not a bob action.

- `feature_description` given → **standalone mode**.
- No description → look for yamlkit artifacts: `.specify/feature.json` → its feature dir, else newest `specs/*/` containing `spec.yaml|spec.md`. Found (with tasks file) → **integration mode**: Specifier input = spec content + tasks list; slices map 1:1 to task groups preserving `depends_on`; Gherkin scenario ids reuse the spec's story ids. Nothing found → error: ask for a feature description.

## 3. Specifier phase

Spawn the **specifier** subagent (Agent tool):
- `model`: from config `roles[specifier].model` — **always pass model explicitly** (frontmatter model is ignored, bug #44385). Label: `bob:specifier [<model>]`.
- Prompt: `.claude/agents/bob/specifier.md` content + the feature input + `bob_root` + `constitution` + where to write: `<bob_root>/.bob/features/` (no worktree exists yet; the specifier makes no commit).
- Parse the return JSON: besides the common fields it carries `"slices_file"`. Read the slice breakdown from that file (the one small file you may read; path relative to `<bob_root>`), not from the specifier's prose. Missing/unparseable file → role failure.

## 4. Approval gate (P2, FR-005)

`human_gates.gherkin_approval` is true (default):
- **Day mode** → outcome `awaiting-approval`: present scenario ids + titles, the file paths of the feature/QA files, and the slice breakdown (with dependencies) — not the files verbatim unless the user asks. Ask: approve / reject with feedback.
  - **Approve** → compute sha256 checksums of every approved artifact (+ spec/tasks sources in integration mode) → these go into `input_checksums`.
  - **Reject with feedback** → re-run Specifier with the feedback (each rework counts against `return_limit`); limit exhausted or final rejection → outcome `rejected`: remove any staging artifacts, nothing else was created.
- **Night mode** → mark every scenario `auto-approved-night`, record checksums, add a deviation entry. Zero questions (P7).

## 5. Worktree setup (P4, FR-007)

Follow `${CLAUDE_PLUGIN_ROOT}/templates/worktree-merge.md` exactly. Per slice ready to run:

```
git worktree add .worktrees/bob-<feature>-<slice> -b bob/<feature>/<slice> <base>
```

`<base>` = user's branch head (or post-merge head of the last predecessor for dependent slices). Per-slice state goes to `<bob_root>/.bob/slices/<slice>/state.yaml` (from `templates/state.yaml`); nothing is seeded into the worktree.

**Baselines (EC-7)**: if `<bob_root>/.bob/baselines.json` doesn't exist, capture now: run the configured complexity/duplication tools on the base, parse via `parse_reports.py`, store `{"complexity": <max_ccn>, "duplication": <pct>}`.

## 6. Role loop (per slice)

For each enabled role in config order, minus this run's skip list (skipped slices get `skipped_roles` recorded). **Exception (D16)**: when `parallel.hardener_qa` is true (default) and both `hardener` and `qa` are enabled and not skipped, run them concurrently, see §6a:

0. **Scout (recon, D25).** Only when the next role is `coder`, this is the slice's FIRST coder pass (not a send-back) and `scout.enabled` in config is not false: spawn `${CLAUDE_PLUGIN_ROOT}/agents/scout.md` with `model: haiku`, label `bob:scout:<slice> [haiku]`, cwd = the slice worktree. Context: the scout prompt (fill `{{PROJECT_NAME}}`/`{{DOMAIN}}`/`{{TECH_STACK}}` from config) + `bob_root` + slice (id, title, scenario_refs) + the approved feature/QA paths. The scout is NOT a config role: no gate computation, no commit to verify, no `return_limit` accounting, and a failure is non-fatal — on any non-`pass` verdict or missing report, log a deviation and continue to the coder without a digest. On success pass `scout_report: <absolute path>` into the coder's task context.
1. Update the slice's `state.yaml`: `current_slice`, `current_role`. **State is written at every role boundary.**
2. Spawn the role subagent: explicit `model` from config, label `bob:<role>:<slice> [<model>]`, cwd = the slice worktree. Context: role prompt + `bob_root` + `constitution` + slice (id, title, scenario_refs) + approved feature/QA file paths (absolute, under `<bob_root>/.bob/features/`) + tool commands and thresholds from config (incl. the quality-gate commands for `lint`/`format`/`architecture` when `quality_gates.enabled` is not false, and `mutation.framework_enabled`) + (if send-back) the diagnosis and the absolute report path, passed on unread (D18: the coder reads the report's `## Send-back` section itself).
3. On return parse the JSON line and **verify the labeled commit** (`git log --oneline -5` contains `bob(<role>): <slice>`; roles use `--allow-empty` when they only produced bob artifacts). Missing → one retry instructing the agent to commit; still missing → role failure (day: ask the user; night: mark the slice `failed`, continue).
4. **Compute gates** (P1) for the role's tools: `python ${CLAUDE_PLUGIN_ROOT}/scripts/compute_gates.py --config <bob_root>/.claude/bob-pipeline.yaml --role <role> --metrics <metrics.json> --baselines <bob_root>/.bob/baselines.json --tests-exit <exit> [--traceability <trace.json>]`. `metrics.json` = `parse_reports.py` output on the role's tool reports. Append GateResults to the run's collection.
   - **Quality gates (D20/D21)**: `quality_gates.enabled` (default true) / `quality_gates.gates.<name>` decide which of `lint`, `format`, `architecture` (coder + architect gates), `diff-coverage`, `constitution-traceability` (merge gate) are computed. Feed each tool's report through `parse_reports.py` (`exitcode-lint|format|architecture`, `diff-cover`) and `constitution_trace.py` into `metrics.json`. Mutation never blocks: `mutation-score` below threshold is a deviation (D22); `hardening-findings` blocks.
   - **Merge gate (D2/D4/D14/D21)**: after qa passes, before merge, in the slice worktree run exactly ONE fast full suite (`tests.coverage_command` if present, else `tests.run_command`) and, when `tests.integration_command` is set and `tests.integration_at` is `merge-gate` (default), exactly ONE integration run. In the same step, when `diff-coverage`/`constitution-traceability` are enabled: run diff-cover against the coverage XML of that run (`quality_gates.diff_coverage_min`, default 80) and `constitution_trace.py` (green-tests list from the same run), then call `compute_gates.py --role merge-gate`. `--tests-exit` is non-zero if either failed; the coverage metric comes from the fast run only — never from role claims. No other full-suite, integration or standalone coverage runs by you; no role ever runs integration tests. Integration failure → treat as a mechanical `tests-green` failure (one in-place repair by `coder` with the diagnosis, then the gate once more).
5. **Route failures** (FR-013):
   - **Mechanical gate failed** (lint, format, architecture, hardening-findings, complexity/duplication-baseline, tests-green): re-spawn the SAME role once with the gate diagnosis — in-place repair. Still failing after the repair attempt → treat like a semantic failure below.
   - **Constitution (D13)**: a `send-back` with diagnosis `constitution:<principle id>` is a normal semantic send-back to `coder` (counts toward `return_limit`). Diagnosis `spec-change:` → not routable: see §2. `recommended`-principle findings are only deviations.
   - **Semantic verdict `send-back`** (architect, qa or hardener): Diagnosis `naming` (qa `procedure-not-executable`: test name/path mismatch) → route to coder (or specifier to fix `.qa.md`), does NOT increment `return_count`. Otherwise increment the slice's `return_count`. Over `return_limit` → day: stop the slice, show the diagnosis chain, ask the user; night: mark slice `failed` with the diagnosis, continue with other slices. Within limit → route per config `send_back_routes` (qa→coder; architect→coder as the verdict names; target `cleaner`→`architect`), then continue forward again from the target role.
   - Checksums of approved artifacts changed mid-run (check at each boundary) → outcome `stale-approval`: list changed artifacts, require re-approval (day) / mark slice failed (night). (EC-9)

## 6a. Hardener and QA in parallel (D16)

After the architect passes:
1. Create the QA worktree: `git worktree add --detach .worktrees/bob-<feature>-<slice>-qa <architect commit>`.
2. In ONE message spawn both: `bob:hardener:<slice>` (cwd = slice worktree) and `bob:qa:<slice>` (cwd = QA worktree, context notes parallel mode). Log metrics per role as usual.
3. Verify commits (hardener in the slice worktree; qa in the QA worktree), then `git worktree remove` the QA worktree and record on the slice branch: `git commit --allow-empty -m "bob(qa): <slice> — <verdict> (ran at <sha>, parallel)"`.
4. Either role `send-back` → route to coder; discard the other result (code will change); after the fix re-run architect → both again.
5. Both pass: take the hardener's changed files (`git diff --name-only <architect sha>..HEAD`) and run `python ${CLAUDE_PLUGIN_ROOT}/scripts/parallel_plan.py qa-rerun --changed <files> --qa <.qa.md paths>`. Non-empty → spawn QA once more in the slice worktree with `only_procedures: [ids]` and merge the verdicts (a failure there is a normal qa send-back). Empty → QA's result stands.
6. Compute gates per role as in §6.4 and continue to the merge gate.

## 7. Resume (FR-019, EC-5)

On resume of an interrupted run:
1. Read `<bob_root>/.bob/slices/<slice>/state.yaml` for the unfinished slice(s).
2. Recompute input checksums. Mismatch → outcome `stale-approval` (re-approval required; night: slice failed).
3. Match → find the last verified `bob(<role>)` commit on the slice branch; continue the role loop from the **next** role. Completed roles are never repeated. Note the resume in the report.

## 8. Parallel slices (FR-017)

- Topologically order slices by `depends_on`. Ready = all predecessors `merged`.
- Independence (D17): slices are parallel only if neither depends on the other AND their specifier-declared `files` are disjoint. Choose the next ones with `python ${CLAUDE_PLUGIN_ROOT}/scripts/parallel_plan.py batch --slices <slices_file> --merged <ids> --running <ids> --failed <ids> --limit <parallel_limit>`; slices without `files` run alone.
- Run up to `parallel_limit` ready slices concurrently — spawn their role chains in parallel (one message, multiple Agent calls), each in its own worktree with its own state.
- **Merges are serialized** in completion order per the merge protocol; after each merge re-evaluate readiness (dependent slices branch from the new head).
- Merge conflict → per protocol: trivial-resolve-and-test or abort → slice `failed` (merge-conflict), worktree preserved, others continue.

## 9. Merge & report (FR-007, FR-016)

Per slice with all gates passed + QA ok + merge-gate run green: merge per `templates/worktree-merge.md` (**no squash**), then the mandatory cleanup there (worktree remove + `branch -d` + `git worktree list` verification; failure = recorded deviation), update baselines.

Assemble the final report from `${CLAUDE_PLUGIN_ROOT}/templates/run-report.md` into `.bob/reports/run-<run_id>.md`:
- summary; per-slice results (scenario verdicts + evidence links, per-role commit shas, gates table, send-backs used);
- **deviations** — every skip, degradation, auto-approval, exhausted limit, merge conflict, resume (P7);
- metrics snapshot (baseline → after).

**Run-end integration (D14)**: `tests.integration_at: run-end` with `tests.integration_command` set → after the last slice is merged, run the integration suite once on the base branch; failure → outcome `completed-with-failures` + diagnosis in the report, no auto-revert. (In `--one-slice` mode this happens in the invocation that merges the last slice.)

Outcome: `completed` (all slices merged) or `completed-with-failures` (some failed/skipped, or the run-end integration run failed — only passing slices merged). Present the report to the user (day) / leave it as the morning report (night: surface the path + summary as the final message).

## Night mode invariants (FR-012, P7)

Audit before running in night mode: the night path contains **zero** interactive questions. Every day-mode prompt has a defined night behavior: approval → auto-approve+flag; resume prompt → auto-resume; role failure / limit exhausted / stale approval / merge conflict → mark slice failed + diagnosis, continue; no-test-infra → Coder sets it up + deviation.

## 10. One-slice mode (`--one-slice`)

Purpose: keep the orchestrator context small. Each invocation handles **exactly one slice** and exits; `scripts/bob-loop.ps1` re-invokes it in a fresh session. Never rely on chat memory — everything is re-read from disk.

Run-level state: `<bob_root>/.bob/run-state.yaml` (the main root, never a worktree). Fields: `feature`, `run_id`, `base_branch`, `input_checksums`, `slices[]` (`id`, `depends_on`, `status`: `pending|merged|failed|skipped`, `return_count`, `failure`), `deviations[]`, `report`. 
Writes to `run-state.yaml` and the slice `state.yaml` files are atomic (write temp file + rename). Always night semantics (zero questions, §Night mode invariants). Steps:

0. **Idempotency (D8).** For every slice not yet `merged`: if `bob/<feature>/<slice>` is in `git branch --merged <base>`, set it `merged` in `run-state.yaml` (clean up leftover worktree/branch per merge protocol) and skip it.
1. **Load state.** `.bob/run-state.yaml` missing → fresh run: need `feature_description` (or yamlkit artifacts, §2); run §3 Specifier + §4 (auto-approve) and write `run-state.yaml` with all slices `pending`. Then continue to step 2 in the same invocation. Missing and no feature input → `BOB-LOOP: failed` (reason: no run to resume).
2. **Pick the slice.** An unmerged interrupted worktree (§1.4/§7) takes priority — resume it. Otherwise the first `pending` slice (topological order) whose `depends_on` are all `merged`. Parallelism (§8) is off in this mode.
3. **Run it:** §5 worktree, §6 role loop, merge (§9 merge step, no final report yet). Update slice `status` (`merged` or `failed` + diagnosis) and `deviations` in `run-state.yaml` immediately after.
4. **Decide the final line:**
   - any `pending` slice whose dependencies are all `merged` remains → `BOB-LOOP: next`
   - nothing runnable remains (all merged, or the rest are blocked by failed/skipped) → assemble the §9 report from `run-state.yaml` + per-slice reports, then `BOB-LOOP: done` (all merged) or `BOB-LOOP: failed` (any failed/blocked slice; report path in the line above)
   - unrecoverable error (config invalid, dirty tree, stale approval) → `BOB-LOOP: failed`
5. **Stop.** The very last output line must be exactly `BOB-LOOP: next`, `BOB-LOOP: done` or `BOB-LOOP: failed` — nothing after it. A failed slice does not stop the loop while other independent slices are runnable (`next`).
