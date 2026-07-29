# Bob pipeline run report — {{RUN_ID}}

**Feature**: {{FEATURE}}
**Mode**: {{MODE}} <!-- day | night -->
**Merged**: {{MERGED}} <!-- true/false — whether passing slices were merged into the user's branch -->

## Summary

{{SUMMARY}}
<!-- e.g. "3 slices: 2 passed and merged, 1 failed (send-back limit exhausted). Feature branch bob/<feature> ready." -->

## Slice results

<!-- One section per slice -->
### {{SLICE_ID}} — {{SLICE_TITLE}} — **{{SLICE_STATUS}}**

| Scenario | Verdict | Evidence |
|----------|---------|----------|
| S1-AS1   | pass    | .bob/reports/qa-S1.md#s1-as1 |

**Commits** (audit trail, one per role):

| Role | Commit | Gist |
|------|--------|------|
| specifier | `<sha>` | ... |

**Gates**:

| Gate | Role | Value | Threshold/Baseline | Passed | Diagnosis |
|------|------|-------|--------------------|--------|-----------|
| mutation-score | hardener | 86 | ≥ 80 | ✅ | |
| coverage-informational | hardener | 91 | — (informational) | — | |

**Send-backs used**: {{RETURN_COUNT}} / {{RETURN_LIMIT}}

## Deviations

<!-- Every deviation from the default flow — honest reporting (P7). Empty section = none. -->
- <!-- role skips ("hardener skipped, per-feature override"), degradations ("no mutation tool for stack X — hardener ran heuristics"), night auto-approvals ("Gherkin auto-approved-night at <time>"), exhausted send-back limits, merge conflicts -->

## Metrics snapshot

| Metric | Before (baseline) | After |
|--------|-------------------|-------|
| max CCN | | |
| duplicated lines % | | |
| line coverage % (informational) | | |
