# Worktree & merge protocol

The single exit point for pipeline changes into the user's branch (P4). Only the
orchestrator (/bob-run) executes merges — roles never merge.

## Worktree lifecycle

1. **Create** (per slice, from the user's current branch head — or, for a dependent
   slice, from the post-merge head of its last predecessor):

   ```
   git worktree add .worktrees/bob-<feature>-<slice> -b bob/<feature>/<slice> <base>
   ```

2. **Seed** the worktree: `.bob/features/` (approved Gherkin), `.bob/state.yaml`
   (from templates/state.yaml), baselines.

3. Roles work and commit ONLY inside this worktree. One labeled commit per role:
   `bob(<role>): <slice> — <gist>`. The per-role diff is the audit trail.

## Merge preconditions (all required)

- Every configured gate for every executed role: `passed: true` (from compute_gates.py output).
- QA verdict for the slice: all scenarios `pass`.
- One labeled commit per non-skipped role present on the slice branch (verified via `git log`).
- Working test suite green at the slice branch head.

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
     full test suite; green → proceed, red → abort the merge (`git merge --abort`).
   - Non-trivial or red after resolve: `git merge --abort`, mark the slice
     `failed` (reason: merge-conflict) in state and report, **preserve its worktree**
     for inspection, continue with remaining slices.
4. After a successful merge: re-evaluate slices whose `depends_on` are now all merged —
   they become eligible to start (their worktrees branch from the new head).
5. Update baselines (complexity/duplication) from the merged head.

## Cleanup

- Merged slice: `git worktree remove .worktrees/bob-<feature>-<slice>` and
  `git branch -d bob/<feature>/<slice>` (safe delete — must already be merged).
- Failed slice: keep both worktree and branch; the report links to them.
- Rejected run (human rejected Gherkin): remove worktrees and branches created for it.
