#!/usr/bin/env python3
"""Render a validated Spec Kit YAML artifact to a disposable, human-readable Markdown view.

Usage: render_markdown.py <artifact-type> <yaml-path> <output-md-path>
artifact-type is one of: spec, plan, tasks, constitution

The generated Markdown is a one-way view: it is never read back as input by any
Spec Kit stage. Re-running this command always overwrites the output file, discarding
any hand edits made to it.
"""
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "render"

GENERATED_HEADER = (
    "<!-- GENERATED FILE — DO NOT EDIT BY HAND.\n"
    "     This file is rendered from the corresponding .yaml artifact and will be\n"
    "     overwritten the next time it is regenerated. Edit the .yaml source instead. -->\n\n"
)

TEMPLATE_BY_TYPE = {
    "spec": "spec.md.jinja2",
    "plan": "plan.md.jinja2",
    "tasks": "tasks.md.jinja2",
    "constitution": "constitution.md.jinja2",
}


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def render(artifact_type, yaml_path, output_path):
    template_name = TEMPLATE_BY_TYPE.get(artifact_type)
    if template_name is None:
        raise ValueError("Unknown artifact type: {0!r} (expected one of {1})".format(
            artifact_type, sorted(TEMPLATE_BY_TYPE)))

    document = load_yaml(yaml_path)
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(template_name)
    body = template.render(**document)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(GENERATED_HEADER + body, encoding="utf-8")


def main():
    if len(sys.argv) != 4:
        print("usage: render_markdown.py <artifact-type> <yaml-path> <output-md-path>", file=sys.stderr)
        sys.exit(1)

    artifact_type, yaml_path, output_path = sys.argv[1], sys.argv[2], sys.argv[3]
    render(artifact_type, yaml_path, output_path)
    sys.exit(0)


if __name__ == "__main__":
    main()
