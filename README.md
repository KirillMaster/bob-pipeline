# bob-pipeline

A Claude Code plugin implementing Uncle Bob's AI development flow ([SwarmForge](https://github.com/unclebob/swarm-forge)): six role subagents — Specifier, Coder, Cleaner, Architect, Hardener, QA — with a **test gauntlet instead of code review**. You approve the Gherkin intent before any code exists and read the QA report at the end; the code itself is guarded by mutation testing, complexity/duplication baselines, and traced acceptance tests.

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
```

## Repository layout

- `commands/` — `/bob-init`, `/bob-run`, `/bob-config`
- `agents/` — the six role subagent templates
- `templates/` — config, Gherkin, report, run-state, and merge-protocol templates
- `registry/` — quality tool registry per stack (mutation, coverage, complexity, duplication)
- `scripts/` — mechanical layer: config validation, report parsing, gate computation
- `tests/` — pytest suite for scripts + fixture mini-projects
- `specs/` — the yamlkit specification this plugin was built from

License: MIT
