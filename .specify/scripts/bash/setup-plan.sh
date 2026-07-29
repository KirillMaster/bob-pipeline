#!/usr/bin/env bash
set -euo pipefail

JSON_MODE=false
for arg in "$@"; do
    case "$arg" in
        --json) JSON_MODE=true ;;
        --help|-h)
            echo "Usage: ./setup-plan.sh [--json] [--help]"
            echo "  --json     Output results in JSON format"
            echo "  --help     Show this help message"
            exit 0
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

get_feature_paths
mkdir -p "$FEATURE_DIR"

# Gate (hard abort): spec.yaml must exist and pass its schema before planning starts
if [[ ! -f "$FEATURE_SPEC" ]]; then
    echo "ERROR: spec.yaml not found in $FEATURE_DIR" >&2
    echo "Run /speckit-specify first to create the feature specification." >&2
    exit 1
fi
if ! invoke_validation_gate spec "$FEATURE_SPEC" "$REPO_ROOT"; then
    echo "ERROR: $FEATURE_SPEC failed schema validation. Fix the violations above before proceeding to planning." >&2
    exit 1
fi

if [[ -f "$IMPL_PLAN" ]]; then
    if $JSON_MODE; then
        echo "Plan already exists at $IMPL_PLAN, skipping template copy" >&2
    else
        echo "Plan already exists at $IMPL_PLAN, skipping template copy"
    fi
else
    template="$(resolve_template plan-template "$REPO_ROOT" || true)"
    if [[ -n "$template" && -f "$template" ]]; then
        cp "$template" "$IMPL_PLAN"
        if $JSON_MODE; then
            echo "Copied plan template to $IMPL_PLAN" >&2
        else
            echo "Copied plan template to $IMPL_PLAN"
        fi
    else
        if $JSON_MODE; then
            echo "Warning: Plan template not found" >&2
        else
            echo "Warning: Plan template not found"
        fi
        : > "$IMPL_PLAN"
    fi
fi

if $JSON_MODE; then
    printf '{"FEATURE_SPEC":"%s","IMPL_PLAN":"%s","SPECS_DIR":"%s","BRANCH":"%s"}\n' \
        "$FEATURE_SPEC" "$IMPL_PLAN" "$FEATURE_DIR" "$CURRENT_BRANCH"
else
    echo "FEATURE_SPEC: $FEATURE_SPEC"
    echo "IMPL_PLAN: $IMPL_PLAN"
    echo "SPECS_DIR: $FEATURE_DIR"
    echo "BRANCH: $CURRENT_BRANCH"
fi
