#!/usr/bin/env python3
"""Validate a Spec Kit YAML artifact: schema conformance, NEEDS CLARIFICATION markers, dangling id references.

Usage: validate.py <schema-path> <yaml-path>
Exit 0 on success, 1 on any violation (printed as a JSON list to stderr).
"""
import sys
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, RefResolver

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"

REF_KEYS = {
    "depends_on", "story_ref", "story_refs", "requirement_refs",
    "entity_refs", "contract_refs", "target_entity_ref",
    "implements_ref", "principle_id",
}


def load_schema_store():
    store = {}
    for path in SCHEMAS_DIR.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        schema_id = schema.get("$id")
        if schema_id:
            store[schema_id] = schema
    return store


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def nearest_owner_id(document, path):
    node = document
    owner_id = None
    for key in path:
        if isinstance(node, dict):
            if isinstance(node.get("id"), str):
                owner_id = node["id"]
            node = node.get(key)
        elif isinstance(node, list):
            try:
                node = node[key]
            except (IndexError, TypeError):
                break
        else:
            break
    if isinstance(node, dict) and isinstance(node.get("id"), str):
        owner_id = node["id"]
    return owner_id


def schema_violations(schema, document):
    store = load_schema_store()
    resolver = RefResolver(base_uri=schema.get("$id", ""), referrer=schema, store=store)
    validator = Draft202012Validator(schema, resolver=resolver)
    violations = []
    for error in sorted(validator.iter_errors(document), key=str):
        path = list(error.absolute_path)
        message = error.message
        owner_id = nearest_owner_id(document, path)
        if owner_id is not None:
            message += " (in {0!r})".format(owner_id)
        violations.append({
            "type": "schema",
            "path": path,
            "message": message,
        })
    return violations


def needs_clarification_violations(document):
    violations = []

    def walk(node, path):
        if isinstance(node, str):
            if "NEEDS CLARIFICATION" in node:
                violations.append({
                    "type": "needs_clarification",
                    "path": path,
                    "message": "Unresolved NEEDS CLARIFICATION marker: {0!r}".format(node),
                })
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, path + [k])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, path + [i])

    walk(document, [])
    return violations


def collect_ids(node, ids):
    if isinstance(node, dict):
        if isinstance(node.get("id"), str):
            ids.add(node["id"])
        for v in node.values():
            collect_ids(v, ids)
    elif isinstance(node, list):
        for v in node:
            collect_ids(v, ids)


def build_id_registry(yaml_path):
    ids = set()
    feature_dir = Path(yaml_path).resolve().parent
    sibling_names = [
        "spec.yaml", "plan.yaml", "tasks.yaml", "data-model.yaml", "contracts.yaml", "constitution.yaml",
        "adr.yaml", "open-questions.yaml", "error-codes.yaml", "tracker-sync-map.yaml",
        "decision-log.yaml", "checklist.yaml", "clarify-qa.yaml", "verification-report.yaml",
    ]
    for name in sibling_names:
        sibling = feature_dir / name
        if sibling.exists():
            collect_ids(load_yaml(sibling), ids)
    constitution_path = Path(__file__).resolve().parent.parent / "memory" / "constitution.yaml"
    if constitution_path.exists():
        collect_ids(load_yaml(constitution_path), ids)
    return ids


def dangling_reference_violations(document, yaml_path):
    registry = build_id_registry(yaml_path)
    collect_ids(document, registry)
    violations = []

    def check_ref(value, path, owner_id):
        if value not in registry:
            message = "Reference {0!r} does not resolve to any known id".format(value)
            if owner_id is not None:
                message += " (referenced from {0!r})".format(owner_id)
            violations.append({
                "type": "dangling_reference",
                "path": path,
                "message": message,
            })

    def walk(node, path, owner_id):
        if isinstance(node, dict):
            current_owner = node["id"] if isinstance(node.get("id"), str) else owner_id
            for k, v in node.items():
                if k in REF_KEYS and v is not None:
                    if isinstance(v, list):
                        for i, item in enumerate(v):
                            if isinstance(item, str):
                                check_ref(item, path + [k, i], current_owner)
                    elif isinstance(v, str):
                        check_ref(v, path + [k], current_owner)
                walk(v, path + [k], current_owner)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, path + [i], owner_id)

    walk(document, [], None)
    return violations


def main():
    if len(sys.argv) != 3:
        print(json.dumps([{"type": "usage", "message": "usage: validate.py <schema-path> <yaml-path>"}]), file=sys.stderr)
        sys.exit(1)

    schema_path, yaml_path = sys.argv[1], sys.argv[2]
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    document = load_yaml(yaml_path)

    violations = []
    violations.extend(schema_violations(schema, document))
    violations.extend(needs_clarification_violations(document))
    violations.extend(dangling_reference_violations(document, yaml_path))

    if violations:
        print(json.dumps(violations, indent=2), file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
