#!/usr/bin/env python3
"""Best-effort MD -> YAML migration for legacy Spec Kit artifacts.

Usage: migrate_md_to_yaml.py <spec|plan|tasks|constitution|adr|open-questions|error-codes|tracker-sync-map|decision-log|checklist|clarify-qa|verification-report> <input.md> <output.yaml>
       migrate_md_to_yaml.py clarify-qa <questions.md> <answers.md> <output.yaml>

This is an explicit, user-invoked conversion tool. It is never run automatically
by any workflow stage. Output is best-effort: fields that cannot be reliably
recovered from the legacy Markdown are filled with TODO placeholders and are
expected to fail the schema gate (validate.py) until a human fills them in.

"clarify-qa" is the one type that spans two legacy input files (a questions
doc and a separate answers doc keyed by the same ids) — it takes an extra
positional argument instead of a single input.md.
"""
import re
import sys
from pathlib import Path

import yaml

TODO = "TODO: migrate from legacy Markdown — not present in legacy format"


def _strip(text):
    return text.strip() if text else text


def migrate_spec(text):
    feature_match = re.search(r"^#\s*Feature Specification:\s*(.+)$", text, re.MULTILINE)
    branch_match = re.search(r"\*\*Feature Branch\*\*:\s*`([^`]+)`", text)
    created_match = re.search(r"\*\*Created\*\*:\s*(.+)$", text, re.MULTILINE)
    status_match = re.search(r"\*\*Status\*\*:\s*(.+)$", text, re.MULTILINE)
    input_match = re.search(r"\*\*Input\*\*:\s*(.+)$", text, re.MULTILINE)

    user_stories = []
    for story_match in re.finditer(
        r"^###\s*User Story\s*(\d+)\s*-\s*(.+?)\s*\(Priority:\s*(P\d+)\)\s*$"
        r"(.*?)(?=^###\s*User Story|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    ):
        num, title, priority, body = story_match.groups()
        why_match = re.search(r"\*\*Why this priority\*\*:\s*(.+)$", body, re.MULTILINE)
        indep_match = re.search(r"\*\*Independent Test\*\*:\s*(.+)$", body, re.MULTILINE)
        description_match = re.search(r"^\s*\n\s*(.+?)\s*\n", body)

        acceptance_scenarios = []
        for i, scenario_match in enumerate(
            re.finditer(
                r"\*\*Given\*\*\s*(.+?),\s*\*\*When\*\*\s*(.+?),\s*\*\*Then\*\*\s*(.+?)$",
                body,
                re.MULTILINE,
            ),
            start=1,
        ):
            given, when, then = scenario_match.groups()
            acceptance_scenarios.append({
                "id": "AS-{0}".format(i),
                "given": _strip(given),
                "when": _strip(when),
                "then": _strip(then),
            })

        user_stories.append({
            "id": "US{0}".format(num),
            "title": _strip(title),
            "priority": priority,
            "description": _strip(description_match.group(1)) if description_match else TODO,
            "motivation": {
                "problem": TODO,
                "value": TODO,
                "consequence_if_skipped": TODO,
            },
            "why_priority": _strip(why_match.group(1)) if why_match else TODO,
            "independent_test": _strip(indep_match.group(1)) if indep_match else TODO,
            "acceptance_scenarios": acceptance_scenarios or [{
                "id": "AS-1", "given": TODO, "when": TODO, "then": TODO,
            }],
            "acceptance_criteria": [],
            "test_scenarios": [],
        })

    edge_cases = []
    edge_section = re.search(r"###\s*Edge Cases\s*\n(.*?)(?=^##|\Z)", text, re.MULTILINE | re.DOTALL)
    if edge_section:
        for i, line in enumerate(re.findall(r"^-\s*(.+)$", edge_section.group(1), re.MULTILINE), start=1):
            edge_cases.append({
                "id": "EC-{0}".format(i),
                "description": _strip(line),
                "expected_behavior": TODO,
            })

    functional_requirements = []
    fr_section = re.search(r"###\s*Functional Requirements\s*\n(.*?)(?=^###|\Z)", text, re.MULTILINE | re.DOTALL)
    if fr_section:
        for fr_id, fr_text in re.findall(r"\*\*(FR-\d+)\*\*:\s*(.+)$", fr_section.group(1), re.MULTILINE):
            fr_text = _strip(fr_text)

            # Legacy specs mix NFRs into the same FR-NNN sequence with no
            # dedicated heading/prefix; flag likely NFRs by keyword heuristic
            # only — anything not matched defaults to "functional" (best effort).
            category = "non_functional" if re.search(
                r"\b(P\d{2}\b|latency|throughput|SLA\b|per second|milliseconds|\bms\b|"
                r"availability|uptime|scalab\w*|performance)\b",
                fr_text, re.IGNORECASE,
            ) else "functional"

            # Stray inline status markers (emoji / bracketed words), not a clean
            # prefix — detect and strip the marker itself, leave rest of text.
            if re.search(r"⏳|\bPRELIMINARY\b|\[NEEDS CLARIFICATION", fr_text):
                status = "preliminary"
            elif re.search(r"\bREMOVED\b|\bDEPRECATED\b|~~[^~]+~~", fr_text):
                status = "deprecated"
            else:
                status = "final"
            fr_text = _strip(re.sub(r"⏳\s*", "", fr_text))

            # Opaque external ticket refs (e.g. RES-12022, FAST-2025, E1-Q5).
            # Excludes the requirement's own FR-NNN id.
            refs = sorted(set(
                ref for ref in re.findall(r"\b[A-Z]{1,6}-[A-Za-z0-9]+\b", fr_text)
                if not ref.startswith("FR-")
            ))

            functional_requirements.append({
                "id": fr_id,
                "text": fr_text,
                "category": category,
                "status": status,
                "refs": refs,
                "story_refs": [],
            })

    key_entities = []
    entity_section = re.search(r"###\s*Key Entities.*?\n(.*?)(?=^##|\Z)", text, re.MULTILINE | re.DOTALL)
    if entity_section:
        for i, (name, description) in enumerate(
            re.findall(r"\*\*(.+?)\*\*:\s*(.+)$", entity_section.group(1), re.MULTILINE), start=1
        ):
            key_entities.append({
                "id": "E-{0}".format(i),
                "name": _strip(name),
                "description": _strip(description),
            })

    success_criteria = []
    sc_section = re.search(r"###\s*Measurable Outcomes\s*\n(.*?)(?=^##|\Z)", text, re.MULTILINE | re.DOTALL)
    if sc_section:
        for sc_id, sc_text in re.findall(r"\*\*(SC-\d+)\*\*:\s*(.+)$", sc_section.group(1), re.MULTILINE):
            success_criteria.append({
                "id": sc_id,
                "description": _strip(sc_text),
                "measurable_via": TODO,
            })

    assumptions = []
    assumptions_section = re.search(r"^##\s*Assumptions\s*\n(.*?)(?=^##|\Z)", text, re.MULTILINE | re.DOTALL)
    if assumptions_section:
        for i, line in enumerate(re.findall(r"^-\s*(.+)$", assumptions_section.group(1), re.MULTILINE), start=1):
            assumptions.append({"id": "A-{0}".format(i), "description": _strip(line)})

    return {
        "feature": _strip(feature_match.group(1)) if feature_match else TODO,
        "branch": _strip(branch_match.group(1)) if branch_match else TODO,
        "created": _strip(created_match.group(1)) if created_match else TODO,
        "status": _strip(status_match.group(1)) if status_match else "Draft",
        "input": _strip(input_match.group(1)) if input_match else TODO,
        "user_stories": user_stories or [],
        "edge_cases": edge_cases,
        "functional_requirements": functional_requirements or [],
        "key_entities": key_entities,
        "success_criteria": success_criteria or [],
        "assumptions": assumptions,
    }


def migrate_plan(text):
    feature_match = re.search(r"^#\s*Implementation Plan:\s*(.+)$", text, re.MULTILINE)
    branch_match = re.search(r"\*\*Branch\*\*:\s*`([^`]+)`", text)
    summary_section = re.search(r"^##\s*Summary\s*\n(.*?)(?=^##|\Z)", text, re.MULTILINE | re.DOTALL)

    def field(label):
        m = re.search(r"\*\*{0}\*\*:\s*(.+)$".format(re.escape(label)), text, re.MULTILINE)
        return _strip(m.group(1)) if m else TODO

    return {
        "feature": _strip(feature_match.group(1)) if feature_match else TODO,
        "branch": _strip(branch_match.group(1)) if branch_match else TODO,
        "summary": _strip(summary_section.group(1)) if summary_section else TODO,
        "technical_context": {
            "language_version": field("Language/Version"),
            "primary_dependencies": [],
            "storage": field("Storage"),
            "testing": field("Testing"),
            "target_platform": field("Target Platform"),
            "project_type": field("Project Type"),
            "performance_goals": field("Performance Goals"),
            "constraints": field("Constraints"),
            "scale_scope": field("Scale/Scope"),
        },
        "constitution_check": [],
        "project_structure": {
            "layout": "single_project",
            "description": TODO,
            "directories": ["src/", "tests/"],
        },
    }


TASK_LINE_RE = re.compile(
    r"^-\s*\[[ Xx]\]\s*(T\d+)\s*((?:\[P\]\s*)?)((?:\[US\d+\]\s*)?)(.+)$"
)


def migrate_tasks(text):
    feature_match = re.search(r"^#\s*Tasks:\s*(.+)$", text, re.MULTILINE)

    tasks = []
    for line in text.splitlines():
        m = TASK_LINE_RE.match(line.strip())
        if not m:
            continue
        task_id, parallel_tag, story_tag, description = m.groups()
        story_ref_match = re.search(r"\[US(\d+)\]", story_tag)
        tasks.append({
            "id": task_id,
            "title": _strip(description)[:80],
            "description": _strip(description),
            "context": TODO,
            "story_ref": "US{0}".format(story_ref_match.group(1)) if story_ref_match else None,
            "requirement_refs": [],
            "depends_on": [],
            "parallelizable": bool(parallel_tag.strip()),
            "entity_refs": [],
            "contract_refs": [],
            "steps": [{"order": 1, "action": "TODO", "detail": TODO}],
            "technical_notes": [],
            "acceptance_criteria": [],
            "test_scenarios": [],
        })

    return {
        "feature": _strip(feature_match.group(1)) if feature_match else TODO,
        "tasks": tasks,
    }


def migrate_constitution(text):
    project_match = re.search(r"^#\s*(.+?)\s*Constitution\s*$", text, re.MULTILINE)
    version_line = re.search(
        r"\*\*Version\*\*:\s*(.+?)\s*\|\s*\*\*Ratified\*\*:\s*(.+?)\s*\|\s*\*\*Last Amended\*\*:\s*(.+)$",
        text,
        re.MULTILINE,
    )

    principles = []
    for i, principle_match in enumerate(
        re.finditer(r"^###\s*(.+?)\s*\n(.*?)(?=^###|\Z)", text, re.MULTILINE | re.DOTALL), start=1
    ):
        name, body = principle_match.groups()
        description = "\n".join(
            line for line in body.splitlines() if line.strip() and not line.strip().startswith("<!--")
        ).strip() or TODO
        severity = "NON-NEGOTIABLE" if "NON-NEGOTIABLE" in name or "NON-NEGOTIABLE" in description else "recommended"
        principles.append({
            "id": "P{0}".format(i),
            "name": _strip(name),
            "description": description,
            "severity": severity,
            "gate_condition": TODO,
        })

    return {
        "project_name": _strip(project_match.group(1)) if project_match else TODO,
        "version": _strip(version_line.group(1)) if version_line else "1.0.0",
        "ratified": _strip(version_line.group(2)) if version_line else TODO,
        "last_amended": _strip(version_line.group(3)) if version_line else TODO,
        "principles": principles or [{
            "id": "P1", "name": TODO, "description": TODO,
            "severity": "NON-NEGOTIABLE", "gate_condition": TODO,
        }],
    }


def migrate_adr(text):
    title_match = re.search(r"^#\s*(ADR-\d+):\s*(.+)$", text, re.MULTILINE)
    status_match = re.search(r"\*\*Status:\*\*\s*(\w+)(?:\s*\(([^)]+)\))?", text)
    supersedes_match = re.search(r"\*\*Supersedes:\*\*\s*(ADR-\d+)", text)

    refs = []
    for label in ("Context tickets", "Refs"):
        m = re.search(r"\*\*{0}:\*\*\s*(.+)$".format(re.escape(label)), text, re.MULTILINE)
        if m:
            refs.extend(r.strip() for r in _strip(m.group(1)).split(",") if r.strip())

    context_match = re.search(r"^##\s*Context\s*\n(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)

    decision = []
    decision_section = re.search(r"^##\s*Decision\s*\n(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    if decision_section:
        subsections = list(re.finditer(
            r"^###\s*(\d+)\.\s*(.+?)\s*\n(.*?)(?=^###\s|\Z)",
            decision_section.group(1),
            re.MULTILINE | re.DOTALL,
        ))
        if subsections:
            for m in subsections:
                num, sub_title, body = m.groups()
                decision.append({
                    "id": "D-{0}".format(num),
                    "title": _strip(sub_title),
                    "detail": _strip(body) or TODO,
                })
        else:
            decision.append({"id": "D-1", "detail": _strip(decision_section.group(1)) or TODO})

    consequences = {"positive": [], "negative": [], "out_of_scope": []}
    consequences_section = re.search(r"^##\s*Consequences\s*\n(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    if consequences_section:
        body = consequences_section.group(1)
        for key, label in (("positive", "Positive"), ("negative", "Negative"), ("out_of_scope", "Out of scope")):
            m = re.search(
                r"\*\*{0}:?\*\*\s*(.*?)(?=\n\s*-\s*\*\*|\Z)".format(re.escape(label)),
                body,
                re.DOTALL,
            )
            if m:
                consequences[key] = [_strip(line) for line in m.group(1).splitlines() if _strip(line)]

    amends_documents = []
    paperwork_section = re.search(
        r"^##\s*Paperwork reversed.*?\n(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL
    )
    if paperwork_section:
        for line in re.findall(r"^-\s*(.+)$", paperwork_section.group(1), re.MULTILINE):
            doc, _, rest = line.partition(":")
            amends_documents.append({
                "document": _strip(doc),
                "description": _strip(rest) or TODO,
            })

    return {
        "id": title_match.group(1) if title_match else TODO,
        "title": _strip(title_match.group(2)) if title_match else TODO,
        "status": status_match.group(1) if status_match else "Proposed",
        "decided_date": _strip(status_match.group(2)) if status_match and status_match.group(2) else None,
        "supersedes": [supersedes_match.group(1)] if supersedes_match else [],
        "refs": refs,
        "context": _strip(context_match.group(1)) if context_match else TODO,
        "decision": decision or [{"id": "D-1", "detail": TODO}],
        "consequences": consequences,
        "amends_documents": amends_documents,
    }


OQ_STATUS_MAP = (
    ("✅", "Resolved"),
    ("РЕШЕНО", "Resolved"),
    ("ЗАКРЫТ", "Resolved"),
    ("CLOSED", "Resolved"),
    ("Resolved", "Resolved"),
    ("🚫", "Blocked"),
    ("БЛОКЕР", "Blocked"),
    ("Blocked", "Blocked"),
    ("Deferred", "Deferred"),
    ("📋", "Deferred"),
    ("⚠️", "Open"),
    ("Открыт", "Open"),
    ("Open", "Open"),
)


def _oq_status_from_text(text):
    if not text:
        return "Open"
    for marker, status in OQ_STATUS_MAP:
        if marker in text:
            return status
    return "Open"


OQ_HEADING_RE = re.compile(
    r"^###\s*(OQ-[A-Za-z0-9-]+)\s*(?:—|--|-)?\s*(.*)$", re.MULTILINE
)


def migrate_open_questions(text):
    feature_match = re.search(r"^#\s*(.+)$", text, re.MULTILINE)

    open_questions = []
    headings = list(OQ_HEADING_RE.finditer(text))
    for i, heading_match in enumerate(headings):
        oq_id, title = heading_match.groups()
        body_start = heading_match.end()
        body_end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[body_start:body_end]

        question_match = re.search(r"\*\*Вопрос:?\*\*\s*(.+)$", body, re.MULTILINE)
        impact_match = re.search(r"\*\*Влияние:?\*\*\s*(.+)$", body, re.MULTILINE)
        owner_match = re.search(r"\*\*Владелец вопроса:?\*\*\s*(.+)$", body, re.MULTILINE)
        status_match = re.search(r"\*\*Статус:?\*\*\s*(.+)$", body, re.MULTILINE)
        resolution_match = re.search(r"\*\*Решение(?:\s+принято)?:?\*\*\s*(.+)$", body, re.MULTILINE)

        status_text = status_match.group(1) if status_match else None
        entry = {
            "id": oq_id,
            "question": _strip(question_match.group(1)) if question_match else (_strip(title) or TODO),
            "status": _oq_status_from_text(status_text),
        }
        if impact_match:
            entry["impact"] = _strip(impact_match.group(1))
        if owner_match:
            entry["owner"] = _strip(owner_match.group(1))
        if resolution_match:
            entry["resolution"] = _strip(resolution_match.group(1))
        if status_text:
            entry["notes"] = _strip(status_text)
        open_questions.append(entry)

    return {
        "feature": _strip(feature_match.group(1)) if feature_match else TODO,
        "open_questions": open_questions or [{
            "id": "OQ-1", "question": TODO, "status": "Open",
        }],
    }


ERROR_CODE_HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
ERROR_CODE_METHOD_RE = re.compile(r"^(GET|POST|PATCH|PUT|DELETE)\s+(\S.*)$")
ERROR_CODE_ROW_RE = re.compile(r"^\|\s*(\d{3})\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$", re.MULTILINE)
ERROR_CODE_INLINE_CODE_RE = re.compile(r"`([A-Z][A-Z0-9_]*)`")


def migrate_error_codes(text):
    title_match = re.search(r"^#\s*(.+)$", text, re.MULTILINE)

    endpoints = []
    headings = list(ERROR_CODE_HEADING_RE.finditer(text))
    for i, heading_match in enumerate(headings):
        heading_text = _strip(heading_match.group(1))
        if heading_text.lower() == "notes":
            continue
        body_start = heading_match.end()
        body_end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[body_start:body_end]

        errors = []
        for status, code_cell, desc_cell in ERROR_CODE_ROW_RE.findall(body):
            error = {"http_status": int(status), "description": _strip(desc_cell)}
            code_match = ERROR_CODE_INLINE_CODE_RE.search(code_cell)
            if code_match:
                error["error_code"] = code_match.group(1)
            errors.append(error)
        if not errors:
            # Non-tabular section (e.g. narrative "## Notes") — nothing to migrate here.
            continue

        method_match = ERROR_CODE_METHOD_RE.match(heading_text)
        endpoint = {}
        if method_match:
            endpoint["method"] = method_match.group(1)
            endpoint["path"] = _strip(method_match.group(2))
        else:
            # Cross-cutting section (e.g. "Rate Limiting (cross-cutting, API gateway)")
            # rather than a single METHOD path — keep the heading as the scope label.
            endpoint["path"] = heading_text
            applies_match = re.search(r"Applies to:\s*(.+)$", body, re.MULTILINE)
            if applies_match:
                endpoint["applies_to"] = _strip(applies_match.group(1))
        endpoint["errors"] = errors
        endpoints.append(endpoint)

    return {
        "feature_or_scope": _strip(title_match.group(1)) if title_match else TODO,
        "endpoints": endpoints or [{
            "path": TODO,
            "errors": [{"http_status": 0, "description": TODO}],
        }],
    }


JSM_TICKET_ROW_RE = re.compile(r"^\|\s*([A-Za-z]+-[0-9]+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$")
JSM_MISSING_ROW_RE = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$")
JSM_SEPARATOR_RE = re.compile(r"^\|[\s:|-]+\|$")
JSM_EPIC_HEADER_RE = re.compile(r"^([A-Za-z]+-[0-9]+|\(No epic\))\s*(?:—|--|-)\s*(.+)$")


def _jsm_parse_tickets(section_text):
    tickets = []
    for line in section_text.splitlines():
        stripped = line.strip()
        m = JSM_TICKET_ROW_RE.match(stripped)
        if not m:
            continue
        key, summary, status, spec_coverage = m.groups()
        tickets.append({
            "key": key,
            "summary": _strip(summary),
            "status": _strip(status),
            "spec_coverage": _strip(spec_coverage),
        })
    return tickets


def migrate_tracker_sync_map(text):
    title_match = re.search(r"^#\s*(.+)$", text, re.MULTILINE)

    epics = []
    discovered_tickets = []
    gaps = []
    missing_tickets = []
    legend = []

    # Split into level-2 ("## ") sections; section bodies are bounded by the
    # next "## " heading (or end of doc) so unrelated tables never bleed in.
    raw_sections = re.split(r"(?m)^##\s+", text)
    for chunk in raw_sections[1:]:
        heading_line, _, body = chunk.partition("\n")
        heading_line = _strip(heading_line)

        if heading_line.startswith("Legend"):
            legend = [_strip(line[1:]) for line in body.splitlines() if line.strip().startswith("-")]
        elif heading_line.startswith("Epic:"):
            header_text = _strip(heading_line[len("Epic:"):])
            header_match = JSM_EPIC_HEADER_RE.match(header_text)
            epic = {}
            if header_match:
                epic_key, name = header_match.groups()
                if epic_key != "(No epic)":
                    epic["epic_key"] = epic_key
                epic["name"] = _strip(name)
            else:
                epic["name"] = header_text
            spec_ref_match = re.search(r"\[.+?\]\(([^)]+)\)", body)
            if spec_ref_match:
                epic["spec_ref"] = _strip(spec_ref_match.group(1))
            tickets = _jsm_parse_tickets(body)
            epic["tickets"] = tickets or [{
                "key": TODO, "summary": TODO, "status": TODO, "spec_coverage": TODO,
            }]
            epics.append(epic)
        elif heading_line.startswith("Newly Discovered Tickets"):
            discovered_tickets = _jsm_parse_tickets(body)
        elif "Gaps" in heading_line or heading_line.startswith("Tasks WITHOUT Spec Coverage"):
            gaps = _jsm_parse_tickets(body)
        elif heading_line.startswith("Missing") and "Ticket" in heading_line:
            for line in body.splitlines():
                stripped = line.strip()
                if not stripped.startswith("|") or JSM_SEPARATOR_RE.match(stripped):
                    continue
                m = JSM_MISSING_ROW_RE.match(stripped)
                if not m:
                    continue
                spec, requirement, proposed_ticket = m.groups()
                if spec.lower() == "spec":
                    continue
                missing_tickets.append({
                    "spec": _strip(spec),
                    "requirement": _strip(requirement),
                    "proposed_ticket": _strip(proposed_ticket),
                })

    document = {
        "feature_or_scope": _strip(title_match.group(1)) if title_match else TODO,
        "epics": epics or [{
            "name": TODO,
            "tickets": [{"key": TODO, "summary": TODO, "status": TODO, "spec_coverage": TODO}],
        }],
    }
    if legend:
        document["legend"] = legend
    if discovered_tickets:
        document["discovered_tickets"] = discovered_tickets
    if gaps:
        document["gaps"] = gaps
    if missing_tickets:
        document["missing_tickets"] = missing_tickets
    return document


MD_TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
MD_TABLE_SEPARATOR_RE = re.compile(r"^\|?[\s:|-]+\|?$")


def _parse_md_table_rows(section_text):
    """Return data rows (list of stripped cell strings) from the first Markdown
    table found in section_text, skipping the header row and the --- separator."""
    rows = []
    seen_separator = False
    for line in section_text.splitlines():
        stripped = line.strip()
        m = MD_TABLE_ROW_RE.match(stripped)
        if not m:
            if seen_separator and rows:
                break  # table ended
            continue
        if MD_TABLE_SEPARATOR_RE.match(stripped):
            seen_separator = True
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if not seen_separator:
            continue  # still the header row
        rows.append(cells)
    return rows


DECISION_LOG_SECTION_RE = re.compile(r"^##\s+(.+?)\s*\n(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL)


def migrate_decision_log(text):
    scope_match = re.search(r"^#\s*(.+)$", text, re.MULTILINE)

    canonical_homes = []
    entries = []
    pending = []
    deprecated_numbering = []
    notes = []

    for heading_match in DECISION_LOG_SECTION_RE.finditer(text):
        heading = _strip(heading_match.group(1))
        body = heading_match.group(2)
        heading_lower = heading.lower()

        if "canonical homes" in heading_lower:
            for cells in _parse_md_table_rows(body):
                if len(cells) < 2:
                    continue
                home = {"range": cells[0], "canonical_source": cells[1]}
                if len(cells) > 2 and cells[2]:
                    home["materialized_as"] = cells[2]
                canonical_homes.append(home)
        elif "current scheme" in heading_lower:
            for cells in _parse_md_table_rows(body):
                if len(cells) < 3:
                    continue
                entries.append({
                    "id": cells[0],
                    "decision": cells[1],
                    "status": cells[2],
                })
            gap_match = re.search(r"^>\s*(.+(?:\n>\s*.+)*)", body, re.MULTILINE)
            if gap_match:
                notes.append(_strip(re.sub(r"^>\s*", "", gap_match.group(1), flags=re.MULTILINE)))
        elif heading_lower.startswith("pending"):
            for cells in _parse_md_table_rows(body):
                if len(cells) < 2:
                    continue
                item = {"id": cells[0], "decision": cells[1]}
                if len(cells) > 2 and cells[2]:
                    item["location"] = cells[2]
                if len(cells) > 3 and cells[3]:
                    item["trigger"] = cells[3]
                pending.append(item)
        elif "deprecated" in heading_lower and "numbering" in heading_lower:
            for cells in _parse_md_table_rows(body):
                if len(cells) < 2:
                    continue
                deprecated_numbering.append({"old": cells[0], "current": cells[1]})
        elif "provenance" in heading_lower or "stale" in heading_lower:
            for line in re.findall(r"^-\s*(.+)$", body, re.MULTILINE):
                notes.append(_strip(line))

    document = {
        "scope": _strip(scope_match.group(1)) if scope_match else TODO,
        "entries": entries or [{"id": TODO, "decision": TODO, "status": TODO}],
    }
    if canonical_homes:
        document["canonical_homes"] = canonical_homes
    if pending:
        document["pending"] = pending
    if deprecated_numbering:
        document["deprecated_numbering"] = deprecated_numbering
    if notes:
        document["notes"] = notes
    return document


CHECKLIST_ITEM_RE = re.compile(r"^-\s*\[( |x|X)\]\s*(?:(CHK-?\d+)\s+)?(.+)$")
CHECKLIST_SECTION_RE = re.compile(r"^##\s+(.+?)\s*\n(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL)


def migrate_checklist(text):
    title_match = re.search(r"^#\s*(.+)$", text, re.MULTILINE)

    def field(label):
        m = re.search(r"\*\*{0}\*\*:\s*(.+)$".format(re.escape(label)), text, re.MULTILINE)
        return _strip(m.group(1)) if m else None

    purpose = field("Purpose")
    created = field("Created")
    feature = field("Feature")

    scope_match = re.search(r">\s*\*\*Scope:?\*\*\s*(.+(?:\n>.*)*)", text)
    scope = None
    if scope_match:
        scope = _strip(re.sub(r"^>\s*", "", scope_match.group(1), flags=re.MULTILINE))

    canonical_sources = []
    canon_section = re.search(
        r"^##\s*Canonical sources.*?\n(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL
    )
    if canon_section:
        for line in re.findall(r"^\d+\.\s*(.+)$", canon_section.group(1), re.MULTILINE):
            canonical_sources.append(_strip(line))

    categories = []
    notes = []
    for heading_match in CHECKLIST_SECTION_RE.finditer(text):
        heading = _strip(heading_match.group(1))
        body = heading_match.group(2)
        heading_lower = heading.lower()

        if "canonical sources" in heading_lower or heading_lower.startswith("escalation"):
            continue

        if heading_lower == "notes":
            for line in re.findall(r"^(?:-|\d+\.)\s*(.+)$", body, re.MULTILINE):
                notes.append(_strip(line))
            continue

        items = []
        for line in body.splitlines():
            m = CHECKLIST_ITEM_RE.match(line.strip())
            if not m:
                continue
            checked_mark, item_id, description = m.groups()
            item = {
                "description": _strip(description),
                "checked": checked_mark.lower() == "x",
            }
            if item_id:
                item["id"] = item_id
            items.append(item)

        if items:
            categories.append({"name": heading, "items": items})

    document = {
        "title": _strip(title_match.group(1)) if title_match else TODO,
        "categories": categories or [{
            "name": TODO,
            "items": [{"description": TODO, "checked": False}],
        }],
    }
    if purpose:
        document["purpose"] = purpose
    if scope:
        document["scope"] = scope
    if created:
        document["created"] = created
    if feature:
        document["feature"] = feature
    if canonical_sources:
        document["canonical_sources"] = canonical_sources
    if notes:
        document["notes"] = notes
    return document


CLARIFY_Q_HEADING_RE = re.compile(r"^###\s*([A-Za-z0-9]+-Q[0-9]+):\s*(.+)$", re.MULTILINE)
CLARIFY_OPTION_ROW_RE = re.compile(r"^\|\s*([A-Za-z0-9]+)\s*(\(Recommended\))?\s*\|\s*(.+?)\s*\|\s*$", re.MULTILINE)
CLARIFY_ANSWER_LINE_RE = re.compile(
    r"^-\s*([A-Za-z0-9]+-Q[0-9]+):\s*\*\*(.+?)\*\*\s*(?:—|--)\s*(.*)$", re.MULTILINE
)


def migrate_clarify_qa(questions_text, answers_text):
    """Merge a standalone clarification-questions doc with its separate
    answers doc (both keyed by the same '{PHASE}-Q{N}' ids) into one
    clarify-qa document."""
    feature_match = re.search(r"^#\s*(.+)$", questions_text, re.MULTILINE)

    answers = {}
    for qid, chosen, decision in CLARIFY_ANSWER_LINE_RE.findall(answers_text):
        answers[qid] = {
            "chosen_option": _strip(chosen),
            "decision": _strip(decision) or TODO,
        }

    clarifications = []
    headings = list(CLARIFY_Q_HEADING_RE.finditer(questions_text))
    for i, heading_match in enumerate(headings):
        qid, question = heading_match.groups()
        body_start = heading_match.end()
        body_end = headings[i + 1].start() if i + 1 < len(headings) else len(questions_text)
        body = questions_text[body_start:body_end]

        gap_match = re.search(r"^\*\*Gap\*\*:\s*(.+)$", body, re.MULTILINE)
        recommended_match = re.search(r"^\*\*Recommended\*\*:\s*(.+)$", body, re.MULTILINE)

        options = []
        for label, recommended_tag, description in CLARIFY_OPTION_ROW_RE.findall(body):
            if label.strip().lower() == "option":
                continue  # table header row, not an option
            option = {"label": _strip(label), "description": _strip(description)}
            if recommended_tag:
                option["recommended"] = True
            options.append(option)

        entry = {
            "id": qid,
            "question": _strip(question),
            "options": options or [{"label": TODO, "description": TODO}],
        }
        if gap_match:
            entry["gap"] = _strip(gap_match.group(1))
        if recommended_match:
            entry["recommendation"] = _strip(recommended_match.group(1))

        answer = answers.get(qid)
        if answer:
            entry["answer"] = answer
            entry["status"] = "Answered"
        else:
            entry["status"] = "Open"

        clarifications.append(entry)

    return {
        "feature": _strip(feature_match.group(1)) if feature_match else TODO,
        "clarifications": clarifications or [{
            "id": "PH-Q1", "question": TODO,
            "options": [{"label": TODO, "description": TODO}],
            "status": "Open",
        }],
    }


VERIFICATION_TITLE_RE = re.compile(r"^#\s*(.+)$", re.MULTILINE)
VERIFICATION_DATE_RE = re.compile(r"\*\*Date:?\*\*\s*:?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})")
VERIFICATION_TITLE_DATE_RE = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})")
VERIFICATION_AUTHOR_RE = re.compile(r"\*\*(?:Verifier|Validator):?\*\*\s*:?\s*(.+)$", re.MULTILINE)
VERIFICATION_CANONICAL_SOURCES_RE = re.compile(r"Canonical sources:\s*(.+)$", re.MULTILINE)
VERIFICATION_SECTION_RE = re.compile(r"^##\s+(.+?)\s*\n(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL)
VERIFICATION_SUBSECTION_RE = re.compile(r"^###\s*(.+?)\s*\n(.*?)(?=^###\s|\Z)", re.MULTILINE | re.DOTALL)
VERIFICATION_VERDICT_RE = re.compile(r"\*\*Verdict:?\*\*\s*(.+)$", re.MULTILINE)
VERIFICATION_SEVERITY_INLINE_RE = re.compile(r"\*\*Severity:\s*([A-Za-z]+)\.?\*\*")
VERIFICATION_FINDING_HEADING_RE = re.compile(
    r"^##\s*[^\n]*?Finding\s*(\d+)\s*\(([A-Za-z]+)\)\s*(?:—|--|-)\s*(.+)$", re.MULTILINE
)
VERIFICATION_NUMBERED_ITEM_RE = re.compile(r"^\d+\.\s*(.+)$", re.MULTILINE)

VERIFICATION_SEVERITY_MAP = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}
VERIFICATION_RESULT_MAP = (
    ("partial pass", "Partial"),
    ("pass", "Pass"),
    ("fail", "Fail"),
    ("clean", "Pass"),
    ("warning", "Warning"),
    ("skip", "Skipped"),
)


def _verification_severity(text):
    if not text:
        return None
    m = re.search(r"\b(critical|high|medium|low)\b", text, re.IGNORECASE)
    return VERIFICATION_SEVERITY_MAP[m.group(1).lower()] if m else None


def _verification_result(text):
    if not text:
        return None
    lowered = text.lower()
    for marker, result in VERIFICATION_RESULT_MAP:
        if marker in lowered:
            return result
    return None


def _verification_action(line, default_priority=None):
    clean = _strip(line).replace("**", "")
    priority_match = re.match(r"^\[([A-Za-z]+)\]\s*(.+)$", clean)
    if priority_match:
        priority, rest = priority_match.groups()
    else:
        priority, rest = default_priority, clean
    action = {"description": _strip(rest)}
    if priority:
        action["priority"] = _strip(priority)
    return action


def migrate_verification_report(text):
    title_match = VERIFICATION_TITLE_RE.search(text)
    title = _strip(title_match.group(1)) if title_match else TODO

    date_match = VERIFICATION_DATE_RE.search(text)
    if date_match:
        report_date = date_match.group(1)
    else:
        # Some reports (e.g. dated consistency sweeps) carry the date only in
        # the title itself, not a dedicated "**Date**:" field.
        title_date_match = VERIFICATION_TITLE_DATE_RE.search(title) if title_match else None
        report_date = title_date_match.group(1) if title_date_match else TODO

    author_match = VERIFICATION_AUTHOR_RE.search(text)

    canonical_sources = []
    canon_match = VERIFICATION_CANONICAL_SOURCES_RE.search(text)
    if canon_match:
        canonical_sources = [s.strip() for s in re.split(r",\s*", _strip(canon_match.group(1))) if s.strip()]

    summary_section = re.search(
        r"^##\s*Executive Summary\s*\n(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL
    )
    summary = None
    if summary_section:
        summary = _strip(summary_section.group(1))
    else:
        # Leading narrative paragraph(s) before the first "##" heading, skipping
        # title/date/verifier metadata lines.
        intro_match = re.search(r"^#[^\n]*\n(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
        if intro_match:
            intro_lines = [
                line.strip() for line in intro_match.group(1).splitlines()
                if line.strip() and not re.match(r"^\*\*(Date|Verifier|Validator)", line.strip())
            ]
            if intro_lines:
                summary = _strip("\n".join(intro_lines))

    checks = []
    seen_check_names = set()

    # A summary table with a "Result" column (e.g. "| Invariant group | Result |").
    for heading_match in VERIFICATION_SECTION_RE.finditer(text):
        heading = _strip(heading_match.group(1))
        body = heading_match.group(2)
        header_row_match = re.search(r"^\|.*\bResult\b.*\|\s*$", body, re.MULTILINE)
        if header_row_match:
            for cells in _parse_md_table_rows(body):
                if len(cells) < 2:
                    continue
                name, result_cell = cells[0], cells[1]
                result = _verification_result(result_cell)
                if result and name not in seen_check_names:
                    checks.append({"name": name, "result": result, "details": result_cell})
                    seen_check_names.add(name)

        # Per-section explicit "**Verdict: ...**" lines.
        verdict_match = VERIFICATION_VERDICT_RE.search(body)
        if verdict_match:
            check_name = re.sub(r"^\d+\.\s*", "", heading)
            if check_name not in seen_check_names:
                result = _verification_result(verdict_match.group(1)) or "Warning"
                checks.append({
                    "name": check_name,
                    "result": result,
                    "details": _strip(verdict_match.group(1)),
                })
                seen_check_names.add(check_name)

    findings = []

    # "## <marker> Finding N (SEVERITY) — description" headings (consistency-sweep style).
    for num, severity, desc in VERIFICATION_FINDING_HEADING_RE.findall(text):
        findings.append({
            "id": "Finding {0}".format(num),
            "severity": _verification_severity(severity) or "Medium",
            "description": _strip(desc),
        })

    # Numbered "Remaining Open Items"-style lists with an inline "**Severity: X.**" tag.
    open_items_section = re.search(
        r"^##\s*Remaining Open Items\s*\n(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL
    )
    if open_items_section:
        for line in VERIFICATION_NUMBERED_ITEM_RE.findall(open_items_section.group(1)):
            severity_match = VERIFICATION_SEVERITY_INLINE_RE.search(line)
            description = _strip(re.sub(r"\*\*Severity:\s*[A-Za-z]+\.?\*\*", "", line)).replace("**", "")
            findings.append({
                "description": description,
                "severity": _verification_severity(severity_match.group(1)) if severity_match else "Medium",
            })

    # Tables with a "Gap" column, grouped under "### Priority N — ..." subsections.
    for heading_match in VERIFICATION_SECTION_RE.finditer(text):
        for sub_heading, sub_body in VERIFICATION_SUBSECTION_RE.findall(heading_match.group(2)):
            if not re.search(r"^\|.*\bGap\b.*\|\s*$", sub_body, re.MULTILINE):
                continue
            severity = _verification_severity(sub_heading)
            for cells in _parse_md_table_rows(sub_body):
                if len(cells) < 2 or not cells[1]:
                    continue
                finding = {"description": cells[1], "severity": severity or "Medium"}
                if cells[0]:
                    finding["id"] = cells[0]
                refs = [c for c in cells[2:] if c]
                if refs:
                    finding["refs"] = refs
                findings.append(finding)

    readiness = []
    for heading_match in VERIFICATION_SECTION_RE.finditer(text):
        heading = _strip(heading_match.group(1))
        if "readiness" not in heading.lower():
            continue
        for cells in _parse_md_table_rows(heading_match.group(2)):
            if len(cells) < 2 or not cells[1]:
                continue
            item = {"scope": cells[0], "verdict": cells[1].replace("**", "")}
            if len(cells) > 2 and cells[2]:
                item["rationale"] = cells[2]
            readiness.append(item)

    recommended_actions = []
    for heading_match in VERIFICATION_SECTION_RE.finditer(text):
        heading = _strip(heading_match.group(1))
        if "recommend" not in heading.lower() and "next steps" not in heading.lower():
            continue
        body = heading_match.group(2)
        sub_sections = VERIFICATION_SUBSECTION_RE.findall(body)
        if sub_sections:
            for sub_heading, sub_body in sub_sections:
                for line in VERIFICATION_NUMBERED_ITEM_RE.findall(sub_body):
                    recommended_actions.append(_verification_action(line, sub_heading))
        else:
            for line in VERIFICATION_NUMBERED_ITEM_RE.findall(body):
                recommended_actions.append(_verification_action(line))

    document = {
        "title": title,
        "report_date": report_date,
        "checks": checks,
        "findings": findings,
    }
    if author_match:
        document["author"] = _strip(author_match.group(1))
    if summary:
        document["summary"] = summary
    if canonical_sources:
        document["canonical_sources"] = canonical_sources
    if readiness:
        document["readiness"] = readiness
    if recommended_actions:
        document["recommended_actions"] = recommended_actions

    return document


MIGRATORS = {
    "spec": migrate_spec,
    "plan": migrate_plan,
    "tasks": migrate_tasks,
    "constitution": migrate_constitution,
    "adr": migrate_adr,
    "open-questions": migrate_open_questions,
    "error-codes": migrate_error_codes,
    "tracker-sync-map": migrate_tracker_sync_map,
    "decision-log": migrate_decision_log,
    "checklist": migrate_checklist,
    "clarify-qa": migrate_clarify_qa,
    "verification-report": migrate_verification_report,
}

# Artifact types whose migrator takes two merged/paired input texts instead of
# one (signature: fn(text_a, text_b)) — main() gives these an extra CLI arg.
TWO_INPUT_MIGRATORS = {"clarify-qa"}


def main():
    artifact_type = sys.argv[1] if len(sys.argv) > 1 else None
    expected_argc = 5 if artifact_type in TWO_INPUT_MIGRATORS else 4

    if len(sys.argv) != expected_argc or artifact_type not in MIGRATORS:
        print(
            "usage: migrate_md_to_yaml.py <spec|plan|tasks|constitution|adr|open-questions|error-codes|tracker-sync-map|decision-log|checklist|clarify-qa|verification-report> <input.md> <output.yaml>\n"
            "       migrate_md_to_yaml.py clarify-qa <questions.md> <answers.md> <output.yaml>",
            file=sys.stderr,
        )
        sys.exit(1)

    if artifact_type in TWO_INPUT_MIGRATORS:
        input_a_path, input_b_path, output_path = sys.argv[2], sys.argv[3], sys.argv[4]
        text_a = Path(input_a_path).read_text(encoding="utf-8")
        text_b = Path(input_b_path).read_text(encoding="utf-8")
        document = MIGRATORS[artifact_type](text_a, text_b)
        input_path = "{0} + {1}".format(input_a_path, input_b_path)
    else:
        input_path, output_path = sys.argv[2], sys.argv[3]
        text = Path(input_path).read_text(encoding="utf-8")
        document = MIGRATORS[artifact_type](text)

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(document, f, sort_keys=False, allow_unicode=True)

    print("Wrote best-effort {0} -> {1}. Run validate.py against it; TODO placeholders and empty required lists will need manual completion.".format(input_path, output_path))


if __name__ == "__main__":
    main()
