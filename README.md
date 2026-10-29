# bob-pipeline

A Claude Code plugin implementing Uncle Bob's AI development flow ([SwarmForge](https://github.com/unclebob/swarm-forge)): five role subagents — Specifier, Coder, Architect (refactor + boundaries), Hardener, QA — with a **test gauntlet instead of code review**. You approve the Gherkin intent before any code exists and read the QA report at the end; the code itself is guarded by quality gates (lint, format, architecture tests, diff coverage, constitution traceability), semantic test hardening, complexity/duplication baselines, and traced acceptance tests.

**bob-pipeline runs on top of yamlkit**: yamlkit owns spec → plan → tasks (`.specify/`), bob implements the tasks. With `.specify/` present, `/bob-run` takes its artifacts as input and treats `.specify/memory/constitution.yaml` as binding (NON-NEGOTIABLE violations send the slice back); without it bob runs standalone. Bob's own files (`.claude/bob-pipeline.yaml`, `.claude/agents/bob/`, `.bob/`, `.worktrees/`) stay out of the project repo (`.git/info/exclude`).

**Full documentation: [docs/README.md](docs/README.md)**

## Quick start

```
/plugin marketplace add KirillMaster/bob-pipeline
/plugin install bob-pipeline
```

Then, inside your project:

```
/bob-init                     # one-time setup interview
/bob-run "describe a feature" # run it through the pipeline
/bob-config                   # view or change the configuration
/bob-init --upgrade           # migrate a 1.0/1.1/1.2 project to 1.3 (see docs/README.md)
/bob-init --upgrade   # then, opt-in quality gates: python <plugin>/scripts/upgrade_project.py --project . --steps qg
```

## Repository layout

- `commands/` — `/bob-init`, `/bob-run`, `/bob-config`
- `agents/` — the five role subagent templates
- `templates/` — config, Gherkin, report, run-state, and merge-protocol templates
- `registry/` — quality tool registry per stack (mutation, coverage, complexity, duplication + quality gates: lint, format, architecture, diff-coverage, constitution-traceability)
- `scripts/` — mechanical layer: config validation, report parsing, gate computation, project upgrade
- `tests/` — pytest suite for scripts + fixture mini-projects
- `specs/` — the yamlkit specification this plugin was built from

License: MIT

## 1.3.0 highlights (design: `docs/design-1.3.0.md`, D16-D24)

- **Parallelism**: hardener and QA run concurrently after the architect (`parallel.hardener_qa`); QA re-runs only procedures touching files the hardener changed; independent slices with disjoint declared `files` run in parallel worktrees up to `parallel_limit`.
- **One-pass send-backs**: QA/architect reports carry a `## Send-back` section (failing procedure ids + exact output, <=40 lines each); the coder reads it directly.
- **Metrics**: `.bob/metrics.jsonl` (role runs, send-back reasons, approval waits); `python scripts/bob_metrics.py summarize .bob/metrics.jsonl`.
- **Bugfix kind and design gates (1.9.0)**: `/bob-run --bugfix` plans one slice with `root_cause` + a red regression test; deterministic gates `bugfix` (KISS K1-K8: root cause bound, no new types/members, immutable tests, no TODO markers, size budget, red-on-base/green-on-head, hunk ablation), `tidy-first` (structural commits change no assertions), `adr` (new interface/module edge needs an ADR), and the PR body rendered from the slice manifest (`pr_description.py`, a purpose per new type).
- **Plan conformance (1.8.0)**: the Specifier emits a slice manifest (`allowed_paths`, `new_types`, `locked_tests`, `allowed_new_edges`); gate `plan-conformance` fails any coder diff outside it or touching locked tests/baselines/config, so a cheap coder model (`roles[coder].model: haiku`) is safe. `escalation` sends a slice back to the Specifier (or a stronger model) after N red gate rounds.
- **Quality gates, on by default** (`quality_gates.enabled: false` or `quality_gates.gates.<name>: false` to opt out): lint, format, architecture block in the coder's final run and the architect; diff-coverage (>=80) and constitution-traceability block at the merge gate. C# net8+ wiring via `KirillMaster.QualityGates.*` (pet) / `TenenGroup.QualityGates.Build` + `TenenGroup.ArchitectureRules` (tenengroup remotes).
- **Mutation never blocks**: the hardener does semantic analysis (unfixed finding = blocking); Stryker/mutmut only with `mutation.framework_enabled: true`, and a low score is a deviation.
- **Upgrade**: `/plugin update`, then `/bob-init --upgrade`, then `python <plugin>/scripts/upgrade_project.py --project . --steps qg` (`--dry-run` first).

