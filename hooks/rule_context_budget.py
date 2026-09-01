"""Shared budget accounting for always-loaded Claude Code rules.

Claude Code loads every top-level ``rules/*.md`` file without ``paths:``
frontmatter into the main session and ordinary children. A per-file ceiling
cannot prevent dozens of individually valid files from exhausting the window,
so the corpus needs an aggregate ceiling as well.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

# The installed architecture was qualified beneath this ceiling. The 50--60 KB
# band is an A/B optimization target, not an unqualified correctness boundary.
AB_TARGET_LOW_BYTES = 50_000
AB_TARGET_HIGH_BYTES = 60_000
WARN_BYTES = 225_000
HARD_CAP_BYTES = 250_000
BLOCK_BYTES = HARD_CAP_BYTES

# Corpus-specific calibration from Anthropic's count_tokens endpoint. Keep the
# measured pair, not a rounded chars/token constant, so every reporter produces
# the same result and reviewers can see exactly what was observed.
TOKEN_CALIBRATION_BYTES = 206_428
TOKEN_CALIBRATION_TOKENS = 75_413


def estimate_tokens(byte_count: int) -> int:
    """Estimate tokens using the measured ambient-corpus calibration."""

    return int(byte_count * TOKEN_CALIBRATION_TOKENS / TOKEN_CALIBRATION_BYTES)


class RuleContextBudgetError(RuntimeError):
    """The rule corpus could not be measured without undercounting."""


@dataclass(frozen=True)
class RuleContextSnapshot:
    """One strict scan of the ambient rule corpus."""

    files: tuple[Path, ...]
    total_bytes: int


def has_paths_frontmatter(text: str) -> bool:
    """Return True only for a YAML frontmatter block containing ``paths:``."""

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    closing = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing is None:
        raise RuleContextBudgetError("unterminated YAML frontmatter")
    frontmatter = "\n".join(lines[1:closing])
    try:
        parsed = yaml.safe_load(frontmatter) or {}
    except yaml.YAMLError as exc:
        raise RuleContextBudgetError("invalid YAML frontmatter") from exc
    if not isinstance(parsed, dict):
        raise RuleContextBudgetError("YAML frontmatter must be a mapping")
    if "paths" not in parsed:
        return False
    paths = parsed["paths"]
    if isinstance(paths, str):
        if not paths.strip():
            raise RuleContextBudgetError("paths frontmatter must not be empty")
        return True
    if isinstance(paths, list) and paths and all(
        isinstance(item, str) and item.strip() for item in paths
    ):
        return True
    raise RuleContextBudgetError("paths frontmatter must be a string or non-empty list")


def _strict_rule_text(path: Path) -> tuple[str, int]:
    if path.is_symlink():
        raise RuleContextBudgetError(f"top-level rule must not be a symlink: {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RuleContextBudgetError(f"cannot read rule {path}: {exc}") from exc
    try:
        return raw.decode("utf-8"), len(raw)
    except UnicodeDecodeError as exc:
        raise RuleContextBudgetError(f"rule is not valid UTF-8: {path}") from exc


def scan_unconditional_rules(
    rules_dir: Path,
    overrides: dict[Path, str | None] | None = None,
) -> RuleContextSnapshot:
    """Strictly scan top-level ambient rules once.

    Any condition that could hide bytes fails closed instead of being treated as
    an empty or out-of-scope file.
    """

    root = rules_dir.expanduser().resolve()
    try:
        candidates = set(rules_dir.glob("*.md"))
    except OSError as exc:
        raise RuleContextBudgetError(f"cannot enumerate rules in {rules_dir}: {exc}") from exc

    normalized: dict[Path, str | None] = {}
    for raw_path, content in (overrides or {}).items():
        path = Path(raw_path).expanduser()
        if path.is_symlink():
            raise RuleContextBudgetError(f"top-level rule must not be a symlink: {path}")
        resolved = path.resolve()
        if resolved.parent != root:
            raise RuleContextBudgetError(f"rule path escapes rules directory: {path}")
        normalized[resolved] = content
        candidates.add(path)

    ambient: list[Path] = []
    total = 0
    for path in sorted(candidates):
        if path.is_symlink():
            raise RuleContextBudgetError(f"top-level rule must not be a symlink: {path}")
        resolved = path.expanduser().resolve()
        if resolved.parent != root:
            raise RuleContextBudgetError(f"rule path escapes rules directory: {path}")
        if resolved in normalized:
            text = normalized[resolved]
            if text is None:
                continue
            byte_count = len(text.encode("utf-8"))
        else:
            text, byte_count = _strict_rule_text(resolved)
        if not has_paths_frontmatter(text):
            ambient.append(resolved)
            total += byte_count
    return RuleContextSnapshot(tuple(ambient), total)


def unconditional_rule_files(rules_dir: Path) -> list[Path]:
    """List top-level ambient rule files, excluding path-scoped rules."""

    return list(scan_unconditional_rules(rules_dir).files)


def unconditional_rule_bytes(
    rules_dir: Path,
    overrides: dict[Path, str | None] | None = None,
) -> int:
    """Return UTF-8 bytes for ambient rules, with optional projected content."""

    return scan_unconditional_rules(rules_dir, overrides).total_bytes


# --------------------------------------------------------------------------
# Delta gate
#
# The aggregate ceilings above bound the corpus ABSOLUTELY. They do not bound its
# GROWTH, and growth is the thing that produced 13 cap-repair PRs: a ceiling is a
# cliff, so every repair converges to just under it and the next append breaches it.
#
# So the operative ceiling is a LEDGER value, and it is DERIVED rather than stored:
#
#     allowed = baseline_unconditional_bytes + sum(entry.bytes for entry in ledger)
#
# There is no stored ceiling to edit, so raising it requires appending an entry that
# names the bytes and the reason. A negative entry ratchets the budget DOWN, which is
# how a relocation's savings are made permanent instead of silently reusable.
# --------------------------------------------------------------------------

BUDGET_LEDGER_RELPATH = "manifests/ambient-budget.json"


@dataclass(frozen=True)
class AmbientBudget:
    """The derived ambient ceiling and the entries that produced it."""

    baseline_bytes: int
    allowed_bytes: int
    entries: tuple[dict, ...]
    path: Path


def load_ambient_budget(ledger_path: Path) -> AmbientBudget:
    """Read the ledger and DERIVE the ceiling from it.

    Raises RuleContextBudgetError rather than defaulting: a missing or malformed
    ledger must fail loudly, because a silent default would make deleting the gate
    indistinguishable from the gate passing.
    """

    try:
        raw = json.loads(ledger_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuleContextBudgetError(f"ambient budget ledger missing: {ledger_path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuleContextBudgetError(f"ambient budget ledger unreadable: {exc}") from exc

    if not isinstance(raw, dict):
        raise RuleContextBudgetError("ambient budget ledger must be a JSON object")
    baseline = raw.get("baseline_unconditional_bytes")
    if not isinstance(baseline, int) or isinstance(baseline, bool) or baseline <= 0:
        raise RuleContextBudgetError("baseline_unconditional_bytes must be a positive int")
    entries = raw.get("ledger")
    if not isinstance(entries, list):
        raise RuleContextBudgetError("ledger must be a list")

    total = baseline
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise RuleContextBudgetError(f"ledger[{index}] must be an object")
        delta = entry.get("bytes")
        if not isinstance(delta, int) or isinstance(delta, bool):
            raise RuleContextBudgetError(f"ledger[{index}].bytes must be an int")
        # Every entry must justify itself. An unexplained ledger row is the same
        # unreviewable ceiling bump the derived form exists to prevent.
        for field_name in ("date", "rule", "reason"):
            value = entry.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise RuleContextBudgetError(
                    f"ledger[{index}].{field_name} must be a non-empty string"
                )
        total += delta

    if total <= 0:
        raise RuleContextBudgetError("derived ambient ceiling must stay positive")
    return AmbientBudget(
        baseline_bytes=baseline,
        allowed_bytes=total,
        entries=tuple(entries),
        path=ledger_path,
    )
