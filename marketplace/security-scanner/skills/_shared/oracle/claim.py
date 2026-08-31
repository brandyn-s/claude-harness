"""Per-skill claim locks — root fix for parallel-batch overlap (cause 2).

The May 2026 fix campaign saw concurrent fix-batches resolve each
other's findings as side effects. E.g., batch B created
``_shared/repo-map.md`` as part of an unrelated fix; by the time
batch H ran, security-alerts' "missing repo-map" finding was already
stale.

The mitigation was reverify-before-action. The root cause was lack
of coordination between parallel batches. This module fixes that:
each batch acquires per-skill claim locks BEFORE editing files in
that skill. A skill held by an active claim is skipped (or queued)
by overlapping batches.

Claims live at ``~/.claude/oracle-claims/<skill>.json``:

  {
    "skill": "weekly-update",
    "claimed_at": "2026-05-25T15:04:23+00:00",
    "claimed_by": "<batch-id>",
    "pid": 12345,
    "purpose": "behavior-fix batch B"
  }

If the claim is older than ``CLAIM_MAX_AGE_SECONDS`` (default 30
minutes), it's treated as orphaned and overwritable — a fix-agent
that crashes shouldn't permanently block its skill.
"""
from __future__ import annotations

import contextlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


CLAIM_DIR_DEFAULT = Path.home() / ".claude" / "oracle-claims"
CLAIM_MAX_AGE_SECONDS = 30 * 60  # 30 minutes


def claim_dir() -> Path:
    """Resolve the claim directory honoring AUDIT_SKILL_ORACLE_CLAIM_DIR
    env var (tests use this to redirect to a tmpdir)."""
    override = os.environ.get("AUDIT_SKILL_ORACLE_CLAIM_DIR")
    return Path(override) if override else CLAIM_DIR_DEFAULT


@dataclass
class Claim:
    skill: str
    claimed_at: str
    claimed_by: str
    pid: int
    purpose: str

    @classmethod
    def fresh(cls, skill: str, claimed_by: str, purpose: str) -> "Claim":
        return cls(
            skill=skill,
            claimed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            claimed_by=claimed_by,
            pid=os.getpid(),
            purpose=purpose,
        )

    def age_seconds(self) -> float:
        try:
            then = datetime.fromisoformat(self.claimed_at)
        except ValueError:
            return float("inf")
        return (datetime.now(timezone.utc) - then).total_seconds()

    def is_orphan(self) -> bool:
        return self.age_seconds() > CLAIM_MAX_AGE_SECONDS

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2)


def _claim_path(skill: str) -> Path:
    return claim_dir() / f"{skill}.json"


def try_acquire(skill: str, claimed_by: str, purpose: str) -> tuple[bool, str]:
    """Atomically attempt to acquire the claim for ``skill``.
    Returns (acquired, reason). Acquired=True means the caller now
    owns the claim; reason is informational.

    Uses ``O_CREAT|O_EXCL`` on a marker file for true atomicity —
    two callers racing on the same skill will see exactly one win.
    If an existing claim is orphaned (older than the max age), it's
    cleared and we retry once."""
    claim_dir().mkdir(parents=True, exist_ok=True)
    path = _claim_path(skill)
    claim = Claim.fresh(skill, claimed_by, purpose)

    for attempt in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            # Someone else holds it. Check if orphan.
            try:
                existing_data = json.loads(path.read_text(encoding="utf-8"))
                existing = Claim(**existing_data)
            except (OSError, json.JSONDecodeError, TypeError):
                # Corrupt claim — treat as orphan, clear and retry.
                if attempt == 0:
                    path.unlink(missing_ok=True)
                    continue
                return False, f"corrupt claim file at {path}"
            if existing.is_orphan() and attempt == 0:
                # Orphaned by a crashed prior caller; reclaim.
                path.unlink(missing_ok=True)
                continue
            return False, (
                f"held by {existing.claimed_by!r} since {existing.claimed_at} "
                f"({existing.age_seconds():.0f}s ago, pid={existing.pid}, "
                f"purpose={existing.purpose!r})"
            )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(claim.to_json())
            return True, f"acquired by {claimed_by}"
        except OSError:
            path.unlink(missing_ok=True)
            return False, "write failed after acquire"
    return False, "exhausted retries"


def release(skill: str, claimed_by: str) -> bool:
    """Release the claim for ``skill`` if owned by ``claimed_by``.
    Returns True if released, False if not held / held by a different
    caller (a safety check — don't let one batch release another's
    claim by accident)."""
    path = _claim_path(skill)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Corrupt — clear it; safer than leaving wedge.
        path.unlink(missing_ok=True)
        return False
    if data.get("claimed_by") != claimed_by:
        return False
    path.unlink(missing_ok=True)
    return True


@contextlib.contextmanager
def claim(skill: str, claimed_by: str, purpose: str) -> Iterator[bool]:
    """Context manager wrapping try_acquire + release. Yields the
    acquired-bool so the caller can branch on success without raising.

    Usage:

        with claim("weekly-update", "batch-H", "behavior-fix batch H") as got:
            if not got:
                print("skipped — already claimed")
                return
            # apply fix here
    """
    acquired, _reason = try_acquire(skill, claimed_by, purpose)
    try:
        yield acquired
    finally:
        if acquired:
            release(skill, claimed_by)


def list_claims() -> list[Claim]:
    """List all current claims (orphans included). Used by the CLI
    to surface "what's currently held" for diagnostics."""
    d = claim_dir()
    if not d.is_dir():
        return []
    out: list[Claim] = []
    for path in sorted(d.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append(Claim(**data))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    return out


def clear_orphans() -> int:
    """Garbage-collect orphaned claims (older than the max age).
    Returns the count cleared. Safe to call any time; idempotent."""
    cleared = 0
    for c in list_claims():
        if c.is_orphan():
            _claim_path(c.skill).unlink(missing_ok=True)
            cleared += 1
    return cleared
