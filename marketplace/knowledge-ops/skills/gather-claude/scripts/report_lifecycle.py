"""Fail-closed report-lifecycle gate for gather-claude.

The report is executable process state, not passive prose. This reader checks
active dated and legacy-numbered findings (everything before ``## Archived``), prints every
condition that must be reconciled before presentation, and exits non-zero when
any blocking condition remains. Historical records under ``## Archived`` are
intentionally preserved.

USAGE
    python3 scripts/report_lifecycle.py <report.md> [--today YYYY-MM-DD] [--json]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter
from typing import Any

FINDING_HEADER = re.compile(
    r"^[ ]{0,3}### \[(?P<identity>\d{4}-\d{2}-\d{2}|#[^\]]+)\]"
    r"\s*(?:\[(?P<severity>[A-Z]+)\])?\s*(?P<title>\S.*)$",
    re.MULTILINE,
)
PASSED_QUALIFICATION = re.compile(
    r"^PASSED\s*(?:—|-|:)\s*\S.+$",
    re.IGNORECASE,
)
NOT_APPLICABLE_QUALIFICATION = re.compile(
    r"^(?:not-applicable|n/?a)\s*(?:—|-|:)\s*\S.+$",
    re.IGNORECASE,
)
UNRESOLVED_QUALIFICATION = re.compile(
    r"\b(?:pending|not\s+run|unverified|todo|tbd|unknown)\b",
    re.IGNORECASE,
)
FAILED_RESULT = re.compile(
    r"\b(?:exit(?:ed|\s+code)?|return(?:ed|\s+code)?|rc)\s*[:=]?\s*[1-9]\d*\b",
    re.IGNORECASE,
)
EXPECTED_NONZERO = re.compile(
    r"\b(?:expected|negative\s+control)\b",
    re.IGNORECASE,
)
FAILURE_WORD = re.compile(
    r"\b(?:fail(?:ed|ure)?|unexpected(?:ly)?|error)\b",
    re.IGNORECASE,
)
SUCCESS_RESULT = re.compile(
    r"\b(?:exit(?:ed|\s+code)?|return(?:ed|\s+code)?|rc)\s*[:=]?\s*0\b"
    r"|\b\d+\s+(?:tests?\s+)?passed\b"
    r"|\b(?:overall|final|integration|suite|command|control)\s+"
    r"(?:passed|succeeded)\b",
    re.IGNORECASE,
)
VERIFIED_EVIDENCE = re.compile(
    r"^(?:\*\*)?yes(?:\*\*)?\s*(?:—|-)\s*\S.+$",
    re.IGNORECASE,
)
INVALID_VERIFIED_EVIDENCE = re.compile(
    r"\b(?:no\s+evidence|pending(?:\s+verification)?|unverified|not\s+checked|"
    r"unknown|could\s+not\s+read|failed\s+to\s+read|unable\s+to\s+read)\b",
    re.IGNORECASE,
)
VAGUE_TRIGGER = re.compile(
    r"^\s*(?:maybe(?:\s+later)?|later|eventually|someday|tbd|todo|unknown|"
    r"when\s+possible)\s*[.!]?\s*$",
    re.IGNORECASE,
)
CANONICAL_VERDICTS = ("ADOPT", "QUALIFY", "DEFER", "REJECT")
CANONICAL_SEVERITIES = ("HIGH", "MEDIUM", "LOW")
VERDICT_TOKEN = re.compile(r"\b(ADOPT|QUALIFY|TRIAL|DEFER|REJECT|RECOMMEND|DOCUMENT)\b")
LEGACY_STAGED = re.compile(r"\bTRIAL\b|(?i:\btry-by\b)")
FIELD = {
    "category": re.compile(r"^- \*\*Category\*\*:\s*(.+)$", re.MULTILINE),
    "source": re.compile(r"^- \*\*Source\*\*:\s*(.+)$", re.MULTILINE),
    "baseline_ref": re.compile(r"^- \*\*Baseline ref\*\*:\s*(.+)$", re.MULTILINE),
    "what_changed": re.compile(r"^- \*\*What changed\*\*:\s*(.+)$", re.MULTILINE),
    "recommended_edit": re.compile(
        r"^- \*\*Recommended edit\*\*:\s*(.+)$", re.MULTILINE
    ),
    "verdict": re.compile(r"^- \*\*Verdict\*\*:\s*(.+)$", re.MULTILINE),
    "trigger": re.compile(r"^- \*\*Trigger\*\*:\s*(.+)$", re.MULTILINE),
    "qualification": re.compile(r"^- \*\*Qualification\*\*:\s*(.+)$", re.MULTILINE),
    "verified": re.compile(r"^- \*\*Verified\*\*:\s*(.+)$", re.MULTILINE),
}
PLACEHOLDER_FIELD = re.compile(
    r"^\s*(?:tbd|todo|pending|unknown|n/?a|none|not\s+checked)\s*[.!]?\s*$",
    re.IGNORECASE,
)

REQUIRED_FIELDS = (
    "category",
    "source",
    "baseline_ref",
    "what_changed",
    "recommended_edit",
)


def _active_text(text: str) -> str:
    """Exclude archived history from the release gate."""

    archived = re.search(r"^## Archived\s*$", text, re.MULTILINE)
    return text if archived is None else text[: archived.start()]


def _active_findings_text(text: str) -> tuple[str, int]:
    """Return the active findings prose and its one-based starting line."""

    active = _active_text(text)
    start = re.search(
        r"^## (?:Active Findings|Architecture Debt)\s*$", active, re.MULTILINE
    )
    if start is None:
        return active, 1
    offset = start.start()
    return active[offset:], active.count("\n", 0, offset) + 1


def _verdict_word(raw: str) -> str | None:
    """Return one unambiguous canonical verdict, otherwise fail parsing closed."""

    tokens = VERDICT_TOKEN.findall(raw)
    if len(tokens) != 1 or tokens[0] not in CANONICAL_VERDICTS:
        return None
    return tokens[0]


def _qualification_passed(raw: str | None) -> bool:
    """Require a PASSED result plus the command/result that produced it."""

    if not raw:
        return False
    normalized = raw.strip()
    if not PASSED_QUALIFICATION.fullmatch(normalized):
        return False
    if UNRESOLVED_QUALIFICATION.search(normalized):
        return False
    clauses = [part.strip() for part in re.split(r"[.;]\s+", normalized)]
    if not any(SUCCESS_RESULT.search(clause) for clause in clauses):
        return False
    risky = [
        clause
        for clause in clauses
        if FAILED_RESULT.search(clause) or FAILURE_WORD.search(clause)
    ]
    if any(not EXPECTED_NONZERO.search(clause) for clause in risky):
        return False
    return not risky or any(
        SUCCESS_RESULT.search(clause) and clause not in risky for clause in clauses
    )


def _qualification_resolved(raw: str | None) -> bool:
    """Accept terminal evidence only; pending placeholders fail closed."""

    if not raw:
        return False
    normalized = raw.strip()
    if UNRESOLVED_QUALIFICATION.search(normalized):
        return False
    if PASSED_QUALIFICATION.fullmatch(normalized):
        return _qualification_passed(normalized)
    return bool(
        NOT_APPLICABLE_QUALIFICATION.fullmatch(normalized)
        and not FAILED_RESULT.search(normalized)
        and not FAILURE_WORD.search(normalized)
    )


def _verified(raw: str | None) -> bool:
    """Require concrete verification evidence, while allowing explicit caveats."""

    if not raw:
        return False
    normalized = raw.strip()
    return bool(
        VERIFIED_EVIDENCE.fullmatch(normalized)
        and not INVALID_VERIFIED_EVIDENCE.search(normalized)
    )


def parse(text: str, *, active_only: bool = True) -> list[dict[str, Any]]:
    """Split report content into canonical dated or numbered finding blocks."""

    corpus = _active_text(text) if active_only else text
    findings: list[dict[str, Any]] = []
    hits = list(FINDING_HEADER.finditer(corpus))
    for index, match in enumerate(hits):
        end = hits[index + 1].start() if index + 1 < len(hits) else len(corpus)
        body = corpus[match.end() : end]
        heading = re.search(r"\n#{2,3} ", body)
        if heading:
            body = body[: heading.start()]
        fields = {
            name: (
                pattern.search(body).group(1).strip() if pattern.search(body) else None
            )
            for name, pattern in FIELD.items()
        }
        identity = match.group("identity")
        findings.append(
            {
                "date": identity
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", identity)
                else None,
                "identity": identity,
                "severity": match.group("severity"),
                "title": match.group("title").strip(),
                "category": fields["category"],
                "source": fields["source"],
                "baseline_ref": fields["baseline_ref"],
                "what_changed": fields["what_changed"],
                "recommended_edit": fields["recommended_edit"],
                "verdict_raw": fields["verdict"],
                "verdict": _verdict_word(fields["verdict"] or ""),
                "trigger": fields["trigger"],
                "qualification": fields["qualification"],
                "verified": fields["verified"],
                "legacy_staged": bool(
                    LEGACY_STAGED.search(match.group("title") + "\n" + body)
                ),
            }
        )
    return findings


def _public(finding: dict[str, Any]) -> dict[str, Any]:
    return dict(finding)


def _has_trigger(finding: dict[str, Any]) -> bool:
    trigger = finding["trigger"]
    if not trigger:
        inline = re.search(
            r"\btrigger\s*[:=]\s*(.+)$",
            finding["verdict_raw"] or "",
            re.IGNORECASE,
        )
        trigger = inline.group(1).strip() if inline else None
    return bool(trigger and len(trigger) >= 8 and not VAGUE_TRIGGER.search(trigger))


def _print_findings(label: str, findings: list[dict[str, Any]]) -> None:
    print(f"\n{label}")
    if not findings:
        print("   none")
        return
    for finding in findings:
        print(f"   REJECTED  {finding['title'][:70]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument(
        "--today", default=dt.datetime.now(tz=dt.UTC).date().isoformat()
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    today = dt.date.fromisoformat(args.today)
    with open(args.report, encoding="utf-8") as handle:
        text = handle.read()
    findings = parse(text)
    history_findings = parse(text, active_only=False)

    active_prose, first_line = _active_findings_text(text)
    malformed_headers = []
    for offset, line in enumerate(_active_text(text).splitlines()):
        if (
            re.match(r"^[ ]{0,3}### \[", line)
            and FINDING_HEADER.fullmatch(line) is None
        ):
            malformed_headers.append(
                {
                    "date": None,
                    "severity": None,
                    "title": f"line {offset + 1}: {line.strip()}",
                }
            )
    legacy_staged = []
    for offset, line in enumerate(active_prose.splitlines()):
        if LEGACY_STAGED.search(line):
            legacy_staged.append(
                {
                    "date": None,
                    "severity": None,
                    "title": f"line {first_line + offset}: {line.strip()}",
                }
            )
    unresolved_qualifications = [
        finding for finding in findings if finding["verdict"] == "QUALIFY"
    ]
    invalid_adoptions = [
        finding
        for finding in findings
        if finding["verdict"] == "ADOPT"
        and not _qualification_passed(finding["qualification"])
    ]
    defers_without_trigger = [
        finding
        for finding in findings
        if finding["verdict"] == "DEFER" and not _has_trigger(finding)
    ]
    missing_verdict = [finding for finding in findings if not finding["verdict_raw"]]
    invalid_verdict = [
        finding
        for finding in findings
        if finding["verdict_raw"] and not finding["verdict"]
    ]
    missing_severity = [finding for finding in findings if not finding["severity"]]
    invalid_severity = [
        finding
        for finding in findings
        if finding["severity"] and finding["severity"] not in CANONICAL_SEVERITIES
    ]
    missing_required_fields = [
        {**finding, "missing_field": field}
        for finding in findings
        for field in REQUIRED_FIELDS
        if not finding[field] or PLACEHOLDER_FIELD.fullmatch(finding[field])
    ]
    missing_qualification = [
        finding for finding in findings if not finding["qualification"]
    ]
    invalid_qualification = [
        finding
        for finding in findings
        if finding["qualification"]
        and finding["verdict"] in {"DEFER", "REJECT"}
        and not _qualification_resolved(finding["qualification"])
    ]
    missing_verified = [finding for finding in findings if not finding["verified"]]
    invalid_verified = [
        finding
        for finding in findings
        if finding["verified"] and not _verified(finding["verified"])
    ]

    blockers = (
        malformed_headers
        + legacy_staged
        + unresolved_qualifications
        + invalid_adoptions
        + defers_without_trigger
        + missing_verdict
        + invalid_verdict
        + missing_severity
        + invalid_severity
        + missing_required_fields
        + missing_qualification
        + invalid_qualification
        + missing_verified
        + invalid_verified
    )

    cutoff = today - dt.timedelta(days=90)
    in_window = [
        finding
        for finding in history_findings
        if finding["date"] and cutoff <= dt.date.fromisoformat(finding["date"]) <= today
    ]
    opportunities = [
        finding
        for finding in in_window
        if finding["category"]
        and re.search(r"NEW_FEATURE|CONFIGURATION", finding["category"])
    ]
    adopted = [
        finding
        for finding in opportunities
        if finding["verdict"] == "ADOPT"
        and _qualification_passed(finding["qualification"])
        and _verified(finding["verified"])
        and finding["severity"] in CANONICAL_SEVERITIES
        and all(finding[field] for field in REQUIRED_FIELDS)
    ]

    payload = {
        "valid": not blockers,
        "malformed_headers": list(map(_public, malformed_headers)),
        "legacy_staged": list(map(_public, legacy_staged)),
        "unresolved_qualifications": list(map(_public, unresolved_qualifications)),
        "invalid_adoptions": list(map(_public, invalid_adoptions)),
        "defers_without_trigger": list(map(_public, defers_without_trigger)),
        "missing_verdict": list(map(_public, missing_verdict)),
        "invalid_verdict": list(map(_public, invalid_verdict)),
        "missing_severity": list(map(_public, missing_severity)),
        "invalid_severity": list(map(_public, invalid_severity)),
        "missing_required_fields": list(map(_public, missing_required_fields)),
        "missing_qualification": list(map(_public, missing_qualification)),
        "invalid_qualification": list(map(_public, invalid_qualification)),
        "missing_verified": list(map(_public, missing_verified)),
        "invalid_verified": list(map(_public, invalid_verified)),
        "adoption": {"opportunities": len(opportunities), "adopted": len(adopted)},
    }
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        print()
        return 1 if blockers else 0

    print(f"REPORT LIFECYCLE WALK  ({args.today})  {len(findings)} active findings")
    print("=" * 78)
    _print_findings("1. MALFORMED FINDING HEADERS", malformed_headers)
    _print_findings("2. LEGACY STAGED STATE", legacy_staged)
    _print_findings("3. UNRESOLVED QUALIFICATION", unresolved_qualifications)
    _print_findings("4. ADOPT WITHOUT QUALIFICATION EVIDENCE", invalid_adoptions)
    _print_findings("5. DEFER WITHOUT TRIGGER", defers_without_trigger)

    print("\n6. FIELD AND VERDICT COMPLETENESS")
    completeness = (
        ("MISSING VERDICT", missing_verdict),
        ("INVALID VERDICT", invalid_verdict),
        ("MISSING SEVERITY", missing_severity),
        ("INVALID SEVERITY", invalid_severity),
        ("MISSING REQUIRED FIELD", missing_required_fields),
        ("MISSING QUALIFICATION", missing_qualification),
        ("INVALID QUALIFICATION", invalid_qualification),
        ("MISSING VERIFIED", missing_verified),
        ("INVALID VERIFIED", invalid_verified),
    )
    for label, group in completeness:
        print(f"   {label + ':':<24} {len(group)}")
        for finding in group[:5]:
            print(f"      {finding['title'][:70]}")
    distribution = dict(
        Counter(finding["verdict"] for finding in findings if finding["verdict"])
    )
    print(f"   verdict distribution: {distribution}")

    print("\n7. ADOPTION METRIC (last 90d)")
    print(
        f"   machine-countable: {len(adopted)} qualified ADOPT of "
        f"{len(opportunities)} opportunity entries"
    )

    print("\n8. WATCHING")
    watching = re.search(r"\n## Watching\n(.*?)(?=\n## )", text, re.DOTALL)
    if watching:
        block = watching.group(1)
        dormant_at = block.find("### Watching (Dormant)")
        active_block = block if dormant_at < 0 else block[:dormant_at]
        dormant_block = "" if dormant_at < 0 else block[dormant_at:]
        active_count = len(re.findall(r"^\| #", active_block, re.MULTILINE))
        dormant_count = len(re.findall(r"^\| #", dormant_block, re.MULTILINE))
        print(f"   active rows: {active_count}   dormant appendix: {dormant_count}")
    else:
        print("   no Watching section found")

    if blockers:
        print(f"\nFAIL: {len(blockers)} lifecycle blocker(s) require reconciliation.")
        return 1
    print("\nREPORT VALID: no active lifecycle blockers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
