#!/usr/bin/env python3
"""Backfill mechanical reproducers + enforce the label contract.

Phase 2 agents sometimes emit findings with `type: manual` while
labeling them `doc-fix` or `behavior-fix`. The orchestrator contract
(see `oracle/templates/phase2-prompt.md`) requires `type: manual` to
pair with `label: unverified` — only then does the route to human
review work correctly.

This script does two things to an existing findings YAML:

1. Convert mechanically-detectable patterns to auto-checkable
   reproducers (file_missing for "cites X — file doesn't exist",
   grep_absent for "Z is missing from path"). The converted finding
   keeps its original label.

2. For findings that remain `type: manual`, demote the label to
   `unverified` so the orchestrator routes them correctly. This is
   a CONTRACT enforcement, not a verdict on the finding — the bug
   may still be real; the agent just didn't supply machine-checkable
   evidence.

Usage:
    python3 scripts/backfill_reproducers.py <findings.yaml>
        [--out PATH] [--dry-run]

Without --out, writes in place.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "skills" / "_shared"))

try:
    import yaml
except ImportError:
    print("PyYAML required", file=sys.stderr)
    sys.exit(2)


# Pattern: '... cites `<path>` — file doesn't exist' or similar.
# Captures the path inside backticks or quotes. The path must end in a
# recognized extension to avoid matching prose like "the X system".
FILE_MISSING_RE = re.compile(
    r"""(?:cites?|references?|points\s+to|references?d\s+at|at)\s+
        [`'"]?(?P<path>[^\s`'"]+\.(?:md|py|ya?ml|sh|json|toml|rs|go|ts|tsx|js|jsx))[`'"]?
        \s*[—\-:]?\s*
        (?:file\s+)?(?:doesn'?t\s+exist|does\s+not\s+exist|missing|not\s+found)""",
    re.IGNORECASE | re.VERBOSE,
)

# Alternative: "X — file doesn't exist" without "cites" prefix.
FILE_MISSING_FALLBACK_RE = re.compile(
    r"""[`'"](?P<path>[^\s`'"]+\.(?:md|py|ya?ml|sh|json|toml|rs|go|ts|tsx|js|jsx))[`'"]
        [\s—\-:]+(?:file\s+)?(?:doesn'?t\s+exist|does\s+not\s+exist|missing|not\s+found)""",
    re.IGNORECASE | re.VERBOSE,
)

# Allowlist for paths embedded in shell command strings. Findings are
# committed to the repo; a malicious description could otherwise inject
# shell metacharacters into the generated `test ! -e <path>` command.
# This allowlist is strict — letters, digits, underscore, dash, slash,
# dot, tilde, $-for-$HOME. No spaces (would break the test arg), no
# shell metacharacters (;, |, &, `, $(, etc.).
_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_./~$\-]+$")


def _is_safe_for_shell(path: str) -> bool:
    """Return True iff `path` can be safely interpolated into a bash
    command without shell-quoting. Rejects any string containing shell
    metacharacters; the regex-extracted path is treated as untrusted
    because findings YAML originates from auditor-written descriptions.
    """
    return bool(_SAFE_PATH_RE.match(path))


def detect_file_missing(description: str) -> str | None:
    """Return the cited path if description matches "cites X — file
    doesn't exist" shape. Returns None otherwise."""
    m = FILE_MISSING_RE.search(description)
    if not m:
        m = FILE_MISSING_FALLBACK_RE.search(description)
    if not m:
        return None
    path = m.group("path")
    # Expand ~ to a deployable form; the reproducer will run from repo_root,
    # so $HOME-relative paths need to use file_exists with absolute resolution.
    # For paths under known-external-paths (sibling repos), we should NOT
    # emit a finding — the registry exists for exactly this case.
    return path


def is_external_path(path: str, external_patterns: list[str]) -> bool:
    """Check if path matches a known-external-paths.yaml pattern."""
    norm = path.replace("~", "$HOME")
    for pat in external_patterns:
        pat_norm = pat.replace("~", "$HOME")
        # Substring match — the registry uses prefix patterns.
        if pat_norm.rstrip("/") in norm:
            return True
    return False


def load_external_patterns() -> list[str]:
    """Load known-external-paths.yaml as a list of pattern strings."""
    p = REPO / "skills" / "audit-skill" / "known-external-paths.yaml"
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    out: list[str] = []
    # The registry uses key "external_paths" (see
    # known-external-paths.yaml header).
    for entry in data.get("external_paths", []):
        if isinstance(entry, dict) and "pattern" in entry:
            out.append(entry["pattern"])
    return out


def backfill_one(finding: dict, external_patterns: list[str]) -> tuple[dict, str]:
    """Mutate `finding` if a mechanical reproducer can be derived from
    its description. Returns (finding, action) where action is one of:
      - "converted_file_missing"     — added a file_missing reproducer
      - "skipped_external_path"      — path lives in a sibling repo;
                                       finding likely false-positive
      - "demoted_to_unverified"      — kept type=manual, fixed label
      - "no_change"                  — already conforming
    """
    rep = finding.get("reproducer", {})
    if rep.get("type") != "manual":
        return finding, "no_change"

    desc = finding.get("description", "")
    path = detect_file_missing(desc)

    if path is not None:
        # Path is regex-extracted from auditor-written description;
        # reject if it would inject shell metacharacters when used in
        # bash `test ! -e <path>`. Demote to unverified instead of
        # building a dangerous reproducer.
        if not _is_safe_for_shell(path):
            finding["label"] = "unverified"
            finding["triage_note"] = (
                f"Cited path '{path[:40]}...' contains shell-metachar; "
                f"refusing to generate bash reproducer. Manual review."
            )
            return finding, "demoted_to_unverified"

        if is_external_path(path, external_patterns):
            # Likely a false positive — the path lives in a sibling
            # repo. Demote to unverified with a flag for review.
            finding["label"] = "unverified"
            finding["triage_note"] = (
                f"Cited path '{path}' is external (registry-matched); "
                f"finding may be false-positive. See "
                f"skills/audit-skill/known-external-paths.yaml."
            )
            return finding, "skipped_external_path"

        # Convert to file_missing reproducer. Three cases:
        #
        # 1) ~/.claude/<sub>/<rest> — the deployment mirror of the repo.
        #    Check the repo-relative path AND the deployed path; the
        #    bug is present iff BOTH are missing.
        # 2) ~/Documents/... or $HOME/... — operator-local; only the
        #    bash check resolves (already filtered for external repos).
        # 3) Repo-relative path — straight file_missing.
        repo_paths_for_deploy = {
            "~/.claude/rules/": "rules/",
            "$HOME/.claude/rules/": "rules/",
            "~/.claude/skills/": "skills/",
            "$HOME/.claude/skills/": "skills/",
            "~/.claude/agents/": "agents/",
            "$HOME/.claude/agents/": "agents/",
            "~/.claude/hooks/": "hooks/",
            "$HOME/.claude/hooks/": "hooks/",
            "~/.claude/agent-memory/": "agent-memory/",
            "$HOME/.claude/agent-memory/": "agent-memory/",
        }
        repo_rel = None
        for deploy_prefix, repo_prefix in repo_paths_for_deploy.items():
            if path.startswith(deploy_prefix):
                repo_rel = repo_prefix + path[len(deploy_prefix):]
                break

        if repo_rel is not None:
            # Bug iff BOTH repo path AND deployed path are missing.
            bash_path = path.replace("~/", "$HOME/")
            finding["reproducer"] = {
                "type": "bash",
                "command": (
                    f"test ! -e {repo_rel} && test ! -e {bash_path}"
                ),
                "expected_exit": 0,
                "description": (
                    f"finding fires iff '{path}' is missing from "
                    f"both the repo ('{repo_rel}') and deployment"
                ),
            }
        elif path.startswith("~/") or path.startswith("$HOME"):
            bash_path = path.replace("~/", "$HOME/")
            finding["reproducer"] = {
                "type": "bash",
                "command": f"test ! -e {bash_path}",
                "expected_exit": 0,
                "description": (
                    f"finding fires iff '{path}' does not exist on disk"
                ),
            }
        else:
            # The oracle resolves file_missing paths against repo_root
            # (finding.py fires()), but H1-shape citations are written
            # relative to the SKILL directory (`references/X.md`). A bare
            # skill-relative path therefore never resolves and the
            # reproducer becomes an always-fires tautology (2026-06-12
            # finding: a citation to an EXISTING references/ file reported
            # STILL-FIRES "exists=False"). Prefix skills/<skill>/ unless
            # the path already names a repo-root tree.
            _ROOT_PREFIXES = (
                "skills/", "rules/", "hooks/", "bin/", "scripts/",
                "manifests/", "agent-memory/", "AUDIT-TRACKERS/",
                "tests/", ".github/", "marketplace/", "templates/",
            )
            repo_path = path
            skill_name = str(finding.get("skill", "") or "")
            if skill_name and not path.startswith(_ROOT_PREFIXES):
                repo_path = f"skills/{skill_name}/{path}"
            finding["reproducer"] = {
                "type": "file_missing",
                "path": repo_path,
                "description": (
                    f"finding fires iff '{path}' (checked at "
                    f"'{repo_path}') does not exist"
                ),
            }
        return finding, "converted_file_missing"

    # No mechanical pattern matched — demote label to unverified per
    # the contract.
    if finding.get("label") in ("doc-fix", "behavior-fix"):
        finding["label"] = "unverified"
        return finding, "demoted_to_unverified"

    return finding, "no_change"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("findings_yaml", type=Path)
    ap.add_argument("--out", type=Path, help="output path (default: in-place)")
    ap.add_argument(
        "--dry-run", action="store_true",
        help="print summary without writing",
    )
    args = ap.parse_args()

    if not args.findings_yaml.exists():
        print(f"not found: {args.findings_yaml}", file=sys.stderr)
        sys.exit(2)

    try:
        data = yaml.safe_load(args.findings_yaml.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        # Category-B contract: clean error + recovery hint, no traceback.
        print(
            f"error: {args.findings_yaml} is not valid YAML: {e}\n"
            f"hint: fix the YAML (yamllint / python3 -c 'import yaml,sys; "
            f"yaml.safe_load(open(sys.argv[1]))') and re-run.",
            file=sys.stderr,
        )
        sys.exit(2)
    if not isinstance(data, dict):
        print(
            f"error: {args.findings_yaml} must be a YAML mapping with a "
            f"'findings:' list (got {type(data).__name__})",
            file=sys.stderr,
        )
        sys.exit(2)
    findings = data.get("findings", [])
    external = load_external_patterns()

    counts = {
        "converted_file_missing": 0,
        "skipped_external_path": 0,
        "demoted_to_unverified": 0,
        "no_change": 0,
    }
    for f in findings:
        # Skip findings already closed by triage.
        if f.get("triage_status") and f["triage_status"] not in ("", "open"):
            counts["no_change"] += 1
            continue
        _, action = backfill_one(f, external)
        counts[action] += 1

    print("Backfill summary:")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    total_open = sum(counts.values()) - counts["no_change"]
    print(f"  total open processed: {total_open}")

    if args.dry_run:
        return

    out = args.out or args.findings_yaml
    # yaml.safe_dump silently corrupts long quoted strings (truncation +
    # double-escape) when re-emitting a previously hand-edited tracker.
    # Use surgical text edits instead: each finding is identified by
    # (skill, code, description-prefix), and we modify only the fields
    # that changed. The original file's formatting is preserved.
    _write_surgical(data["findings"], args.findings_yaml, out)
    print(f"wrote {out}")


def _write_surgical(findings_after: list[dict], src: Path, out: Path) -> None:
    """Apply per-finding diffs back to the source YAML using text edits.

    The source YAML carries hand-edited quoting that yaml.safe_dump
    would clobber. Iterate the source in document order, match each
    `  - skill:` block against the corresponding finding_after by
    POSITION (the parser produces findings in source order, so the
    Nth finding-after corresponds to the Nth source block).

    Only three fields are mutated:
      - label: line-level replacement
      - reproducer: block-level replacement, but only when the
        finding was converted to an auto-checkable reproducer
      - triage_note: appended at the end of the block if newly set
    """
    source_text = src.read_text(encoding="utf-8")
    source_lines = source_text.splitlines(keepends=True)

    # Build block ranges in source order. Accept ANY sequence-item indent:
    # hand-maintained trackers use "  - skill:" (2-space), but PyYAML's
    # default dump puts dashes at column 0 ("- skill:") — both are valid
    # YAML and both are accepted by load_findings, so the writer must not
    # reject one of them (2026-06-12 finding: a machine-generated tracker
    # aborted with "source has 0 blocks" + raw traceback).
    item_re = re.compile(r"^( *)- skill:")
    finding_ranges: list[tuple[int, int, int]] = []  # (start, end, key_indent)
    start = None
    start_indent = 0
    for i, ln in enumerate(source_lines):
        m = item_re.match(ln)
        if m:
            if start is not None:
                finding_ranges.append((start, i, start_indent + 2))
            start = i
            start_indent = len(m.group(1))
    if start is not None:
        finding_ranges.append((start, len(source_lines), start_indent + 2))

    if len(finding_ranges) != len(findings_after):
        # Defensive: source block count must match parsed findings count
        # exactly, else position-based matching is unsafe.
        raise RuntimeError(
            f"source has {len(finding_ranges)} blocks but parsed "
            f"{len(findings_after)} findings; aborting to avoid "
            f"corrupting the tracker"
        )

    # Process in reverse so line-index edits to later blocks don't
    # shift earlier ones.
    for f_after, (s, e, ki) in reversed(list(zip(findings_after, finding_ranges))):
        _patch_block_in_place(source_lines, s, e, f_after, ki)

    out.write_text("".join(source_lines), encoding="utf-8")


def _patch_block_in_place(
    source_lines: list[str], start: int, end: int, f_after: dict,
    key_indent: int = 4,
) -> None:
    """Update label, reproducer (if converted), triage_status, triage_note.

    Other fields and original line formatting are preserved. `key_indent`
    is the column of the finding's keys (sequence-item indent + 2), so
    both 2-space-indented and column-0 item styles patch correctly.
    """
    kp = " " * key_indent          # finding-key prefix, e.g. "    "
    rp = " " * (key_indent + 2)    # reproducer-key prefix

    # Update label.
    target_label = f_after.get("label")
    if target_label is not None:
        for i in range(start, end):
            if source_lines[i].startswith(f"{kp}label:"):
                source_lines[i] = f"{kp}label: {target_label}\n"
                break

    # Replace reproducer ONLY when the type changed away from manual.
    # If both source and after are type:manual, leave the source
    # reproducer block untouched (preserves original description).
    rep_after = f_after.get("reproducer", {})
    rep_after_type = rep_after.get("type") if rep_after else None
    rep_source_type = None
    rep_start = None
    rep_end = None
    for i in range(start, end):
        if source_lines[i].startswith(f"{kp}reproducer:"):
            rep_start = i
            for j in range(i + 1, end):
                ln = source_lines[j]
                if ln.startswith(f"{rp}type:"):
                    rep_source_type = ln.split(":", 1)[1].strip()
                if ln.startswith(kp) and not ln.startswith(rp) and ":" in ln:
                    rep_end = j
                    break
            if rep_end is None:
                rep_end = end
            break
    if (rep_start is not None and rep_after_type
            and rep_after_type != rep_source_type):
        new_block = _format_reproducer(rep_after, key_indent)
        source_lines[rep_start:rep_end] = new_block
        # Adjust end pointer for downstream operations.
        end = rep_start + len(new_block) + (end - rep_end)

    # Update triage_status (replace existing OR append new).
    ts = f_after.get("triage_status")
    if ts:
        ts_present = False
        for i in range(start, end):
            if source_lines[i].startswith(f"{kp}triage_status:"):
                source_lines[i] = f"{kp}triage_status: {ts}\n"
                ts_present = True
                break
        if not ts_present:
            source_lines.insert(end, f"{kp}triage_status: {ts}\n")
            end += 1

    # Update triage_note (replace existing OR append new).
    note = f_after.get("triage_note")
    if note:
        note_present = False
        for i in range(start, end):
            if source_lines[i].startswith(f"{kp}triage_note:"):
                source_lines[i] = f"{kp}triage_note: {_yaml_quote(note)}\n"
                note_present = True
                break
        if not note_present:
            source_lines.insert(end, f"{kp}triage_note: {_yaml_quote(note)}\n")


def _format_reproducer(rep: dict, key_indent: int = 4) -> list[str]:
    """Format a reproducer dict as YAML lines at the block's indent."""
    kp = " " * key_indent
    rp = " " * (key_indent + 2)
    bp = " " * (key_indent + 4)
    lines = [f"{kp}reproducer:\n"]
    for k, v in rep.items():
        if not v:
            continue
        if isinstance(v, str) and ("\n" in v or len(v) > 80):
            lines.append(f"{rp}{k}: |\n")
            for sub in v.splitlines():
                lines.append(f"{bp}{sub}\n")
        elif isinstance(v, str):
            lines.append(f"{rp}{k}: {_yaml_quote(v)}\n")
        else:
            lines.append(f"{rp}{k}: {v}\n")
    return lines


def _yaml_quote(v) -> str:
    """Quote a YAML scalar minimally. Strings with special chars get
    double-quoted; other scalars rendered verbatim."""
    if isinstance(v, str):
        special = any(c in v for c in [':', '#', '"', "'", '\n', '\t'])
        if special or v.strip() != v or v == "":
            escaped = v.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return v
    return str(v)


if __name__ == "__main__":
    main()
