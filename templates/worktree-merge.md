# Worktree & merge protocol

The single exit point for pipeline changes into the user's branch (P4). Only the
orchestrator (/bob-run) executes merges — roles never merge.

## Worktree lifecycle

1. **Create** (per slice, from the user's current branch head — or, for a dependent
   slice, from the post-merge head of its last predecessor):

   ```
   git worktree add .worktrees/bob-<feature>-<slice> -b bob/<feature>/<slice> <base>
   ```

2. **No seeding.** Bob files (`.claude/bob-pipeline.yaml`, `.claude/agents/bob/`, `.bob/`, `.worktrees/`) are untracked (`.git/info/exclude`), so the worktree does not contain them. Approved Gherkin/QA files, baselines and the slice state (`.bob/slices/<slice>/state.yaml`, from templates/state.yaml) stay in the MAIN root; roles get absolute `bob_root` paths.

3. Roles work and commit ONLY inside this worktree. One labeled commit per role:
   `bob(<role>): <slice> — <gist>`. The per-role diff is the audit trail.

## Merge preconditions (all required)

- Every configured gate for every executed role: `passed: true` (from compute_gates.py output).
- QA verdict for the slice: all scenarios `pass`.
- One labeled commit per non-skipped role present on the slice branch (verified via `git log`).
- **Merge gate run (D2/D4/D14)**: after qa passes, in the slice worktree: exactly one fast full-suite run (`tests.coverage_command` if configured, else `tests.run_command`), then — when `tests.integration_command` is set and `tests.integration_at` is `merge-gate` (default) — exactly one integration run. Both exit 0. Their exit codes and the coverage feed compute_gates — role claims are not a source. With `integration_at: run-end` the integration run is not part of the slice gate (see Run end).

## Merge steps

1. Merges are **serialized**: one slice at a time, in completion order, even when
   slices ran in parallel.
2. From the user's branch (main working copy, not a worktree):

   ```
   git merge --no-ff --no-squash bob/<feature>/<slice>
   ```

   **Never squash** — per-role commits ARE the audit trail (P3).
3. On conflict:
   - Trivial (non-overlapping semantic intent, e.g. adjacent imports): resolve, run the
     fast full test suite (`tests.run_command`); green → proceed, red → abort the merge (`git merge --abort`).
   - Non-trivial or red after resolve: `git merge --abort`, mark the slice
     `failed` (reason: merge-conflict) in state and report, **preserve its worktree**
     for inspection, continue with remaining slices.
4. After a successful merge: re-evaluate slices whose `depends_on` are now all merged —
   they become eligible to start (their worktrees branch from the new head).
5. Update baselines (complexity/duplication) from the merged head.

## Run end (D14)

`tests.integration_at: run-end` and `tests.integration_command` set: after the LAST slice is merged, run the integration suite once on the base branch (main working copy). Failure → run outcome `completed-with-failures` + diagnosis in the report; never auto-revert merges. No other integration run happens anywhere.

## Cleanup

- Merged slice (**mandatory**, right after the merge): `git worktree remove .worktrees/bob-<feature>-<slice>` then `git branch -d bob/<feature>/<slice>` (safe delete — must already be merged). Verify: `git worktree list` no longer shows the path and `git branch --list bob/<feature>/<slice>` is empty. Any failure → recorded deviation, never silent.
- Interrupted-run detection ignores worktrees whose branch is merged into the base (`git branch --merged <base>`) or whose state is `merged`.
- Failed slice: keep both worktree and branch; the report links to them.
- Rejected run (human rejected Gherkin): remove worktrees and branches created for it.

## Parallel QA worktree (D16)

The detached `.worktrees/bob-<feature>-<slice>-qa` worktree is removed (`git worktree remove --force`) as soon as QA returns, before the merge gate; it is never merged and has no branch. `git worktree list` must not show it afterwards (leftover = recorded deviation).
