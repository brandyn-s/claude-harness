"""Markdown-tracker → YAML converter.

The Phase 2 audit (run before this oracle landed) emitted findings as
prose in ``AUDIT-TRACKERS/05-phase2-findings.md``. The oracle's
reverify layer needs structured Reproducers, not prose. This module
parses the markdown tracker and emits a YAML findings file with
``type: manual`` Reproducers for findings whose prose doesn't yield
a deterministic predicate, and best-effort grep/file-check
Reproducers for the ones whose prose hints at one.

Going forward, Phase 2 agents should emit YAML directly (see
``skills/audit-skill/SKILL.md`` §"Phase 2: Agent checks" — Reproducer
schema). This converter exists for the back-catalog only; new audits
should produce YAML at source so the conversion is unnecessary.

Format expected:

  ### <skill-name>
  - [severity] [behavior-fix|doc-fix|unverified] CODE: description.
    Reproducer: ...
  - ...

  ### <next-skill>
  ...

The parser is permissive: it doesn't require the Reproducer to be on
a specific line, and it does NOT attempt deep prose parsing — for any
finding without an obvious grep/file-check shape, it emits
``type: manual`` with the description preserved.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from .finding import Finding, Reproducer

_HEADER = re.compile(r"^###\s+(\S.*?)\s*$")
_BULLET = re.compile(
    r"^-\s*"
    r"\[(?P<severity>[a-z]+)\]\s*"
    r"\[(?P<label>[a-z-]+)\]\s*"
    r"(?P<code>[A-Z][0-9a-z]+):\s*"
    r"(?P<rest>.*)$"
)


def parse_tracker(tracker_path: Path) -> Iterator[Finding]:
    """Yield Finding objects parsed from a Phase 2 markdown tracker.

    The parser is forgiving: it skips lines that don't match the
    expected bullet shape (so prose intro paragraphs, summary tables,
    and section headers are ignored without erroring)."""
    text = tracker_path.read_text(encoding="utf-8")
    skill = ""
    for raw in text.splitlines():
        h = _HEADER.match(raw)
        if h:
            skill = h.group(1).strip()
            continue
        # Skip code-fence content (some skills' findings show example bash)
        # by tracking ```/``` boundaries; cheap approximation since the
        # tracker's structure is shallow.
        if raw.strip().startswith("```"):
            continue
        b = _BULLET.match(raw.strip())
        if not b or not skill:
            continue
        rest = b.group("rest").strip()
        # Best-effort: extract the description (everything before
        # "Reproducer:" or the first sentence-end if no Reproducer)
        description = rest
        reproducer_prose = ""
        if "Reproducer:" in rest:
            description, _sep, reproducer_prose = rest.partition("Reproducer:")
            description = description.strip().rstrip(". ")
            reproducer_prose = reproducer_prose.strip()
        # Generate a best-effort Reproducer from the prose.
        rep = _infer_reproducer(skill, description, reproducer_prose)
        yield Finding(
            skill=skill,
            code=b.group("code"),
            severity=b.group("severity"),
            label=b.group("label"),
            description=description,
            reproducer=rep,
        )


def _infer_reproducer(skill: str, description: str, reproducer_prose: str) -> Reproducer:
    """Best-effort: produce a deterministic Reproducer from the prose.

    Patterns we recognize:
      - "cited references/X.md" + "does not exist" → file_missing
      - "manifest declares X but never invoked" → grep_absent on body
      - "phantom MCP tool 'mcp__...__...'" → grep for the name
      - "{baseDir}" / "<your-X>" mention → grep for the placeholder
      - "scripts/X.py" + "does not exist" → file_missing

    For anything we can't reduce, fall back to ``type: manual`` with
    the prose as the description — those findings can't be auto-
    verified and must remain ``[unverified]`` until someone hand-
    writes a Reproducer."""
    full = (description + " " + reproducer_prose).lower()
    skill_path = f"skills/{skill}"

    # Phantom-tool reference
    m = re.search(r"mcp__[a-z0-9_-]+__[a-z0-9_-]+", full)
    if m and ("phantom" in full or "known-phantom" in full):
        tool = m.group(0)
        return Reproducer(
            type="grep",
            command=f"grep -rE '{re.escape(tool)}' {skill_path} || true",
            description=f"phantom MCP tool {tool} reference",
        )

    # Missing file (citation to references/X.md)
    m = re.search(r"references/([a-z0-9._-]+\.md)", full)
    if m and ("does not exist" in full or "doesn't exist" in full or "missing" in full):
        ref = m.group(1)
        return Reproducer(
            type="file_missing",
            path=f"{skill_path}/references/{ref}",
            description=f"cited references/{ref} does not exist",
        )

    # Missing script
    m = re.search(r"scripts/([a-z0-9._-]+\.py)", full)
    if m and ("does not exist" in full or "missing" in full or "nonexistent" in full):
        script = m.group(1)
        return Reproducer(
            type="file_missing",
            path=f"{skill_path}/scripts/{script}",
            description=f"script {script} not present",
        )

    # Placeholder syntax
    if "{basedir}" in full or "{projectroot}" in full:
        return Reproducer(
            type="grep",
            command=f"grep -rE '\\{{baseDir\\}}|\\{{projectRoot\\}}' {skill_path}/SKILL.md || true",
            description="unresolved template placeholder in SKILL.md",
        )
    if "<your-" in full:
        return Reproducer(
            type="grep",
            command=f"grep -E '<your-[a-z0-9-]+>' {skill_path}/SKILL.md || true",
            description="<your-X> placeholder in SKILL.md",
        )

    # Generic: no machine-checkable predicate could be inferred.
    return Reproducer(
        type="manual",
        description=description + (" / " + reproducer_prose if reproducer_prose else ""),
    )


def convert_tracker_to_yaml(tracker_path: Path, out_path: Path) -> int:
    """Write parsed findings as YAML. Returns the count of findings
    written (so callers can sanity-check)."""
    findings = list(parse_tracker(tracker_path))
    # Use the existing dump helper which emits JSON; tests + oracle
    # accept either, and JSON is unambiguous.
    out_path.write_text(_to_yaml(findings), encoding="utf-8")
    return len(findings)


def _to_yaml(findings: list[Finding]) -> str:
    """Tiny YAML emitter — matches the format the loader accepts."""
    out = ["findings:"]
    for f in findings:
        out.append(f"  - skill: {f.skill}")
        out.append(f"    code: {f.code}")
        out.append(f"    severity: {f.severity}")
        out.append(f"    label: {f.label}")
        out.append(f"    description: {_yaml_escape(f.description)}")
        out.append("    reproducer:")
        out.append(f"      type: {f.reproducer.type}")
        if f.reproducer.command:
            if "\n" in f.reproducer.command:
                # Multi-line commands (python snippets especially) MUST keep
                # their newlines: _yaml_escape's `\n → " "` flattening turns
                # a valid python reproducer into a one-line SyntaxError, so
                # every act-on worklist round-trip broke it (2026-06-12:
                # the parser-truncation finding ERROR'd in the worklist while
                # passing in the tracker). Emit a block scalar instead —
                # the loader's block-scalar path reads it back exactly.
                out.append("      command: |")
                for sub in f.reproducer.command.rstrip("\n").splitlines():
                    out.append(f"        {sub}")
            else:
                out.append(f"      command: {_yaml_escape(f.reproducer.command)}")
        if f.reproducer.path:
            out.append(f"      path: {f.reproducer.path}")
        if f.reproducer.expected_exit:
            out.append(f"      expected_exit: {f.reproducer.expected_exit}")
        # transcript_pattern fields (added 2026-05-26 for audit-rules lift)
        if f.reproducer.metric_path:
            out.append(f"      metric_path: {_yaml_escape(f.reproducer.metric_path)}")
        if f.reproducer.threshold:
            out.append(f"      threshold: {f.reproducer.threshold}")
        if f.reproducer.threshold_op and f.reproducer.threshold_op != "gte":
            out.append(f"      threshold_op: {f.reproducer.threshold_op}")
        if f.reproducer.description:
            out.append(f"      description: {_yaml_escape(f.reproducer.description)}")
        if f.source:
            out.append(f"    source: {_yaml_escape(f.source)}")
        if f.triage_status:
            out.append(f"    triage_status: {f.triage_status}")
        if f.triage_note:
            out.append(f"    triage_note: {_yaml_escape(f.triage_note)}")
        # Round-trip EVERY extra field, not a hand-picked subset. The
        # loader routes unknown keys into Finding.extra precisely so
        # campaign metadata (location, oracle_verdict, verified_at, ...)
        # survives load→modify→write cycles; emitting only known fields
        # silently DROPPED all 451 `location:` fields on the first
        # set-triage-status rewrite (2026-06-12 finding). Values are
        # emitted single-line; multi-line extras are flattened by
        # _yaml_escape (none exist today — keep extras scalar).
        for k in sorted(f.extra):
            v = f.extra[k]
            if v in (None, ""):
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append(f"    {k}: {v}")
            else:
                out.append(f"    {k}: {_yaml_escape(str(v))}")
    return "\n".join(out) + "\n"


def _yaml_escape(s: str) -> str:
    """Quote a string for YAML (single line — multi-line not needed
    for the tracker output)."""
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", " ").replace("\r", " ")
    return f'"{s}"'


def update_triage_surgical(path, match_indices, status, note=None):
    """Set triage_status (and optionally triage_note) on the findings at
    ``match_indices`` (document order) via line-level edits — every other
    byte of the file is preserved.

    This replaces the previous full re-emit through _to_yaml for triage
    updates: a one-field change used to rewrite all N findings, which is
    how the 2026-06-12 campaign tracker lost all 451 `location:` fields
    in a single set-triage-status call (the emitter of that era dropped
    unknown fields). Surgical edits make the blast radius of a triage
    update exactly the triage lines of the matched blocks.

    Accepts both sequence-item indents ("  - skill:" and column-0
    "- skill:"). Returns the number of blocks patched. Raises ValueError
    when an index has no corresponding block (file/finding-order drift —
    caller should reconcile, not write).
    """
    import re as _re
    from pathlib import Path as _Path

    p = _Path(path)
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)

    item_re = _re.compile(r"^( *)- skill:")
    blocks = []  # (start, end, key_indent)
    start = None
    indent = 0
    for i, ln in enumerate(lines):
        m = item_re.match(ln)
        if m:
            if start is not None:
                blocks.append((start, i, indent + 2))
            start = i
            indent = len(m.group(1))
    if start is not None:
        blocks.append((start, len(lines), indent + 2))

    missing = [i for i in match_indices if i >= len(blocks)]
    if missing:
        raise ValueError(
            f"finding indices {missing} exceed the {len(blocks)} blocks in "
            f"{p} — file and finding order have drifted; refusing to write"
        )

    patched = 0
    # Reverse order so insertions don't shift earlier block ranges.
    for idx in sorted(set(match_indices), reverse=True):
        s, e, ki = blocks[idx]
        kp = " " * ki
        ts_line = f"{kp}triage_status: {status}\n"
        done_status = False
        for i in range(s, e):
            if lines[i].startswith(f"{kp}triage_status:"):
                lines[i] = ts_line
                done_status = True
                break
        if not done_status:
            lines.insert(e, ts_line)
            e += 1
        if note is not None:
            note_line = f"{kp}triage_note: {_yaml_escape(note)}\n"
            done_note = False
            for i in range(s, e):
                if lines[i].startswith(f"{kp}triage_note:"):
                    lines[i] = note_line
                    done_note = True
                    break
            if not done_note:
                lines.insert(e, note_line)
        patched += 1

    p.write_text("".join(lines), encoding="utf-8")
    return patched
