#!/usr/bin/env python3
"""Extract normalized metrics from quality tool reports.

Usage:
    python scripts/parse_reports.py <parser> <report-file>

Parsers: stryker, mutmut, pit, cobertura, lcov, jacoco, lizard, jscpd
Output (stdout): JSON {"category": ..., "metric": ..., "metric_value": <number>}
Exit non-zero with a JSON error on stderr for unreadable/malformed reports.
"""
import csv
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


class ParseError(Exception):
    pass


def parse_stryker(text: str) -> dict:
    """Stryker.NET / StrykerJS mutation-report.json."""
    data = json.loads(text)
    if "mutationScore" in data:
        score = data["mutationScore"]
    else:
        # mutation-testing-report-schema: compute from files[].mutants[].status
        killed = survived = timeout = no_cov = 0
        files = data.get("files")
        if files is None:
            raise ParseError("not a Stryker report: no mutationScore and no files")
        for f in files.values():
            for m in f.get("mutants", []):
                s = m.get("status")
                if s in ("Killed",):
                    killed += 1
                elif s in ("Survived",):
                    survived += 1
                elif s in ("Timeout",):
                    timeout += 1
                elif s in ("NoCoverage",):
                    no_cov += 1
        detected = killed + timeout
        total = detected + survived + no_cov
        if total == 0:
            raise ParseError("Stryker report contains no mutants")
        score = 100.0 * detected / total
    return {"category": "mutation", "metric": "mutation_score", "metric_value": round(float(score), 2)}


def parse_mutmut(text: str) -> dict:
    """mutmut results output: counts killed/survived from 'mutmut results' or run summary."""
    killed = len(re.findall(r"\bkilled\b", text, re.I))
    m = re.search(r"(\d+)/(\d+)\s+.*killed", text, re.I)
    if m:
        killed, total = int(m.group(1)), int(m.group(2))
    else:
        # summary emoji format: "Killed 12", "Survived 3" (mutmut 2.x/3.x variants)
        k = re.search(r"killed[^\d]*(\d+)", text, re.I)
        s = re.search(r"survived[^\d]*(\d+)", text, re.I)
        t = re.search(r"timeout[^\d]*(\d+)", text, re.I)
        sus = re.search(r"suspicious[^\d]*(\d+)", text, re.I)
        if not (k or s):
            raise ParseError("unrecognized mutmut output")
        killed = int(k.group(1)) if k else 0
        survived = int(s.group(1)) if s else 0
        total = killed + survived + (int(t.group(1)) if t else 0) + (int(sus.group(1)) if sus else 0)
    if total == 0:
        raise ParseError("mutmut report contains no mutants")
    return {"category": "mutation", "metric": "mutation_score", "metric_value": round(100.0 * killed / total, 2)}


def parse_pit(text: str) -> dict:
    """PIT mutations.xml."""
    root = ET.fromstring(text)
    mutations = root.findall(".//mutation")
    if not mutations:
        raise ParseError("PIT report contains no mutations")
    detected = sum(1 for m in mutations if m.get("detected") == "true")
    return {"category": "mutation", "metric": "mutation_score", "metric_value": round(100.0 * detected / len(mutations), 2)}


def parse_cobertura(text: str) -> dict:
    """Cobertura XML (coverlet, coverage.py xml)."""
    root = ET.fromstring(text)
    rate = root.get("line-rate")
    if rate is None:
        raise ParseError("not a cobertura report: missing line-rate")
    return {"category": "coverage", "metric": "line_coverage", "metric_value": round(float(rate) * 100.0, 2)}


def parse_lcov(text: str) -> dict:
    """lcov.info: sum LH/LF records."""
    lh = sum(int(m) for m in re.findall(r"^LH:(\d+)", text, re.M))
    lf = sum(int(m) for m in re.findall(r"^LF:(\d+)", text, re.M))
    if lf == 0:
        raise ParseError("lcov report contains no instrumented lines")
    return {"category": "coverage", "metric": "line_coverage", "metric_value": round(100.0 * lh / lf, 2)}


def parse_jacoco(text: str) -> dict:
    """JaCoCo XML: LINE counter at report level."""
    root = ET.fromstring(text)
    for counter in root.findall("counter"):
        if counter.get("type") == "LINE":
            covered, missed = int(counter.get("covered")), int(counter.get("missed"))
            total = covered + missed
            if total == 0:
                raise ParseError("JaCoCo LINE counter is empty")
            return {"category": "coverage", "metric": "line_coverage", "metric_value": round(100.0 * covered / total, 2)}
    raise ParseError("JaCoCo report has no LINE counter")


def parse_lizard(text: str) -> dict:
    """lizard --csv: NLOC,CCN,token,param,length,location,file,function,... — use max CCN."""
    reader = csv.reader(io.StringIO(text))
    ccns = []
    for row in reader:
        if len(row) < 2:
            continue
        try:
            ccns.append(int(row[1]))
        except ValueError:
            continue  # header line
    if not ccns:
        raise ParseError("lizard CSV contains no functions")
    return {"category": "complexity", "metric": "max_ccn", "metric_value": max(ccns)}


def parse_jscpd(text: str) -> dict:
    """jscpd json report: statistics.total.percentage."""
    data = json.loads(text)
    try:
        pct = data["statistics"]["total"]["percentage"]
    except (KeyError, TypeError):
        raise ParseError("not a jscpd report: missing statistics.total.percentage")
    return {"category": "duplication", "metric": "duplicated_lines_pct", "metric_value": round(float(pct), 2)}


PARSERS = {
    "stryker": parse_stryker,
    "mutmut": parse_mutmut,
    "pit": parse_pit,
    "cobertura": parse_cobertura,
    "lcov": parse_lcov,
    "jacoco": parse_jacoco,
    "lizard": parse_lizard,
    "jscpd": parse_jscpd,
}


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in PARSERS:
        json.dump({"error": f"usage: parse_reports.py <{ '|'.join(PARSERS) }> <report-file>"}, sys.stderr)
        sys.exit(2)
    parser, path = sys.argv[1], Path(sys.argv[2])
    try:
        result = PARSERS[parser](path.read_text(encoding="utf-8", errors="replace"))
    except (ParseError, json.JSONDecodeError, ET.ParseError, OSError) as e:
        json.dump({"error": f"{parser}: {e}", "report": str(path)}, sys.stderr)
        sys.stderr.write("\n")
        sys.exit(1)
    json.dump(result, sys.stdout)
    print()


if __name__ == "__main__":
    main()
