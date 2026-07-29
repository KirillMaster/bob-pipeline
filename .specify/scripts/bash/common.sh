#!/usr/bin/env bash
# Common bash functions, mirroring common.ps1. Simplified: template resolution
# supports overrides -> core only (this repo has no presets/extensions layer
# yet; add preset/extension lookup here if/when .specify/presets or
# .specify/extensions are introduced).

get_repo_root() {
    if [[ -n "${SPECIFY_INIT_DIR:-}" ]]; then
        local init_dir="$SPECIFY_INIT_DIR"
        [[ "$init_dir" != /* ]] && init_dir="$(pwd)/$init_dir"
        if [[ ! -d "$init_dir" ]]; then
            echo "ERROR: SPECIFY_INIT_DIR does not point to an existing directory: $SPECIFY_INIT_DIR" >&2
            exit 1
        fi
        init_dir="$(cd "$init_dir" && pwd)"
        if [[ ! -d "$init_dir/.specify" ]]; then
            echo "ERROR: SPECIFY_INIT_DIR is not a Spec Kit project (no .specify/ directory): $init_dir" >&2
            exit 1
        fi
        echo "$init_dir"
        return
    fi

    local current
    current="$(pwd)"
    while true; do
        if [[ -d "$current/.specify" ]]; then
            echo "$current"
            return
        fi
        local parent
        parent="$(dirname "$current")"
        if [[ -z "$parent" || "$parent" == "$current" ]]; then
            break
        fi
        current="$parent"
    done

    # Fallback to script location
    cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd
}

get_current_branch() {
    if [[ -n "${SPECIFY_FEATURE:-}" ]]; then
        echo "$SPECIFY_FEATURE"
        return
    fi
    echo ""
}

# Populates FEATURE_DIR, FEATURE_SPEC, IMPL_PLAN, TASKS, RESEARCH, DATA_MODEL,
# QUICKSTART, CONTRACTS_DIR, CURRENT_BRANCH, REPO_ROOT globals.
get_feature_paths() {
    REPO_ROOT="$(get_repo_root)"
    CURRENT_BRANCH="$(get_current_branch)"

    local feature_json="$REPO_ROOT/.specify/feature.json"
    if [[ -n "${SPECIFY_FEATURE_DIRECTORY:-}" ]]; then
        FEATURE_DIR="$SPECIFY_FEATURE_DIRECTORY"
        [[ "$FEATURE_DIR" != /* ]] && FEATURE_DIR="$REPO_ROOT/$FEATURE_DIR"
    elif [[ -f "$feature_json" ]]; then
        FEATURE_DIR="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('feature_directory',''))" "$feature_json" 2>/dev/null)"
        if [[ -z "$FEATURE_DIR" ]]; then
            echo "ERROR: Feature directory not found. Set SPECIFY_FEATURE_DIRECTORY or ensure .specify/feature.json contains feature_directory." >&2
            exit 1
        fi
        [[ "$FEATURE_DIR" != /* ]] && FEATURE_DIR="$REPO_ROOT/$FEATURE_DIR"
    else
        echo "ERROR: Feature directory not found. Set SPECIFY_FEATURE_DIRECTORY or run the specify command to create .specify/feature.json." >&2
        exit 1
    fi

    if [[ -z "$CURRENT_BRANCH" ]]; then
        CURRENT_BRANCH="$(basename "${FEATURE_DIR%/}")"
    fi

    FEATURE_SPEC="$FEATURE_DIR/spec.yaml"
    IMPL_PLAN="$FEATURE_DIR/plan.yaml"
    TASKS="$FEATURE_DIR/tasks.yaml"
    RESEARCH="$FEATURE_DIR/research.md"
    DATA_MODEL="$FEATURE_DIR/data-model.md"
    QUICKSTART="$FEATURE_DIR/quickstart.md"
    CONTRACTS_DIR="$FEATURE_DIR/contracts"
}

# Resolve a template name to a file path: overrides -> core, .yaml preferred
# over .md (legacy templates not yet converted, e.g. research/quickstart).
resolve_template() {
    local template_name="$1"
    local repo_root="$2"
    local base="$repo_root/.specify/templates"

    for ext in yaml md; do
        local override="$base/overrides/$template_name.$ext"
        [[ -f "$override" ]] && { echo "$override"; return; }
    done

    for ext in yaml md; do
        local core="$base/$template_name.$ext"
        [[ -f "$core" ]] && { echo "$core"; return; }
    done

    return 1
}

get_python3_command() {
    if command -v python3 >/dev/null 2>&1; then
        echo "python3"
        return
    fi
    if command -v python >/dev/null 2>&1 && python --version 2>&1 | grep -q "Python 3"; then
        echo "python"
        return
    fi
    return 1
}

# Run the JSON Schema validation gate against a YAML artifact. Returns 0 on
# success. On failure, prints the structured violations to stderr and returns
# 1 -- callers treat this as a hard abort (per US3: no progression on a schema
# violation or dangling reference).
invoke_validation_gate() {
    local schema_name="$1"
    local yaml_path="$2"
    local repo_root="$3"

    local schema_path="$repo_root/.specify/schemas/$schema_name.schema.json"
    local validate_py="$repo_root/.specify/scripts/validate.py"

    local py_cmd
    py_cmd="$(get_python3_command)" || {
        echo "ERROR: no Python 3 interpreter found; cannot run the validation gate for $yaml_path" >&2
        return 1
    }

    "$py_cmd" "$validate_py" "$schema_path" "$yaml_path"
}
