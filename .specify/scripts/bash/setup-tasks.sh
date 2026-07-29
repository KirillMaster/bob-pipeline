#!/usr/bin/env bash
set -euo pipefail

JSON_MODE=false
for arg in "$@"; do
    case "$arg" in
        --json) JSON_MODE=true ;;
        --help|-h)
            echo "Usage: setup-tasks.sh [--json] [--help]"
            exit 0
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

get_feature_paths

if [[ ! -f "$IMPL_PLAN" ]]; then
    echo "ERROR: plan.yaml not found in $FEATURE_DIR" >&2
    echo "Run /speckit-plan first to create the implementation plan." >&2
    exit 1
fi

if [[ ! -f "$FEATURE_SPEC" ]]; then
    echo "ERROR: spec.yaml not found in $FEATURE_DIR" >&2
    echo "Run /speckit-specify first to create the feature structure." >&2
    exit 1
fi

# Gate (hard abort): both spec.yaml and plan.yaml must pass their schemas before task generation starts
if ! invoke_validation_gate spec "$FEATURE_SPEC" "$REPO_ROOT"; then
    echo "ERROR: $FEATURE_SPEC failed schema validation. Fix the violations above before proceeding to task generation." >&2
    exit 1
fi
if ! invoke_validation_gate plan "$IMPL_PLAN" "$REPO_ROOT"; then
    echo "ERROR: $IMPL_PLAN failed schema validation. Fix the violations above before proceeding to task generation." >&2
    exit 1
fi

docs=()
[[ -f "$RESEARCH" ]] && docs+=("research.md")
[[ -f "$DATA_MODEL" ]] && docs+=("data-model.md")
[[ -f "$FEATURE_DIR/data-model.yaml" ]] && docs+=("data-model.yaml")
[[ -f "$FEATURE_DIR/contracts.yaml" ]] && docs+=("contracts.yaml")
if [[ -d "$CONTRACTS_DIR" ]] && [[ -n "$(ls -A "$CONTRACTS_DIR" 2>/dev/null)" ]]; then
    docs+=("contracts/")
fi
[[ -f "$QUICKSTART" ]] && docs+=("quickstart.md")

tasks_template="$(resolve_template tasks-template "$REPO_ROOT" || true)"
if [[ -z "$tasks_template" || ! -f "$tasks_template" ]]; then
    expected="$REPO_ROOT/.specify/templates/tasks-template.md"
    echo "ERROR: Tasks template not found for repository root: $REPO_ROOT" >&2
    echo "Template resolution order: overrides -> core." >&2
    echo "Expected shared/core template location: $expected" >&2
    echo "To continue, verify whether 'tasks-template.yaml'/'tasks-template.md' is available in '.specify/templates/overrides/', or restore the shared/core templates so that '.specify/templates/tasks-template.yaml' exists." >&2
    exit 1
fi

if $JSON_MODE; then
    docs_json="$(printf '"%s",' "${docs[@]:-}")"
    docs_json="[${docs_json%,}]"
    printf '{"FEATURE_DIR":"%s","AVAILABLE_DOCS":%s,"TASKS_TEMPLATE":"%s"}\n' \
        "$FEATURE_DIR" "$docs_json" "$tasks_template"
else
    echo "FEATURE_DIR: $FEATURE_DIR"
    echo "TASKS_TEMPLATE: $tasks_template"
    echo "AVAILABLE_DOCS:"
    for d in "${docs[@]:-}"; do
        [[ -n "$d" ]] && echo "  $d"
    done
fi
