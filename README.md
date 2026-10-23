# bob-pipeline

A Claude Code plugin implementing Uncle Bob's AI development flow ([SwarmForge](https://github.com/unclebob/swarm-forge)): five role subagents — Specifier, Coder, Architect (refactor + boundaries), Hardener, QA — with a **test gauntlet instead of code review**. You approve the Gherkin intent before any code exists and read the QA report at the end; the code itself is guarded by mutation testing, complexity/duplication baselines, and traced acceptance tests.

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
/bob-init --upgrade           # migrate a 1.0/1.1 project to 1.2 (see docs/README.md)
```

## Repository layout

- `commands/` — `/bob-init`, `/bob-run`, `/bob-config`
- `agents/` — the five role subagent templates
- `templates/` — config, Gherkin, report, run-state, and merge-protocol templates
- `registry/` — quality tool registry per stack (mutation, coverage, complexity, duplication)
- `scripts/` — mechanical layer: config validation, report parsing, gate computation, project upgrade
- `tests/` — pytest suite for scripts + fixture mini-projects
- `specs/` — the yamlkit specification this plugin was built from

License: MIT
