# bob-pipeline 1.3.0 — design contract

Extends `design-1.2.0.md`; D1–D15 stay in force unchanged unless a D16+ item says otherwise.
Motivation (Langfuse, 30 days): coder 46% of role wall time, hardener 25%, qa 15%; send-backs 23% of slices; orchestrator overhead only 7%. Levers: run independent work concurrently, make each send-back fixable in one pass, measure it, and move cheap mechanical quality checks (lint/format/arch/diff-coverage/traceability) into the pipeline instead of discovering them in CI.

## D16. Hardener and QA run concurrently
- After `architect` passes, the orchestrator launches `hardener` and `qa` in ONE message (two Agent calls). QA makes no code edits; the hardener edits tests only, so they cannot conflict on files.
- Git isolation: both cannot commit in the same worktree at once (index lock). QA runs in a detached worktree `.worktrees/bob-<feature>-<slice>-qa` created at the architect commit (`git worktree add --detach`); its commit is the role-labeled audit commit there. After both return, the orchestrator removes the QA worktree and records `git commit --allow-empty -m "bob(qa): <slice> — <verdict> (ran at <sha>, parallel)"` on the slice branch.
- Merge rule: hardener `pass` with test changes → QA results stay valid, EXCEPT procedures whose referenced files (test files, paths, commands in `.qa.md`) intersect the hardener's diff. `python scripts/parallel_plan.py qa-rerun --changed <files...> --qa <.qa.md...>` prints the procedure ids to re-run; the orchestrator re-spawns QA once with `only_procedures: [...]` and merges the verdicts. Empty list → nothing to re-run.
- Either role `send-back` → route to `coder` (the other result is discarded: code will change); both re-run after the fix. A mechanical hardener repair stays in place.
- Config: `parallel.hardener_qa: true` (default); `false` restores the sequential 1.2 order. If either role is skipped/disabled the chain is sequential anyway.

## D17. Independent slices in parallel worktrees
- The specifier declares per slice `files: [<path or dir prefix>, ...]` (production + test paths it expects to touch) in `.slices.yaml`.
- Slices are independent iff neither depends (transitively) on the other AND their `files` sets are disjoint (a path equal to, or under, another entry counts as overlap). A slice without `files` is never run in parallel with a slice that has no declared disjointness, i.e. it runs alone.
- `parallel_plan.py batch --slices <slices.yaml> --merged <ids> --running <ids> --limit <parallel_limit>` returns the next ids to start. Serialized merges (§8) unchanged.

## D18. Send-back carries its evidence
- qa/architect send-back: the report holds a section `## Send-back` with, per failing procedure/finding: id, expected vs actual and the EXACT failing output excerpt (≤40 lines per item, verbatim, trimmed to the failing frames). The JSON `diagnosis` (≤300 chars) = failing procedure ids + `report: <path>`.
- The orchestrator passes the report path and diagnosis to `coder` unread (D3 holds); the coder reads the `## Send-back` section itself and fixes all listed items in one pass (one commit), re-running only the listed tests before its final full run.

## D19. Instrumentation
- The orchestrator appends one JSON line per role run to `<bob_root>/.bob/metrics.jsonl` via `scripts/bob_metrics.py append`: `{"kind":"role","role","slice","start","end","verdict","send_back_reason"}` (ISO-8601 UTC). Day-mode approval waits: `{"kind":"approval","what","start","end","wait_s"}`, timestamps taken before asking the user and after the answer.
- `bob_metrics.py summarize <file>` prints JSON: per-role runs, wall seconds, share %, send-back count/rate; total approval wait; per-slice wall time.
- `.bob/metrics.jsonl` is untracked (`.bob/` is in `.git/info/exclude`, D15).

## D20. Quality gates (QG) — registry and config
- Enabled by default; `quality_gates.enabled: false` turns all off, `quality_gates.gates.<gate>: false` one gate. Configs without the section behave as enabled, but a QG gate with no enabled tool of its category for the stack passes with a note (so unmigrated projects are not broken).
- New registry categories: `lint` (warnings-as-errors build + analyzers), `format` (`dotnet format --verify-no-changes`; prettier / ruff format `--check`), `architecture` (arch tests), `diff-coverage` (≥ `quality_gates.diff_coverage_min`, default 80), `constitution-traceability`. They are NOT part of the "every stack resolves every category" registry rule (that stays on the original four).
- Gates: `lint`, `format`, `architecture` — BLOCKING; `diff-coverage`, `constitution-traceability` — BLOCKING at the merge gate only (informational total coverage, D4, unchanged).
- Arch tests: ArchUnitNET via `KirillMaster.QualityGates.Architecture` (pet remotes), `TenenGroup.ArchitectureRules` (remote URL contains `tenengroup`); build/analyzer props via `KirillMaster.QualityGates.Build` / `TenenGroup.QualityGates.Build`. Tests are tagged `Category=Architecture`, are fast and part of the fast suite. The package repos are owned elsewhere (referenced by id only).
- Report parsers: `exitcode` (file with the exit code on line 1 + output tail; 0 = pass), `diff-cover` (json `total_percent_covered`), `constitution-trace` (`scripts/constitution_trace.py`: every NON-NEGOTIABLE principle needs a non-empty `gate_condition`; each `verified_by` entry (optional field; absent from yamlkit schema 1.x, so the check is a no-op until yamlkit adds it) must appear in the green-tests list; no constitution → no-op).
- compute_gates: new gates `lint`, `format`, `architecture`, `diff-coverage`, `constitution-traceability`, `hardening-findings`; pseudo-role `merge-gate` (gates: `tests-green`, `diff-coverage`, `constitution-traceability`).

## D21. QG placement (per D2/D14)
- coder final run and architect: warnings-as-errors build (lint), format check, arch tests (`Category=Architecture`) — all fast. Failure = mechanical in-place repair by the same role.
- merge gate (the single full run): coverage run → `diff-cover` ≥ threshold, `constitution_trace.py`. Failure → one in-place repair by `coder`, then the gate once more (as for tests-green).
- Legacy net48 projects are never wired (D23) and have no QG tools: gates pass with a note.

## D22. Mutation never blocks; the hardener is semantic by default
- Default hardener mode = semantic analysis: the LLM reviews tests against the slice code for surviving-mutant-like gaps (missing assertions, untested branches, boundaries, error paths, weak equality) and strengthens tests immediately. Every discrepancy found is fixed in the same run.
- An UNFIXED finding is blocking: gate `hardening-findings` (metric `unfixed_findings`, from the hardener report) → `send-back` when > 0.
- Mutation frameworks (Stryker/mutmut/PIT) run ONLY with `mutation.framework_enabled: true` (default false), as an extra on top of the semantic pass. `mutation-score` below `thresholds.mutation_score_min` is a DEVIATION (gate `passed: true`, `deviation: true`, diagnosis recorded), never a block. This supersedes the 1.2 "hard gate".
- The validator requires `hardener.degradation` only when `mutation.framework_enabled: true` and the mutation tool is disabled.

## D23. bob-init and upgrade step `qg`
- bob-init (C#, `net8.0`+ only; `net4x`/netframework skipped and listed) offers: (1) the Build package reference via `Directory.Build.props` (created or patched, idempotent), (2) an arch test project skeleton `tests/<Solution>.Architecture.Tests` (xunit, `Category=Architecture`, ArchUnitNET), (3) constitution principles (next free `P<n>` ids, as the yamlkit schema requires; lint, format, architecture, new-code coverage; severity NON-NEGOTIABLE) with `gate_condition` naming the gates and the Architecture tests, when `.specify/memory/constitution.yaml` exists. Package ids are chosen by git remote (pet vs tenengroup).
- `upgrade_project.py --steps qg` (opt-in, never in the default steps): adds `quality_gates`/`mutation` sections and registry QG tools to the config (backup `bob-pipeline.yaml.bak-pre-1.3`), adds QG gates to role gates, applies the C# wiring, patches the constitution. `--dry-run` reports without writing. `--qg-version` overrides the pinned package version.

## D24. Release
- Version 1.3.0 in `plugin.json` and `marketplace.json`; CHANGELOG, README updated; tag `v1.3.0`.
