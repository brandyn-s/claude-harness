#!/usr/bin/env python3
"""Detect staged hook specs whose fix has ALREADY SHIPPED.

`hooks/staged/*.spec.md` is a work queue with no completion mechanism: /ship-hook
installs a spec but nothing deletes it, so an obsolete spec sits there
indefinitely. Any later session that reads one — especially on a checkout behind
origin/main — re-derives solved work.

INCIDENT 2026-07-28 (session 19491bf1): read
`tail-guard-preserve-exit-status.spec.md`, ran its mandated replay (174 incidents
/ 8.23% of 2,114 audit events), wrote the fix + 11 tests, mutation-verified 5/5 —
then found PR #1713 (2026-07-26) had already shipped the spec's PREFERRED fix
(`__tbg_rc=$?` + `exit $__tbg_rc`) two days earlier. The work was a strictly
weaker re-solution; a blind copy into the ship worktree would have REVERTED the
real fix (the clobber guard caught it: 54 insertions / 30 deletions).

Detection: each spec names its target file in a `**Type**:` line. If that target
already contains the spec's own marker string, the fix has shipped and the spec
is stale. Markers are declared per-spec below rather than inferred — inferring a
marker from prose is unreliable, and a wrong marker yields a false "stale"
verdict that would delete live work.

Exit codes:
  0  no stale specs (or none with a declared marker)
  1  at least one stale spec found  (healthcheck WARN)
"""
import argparse
import pathlib
import re
import subprocess
import sys

_COLON_SHIPPED = (
    "2026-08-27 — colon-modifier branch in hooks/zsh-dialect-guard.py. NOTE: the "
    "implementation deliberately does NOT match either spec's character set. Both "
    "were measured WRONG in zsh 5.9 (each listed inert letters, so either would "
    'fire on the safe and very common docker tag "$IMG:prod"; the older one also '
    "missed Q). Shipped set is the measured acehlqrtuAPQ&s. 0.036% corpus fire "
    "rate, 4 of 4 fires genuine, 10/10 mutations CAUGHT."
)

# Per-spec shipped-marker declarations.
#   key    = spec filename under hooks/staged/
#   target = repo-relative file the spec modifies
#   marker = string present in `target` IFF the fix has shipped
# A spec absent from this map is reported as UNVERIFIABLE (not stale) — it needs
# a marker added when authored. That is deliberate: silence beats a false delete.
MARKERS = {
    "tail-guard-preserve-exit-status.spec.md": {
        "target": "hooks/bash-tail-buffering-guard.py",
        "marker": "__tbg_rc",
        "shipped_by": "#1713 (2026-07-26) — v6 exit-code preservation",
    },
    "git-gating-pipe-guard.spec.md": {
        "target": "hooks/bash-tail-buffering-guard.py",
        # A gating-git detection would have to name git somewhere in the guard's
        # producer/consumer logic. Verified absent on origin/main 2026-07-28.
        "marker": "GIT_GATING",
        "shipped_by": None,
    },
    # --- added 2026-08-27 -------------------------------------------------------
    # Both specs below declare their own install in their bodies, and both were
    # verified against zsh-dialect-guard.py's SOURCE (not its prose or
    # ARCHITECTURE.md's row) before being registered here. Registering them turns a
    # manual reading into a rerunnable check, which is what licenses the `git rm`.
    "bash-glob-metachar-guard.spec.md": {
        "target": "hooks/zsh-dialect-guard.py",
        # The regex for the spec's headline case, `--include=*.py`. Unique to this
        # hook (plus its own tests/replay harness); verified present 2026-08-27.
        "marker": "_OPT_EQ",
        "shipped_by": "#1874 (2026-08-02) — installed as hooks/zsh-dialect-guard.py; "
                      "the spec's own body records all 5 items complete, and its "
                      "word-splitting half is marked SUPERSEDED",
    },
    "zsh-word-splitting-guard.spec.md": {
        "target": "hooks/zsh-dialect-guard.py",
        # Deliberately the FOR-IN branch, not `_SET_DASHDASH`: the spec's last
        # request was the 2026-08-16 extension lifting the v1 `for X in $var`
        # exclusion, so `_FOR_IN_SPLIT` is the marker that proves the WHOLE spec
        # shipped rather than only its first half. Verified present 2026-08-27.
        "marker": "_FOR_IN_SPLIT",
        "shipped_by": "2026-08-08 install (set-dashdash, flag-packing) + 2026-08-16 "
                      "extension (for-in-split, 9/6836 = 0.132%, 5/5 mutations CAUGHT)",
    },
    # The colon-modifier hazard was staged TWICE by different sessions — 2026-08-12
    # as `zsh-unbraced-colon-modifier` and 2026-08-27 as `zsh-colon-modifier-guard`
    # (via #2158). Same lesson, same proposed disposition, same target. Both point at
    # one marker so the pair resolves together and neither can be re-derived alone.
    # Both flipped live -> STALE on 2026-08-27 when the branch landed, which is the
    # known-negative/known-positive transition that qualifies this instrument: it
    # reported `live` before the change and `STALE` after, on the same marker.
    "zsh-unbraced-colon-modifier.spec.md": {
        "target": "hooks/zsh-dialect-guard.py",
        "marker": "_COLON_MODIFIER",
        "shipped_by": _COLON_SHIPPED,
    },
    "zsh-colon-modifier-guard.spec.md": {
        "target": "hooks/zsh-dialect-guard.py",
        "marker": "_COLON_MODIFIER",
        "shipped_by": _COLON_SHIPPED,
    },
    # --- added 2026-08-27: the remaining queue, so NOTHING reports unverifiable ---
    #
    # Every marker below was verified ABSENT from its target before registration. That
    # order matters: the docstring's warning is that a wrong marker yields a false
    # STALE, and a false STALE prints a `git rm` for live work. Absent marker -> `live`
    # -> correct, and the marker flips the verdict the moment the fix lands.
    #
    # Marker names are the SYMBOL the fix would introduce, not prose. Prose gets
    # reworded; a constant/env-var name is what a reader greps for.
    "git-statechange-pipe-guard.spec.md": {
        "target": "hooks/bash-tail-buffering-guard.py",
        # Distinct from the sibling git-gating-pipe-guard spec's GIT_GATING marker:
        # that one is about a git command GATING a pipeline, this one about a
        # STATE-CHANGING git producer being SIGPIPE'd by an early-exiting filter.
        # CAVEAT: the spec permits a standalone hook instead of extending this file.
        # If installed standalone, this marker never appears and the spec reads `live`
        # forever — wrong, but in the SAFE direction (no false delete). Repoint the
        # target at install time.
        "marker": "STATE_CHANGING_GIT",
        "shipped_by": None,
    },
    "iam-unsatisfiable-condition.spec.md": {
        # Tier line says PreToolUse on Write/Edit, and this repo consolidates that
        # surface into one dispatcher rather than registering another hook there.
        "target": "hooks/write-edit-dispatcher.py",
        "marker": "UNSATISFIABLE_CONDITION",
        "shipped_by": None,
    },
    "mcp-truncation-signal-guard.spec.md": {
        # The spec's declared target IS the new hook file, so absence is evidence.
        "target": "hooks/mcp-truncation-signal-guard.py",
        "marker": "TRUNCATION_SIGNAL",
        "new_file": True,
        "shipped_by": "2026-08-29 install via /ship-hook — hook + tests + "
                      "registration; fire-rate replay 7.6% of sessions / "
                      "0.84% of results (under the ~10% gate)",
    },
    "script-file-bypasses-bash-guards.spec.md": {
        "target": "hooks/write-edit-dispatcher.py",
        "marker": "SCRIPT_CONTENT_SCAN",
        "shipped_by": None,
    },
    "staged-additions-ignored-files.spec.md": {
        "target": "hooks/staged-additions-guard.py",
        # The spec names this env var as the required override, so it is the fix's own
        # identifier rather than a marker invented here.
        "marker": "CLAUDE_GIT_ALLOW_IGNORED_UNDER_ADDED",
        "shipped_by": None,
    },
    "tail-guard-backgrounded-pytest.spec.md": {
        "target": "hooks/bash-tail-buffering-guard.py",
        # NOT the bare string "pytest" and NOT "VERDICT_COMMANDS": both already appear
        # in that file, so either would report a false STALE immediately. The marker
        # has to name the EXTENSION (test runners recognised only when backgrounded),
        # which is what the spec asks for.
        "marker": "BACKGROUNDED_TEST_RUNNERS",
        "shipped_by": None,
    },
    "tool-receipt-log.spec.md": {
        # Its own body says "STAGED — do NOT auto-install. Validated prototype, not yet
        # enabled (scope-discipline)." The marker does not authorize installing it; it
        # only makes the parked state MEASURED instead of unknown. The prototype body
        # currently sits at hooks/staged/tool-receipt-log.py, i.e. not installed.
        "target": "hooks/tool-receipt-log.py",
        "marker": "TOOL_RECEIPT",
        "new_file": True,
        "shipped_by": None,
    },
    # --- added 2026-08-27: two specs that existed ONLY in the ~/.claude local arc ---
    #
    # Both were staged into `hooks/staged/` on a checkout that is 278 commits ahead of
    # origin/main and drains only via separate PRs, so neither ever reached main. For 24
    # and 29 days respectively they were invisible to CI, to every other checkout, and
    # to THIS tool — which is the precise gap the tool exists to close. The new
    # TestEverySpecIsVerifiable invariant is what surfaced them.
    "org-guard-read-write-discrimination.spec.md": {
        "target": "hooks/bash-security-guard.py",
        # HALF of this spec already shipped: the read/write discriminator on `--repo`
        # is live (measured 2026-08-27 — 6/6 read forms allowed, 3/3 writes blocked).
        # So the marker MUST name the UNSHIPPED half, the approval mechanism. Marking
        # the shipped half would report STALE and print a `git rm` for live work — the
        # exact false-positive this tool's docstring warns about.
        "marker": "ORG_WRITE_APPROVAL",
        "shipped_by": None,
    },
    # --- added 2026-08-29 -------------------------------------------------------
    "tail-buffering-autorewrite-coverage.spec.md": {
        "target": "hooks/bash-tail-buffering-guard.py",
        # NOT "sed -n" or anything from the existing v4/v5 rewrite path — the guard
        # already auto-rewrites tail/grep (v4) and head (v5), so any string from the
        # current implementation would report a false STALE immediately. The marker
        # names the EXTENSION the spec asks for (broadened coverage of shapes that
        # today fall back to a block, gated on the spec's historical-replay
        # requirement). Verified absent from the target on origin/main 2026-08-29.
        # The installer must introduce this symbol when the extension ships.
        "marker": "AUTOREWRITE_COVERAGE",
        "shipped_by": None,
    },
    # TOMBSTONE. `verdict-command-position-anchoring.spec.md` was arc-only and is now
    # FULLY OBSOLETE: both of its defects shipped into bash-tail-buffering-guard as
    # `_verdict_at_command_position` (Defect A — whose docstring cites this spec's own
    # 2026-08-03 measurement and calls it "a RECURRENCE, not a new class") and
    # `_is_backgrounded` (Defect B). It was deleted from the arc rather than preserved.
    # The entry stays so that if the spec is ever re-staged from an old checkout, this
    # tool reports it STALE on the first run instead of a session re-deriving shipped
    # work. An entry whose spec file is absent is skipped, so this costs nothing.
    "verdict-command-position-anchoring.spec.md": {
        "target": "hooks/bash-tail-buffering-guard.py",
        "marker": "_verdict_at_command_position",
        "shipped_by": "shipped before 2026-08-27 as _verdict_at_command_position "
                      "(Defect A) + _is_backgrounded (Defect B); spec was arc-only and "
                      "fully obsolete on discovery, deleted not preserved",
    },
}

TYPE_RE = re.compile(r"^\*\*Type\*\*:\s*(.+)$", re.MULTILINE)


def find_repo_root(start=None):
    p = pathlib.Path(start or __file__).resolve()
    for cand in [p] + list(p.parents):
        if (cand / "hooks").is_dir() and (cand / "skills").is_dir():
            return cand
    return pathlib.Path.home() / ".claude"


def prior_deletions(root, spec_name):
    """Commits that DELETED this spec path before, newest first.

    A staged spec that was deliberately removed and is now back is a distinct condition
    from stale/live/unverifiable, and the one the tool was blindest to. Measured
    2026-08-27: `org-guard-read-write-discrimination.spec.md` was deleted 2026-08-15 as
    already-shipped (0c9f5e56, "#2009"), whose own message warned that keeping a shipped
    spec "invites a second implementation" — and 12 days later it was re-added from a
    pre-deletion remnant found in a diverged local checkout, described in the PR as a
    spec that "never reached origin/main".

    A file's presence in one checkout is not evidence about its history in another. This
    is the cheap mechanical check that settles it.
    """
    rel = "hooks/staged/%s" % spec_name
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "--all", "--diff-filter=D",
             "--format=%h\t%ad\t%s", "--date=short", "--", rel],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    rows = []
    for line in out.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            rows.append(tuple(p.strip() for p in parts))
    return rows


def audit(root):
    """Return (stale, unverifiable, live) lists of spec names."""
    staged = root / "hooks" / "staged"
    stale, unverifiable, live = [], [], []
    if not staged.is_dir():
        return stale, unverifiable, live
    for spec in sorted(staged.glob("*.spec.md")):
        decl = MARKERS.get(spec.name)
        if not decl:
            unverifiable.append((spec.name, "no marker declared in staged-spec-staleness.py"))
            continue
        target = root / decl["target"]
        if not target.exists():
            # A spec whose target IS THE NEW FILE it proposes can be verified after
            # all: an absent target means the file was never created, i.e. the fix has
            # NOT shipped. That is `live`, not `unverifiable`.
            #
            # Without this, every new-hook spec is permanently unknown — and
            # "unverifiable" is how this queue grew to 11 specs of which 4 had already
            # shipped. `new_file` must be declared explicitly, so a TYPO in an
            # existing-file target still reports unverifiable rather than silently
            # reading as live.
            if decl.get("new_file"):
                live.append((spec.name, decl["target"], decl["marker"]))
            else:
                unverifiable.append((spec.name, f"target missing: {decl['target']}"))
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        if decl["marker"] in text:
            stale.append((spec.name, decl["target"], decl["marker"], decl.get("shipped_by")))
        else:
            live.append((spec.name, decl["target"], decl["marker"]))
    return stale, unverifiable, live


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None, help="repo root (default: autodetect)")
    ap.add_argument("--quiet", action="store_true", help="only print on failure")
    a = ap.parse_args()
    root = pathlib.Path(a.root) if a.root else find_repo_root()

    stale, unverifiable, live = audit(root)

    readded = []
    for spec in sorted((root / "hooks" / "staged").glob("*.spec.md")) if (
            root / "hooks" / "staged").is_dir() else []:
        dels = prior_deletions(root, spec.name)
        if dels:
            readded.append((spec.name, dels))
    if readded:
        print("STAGED-SPEC RE-ADDED — %d spec(s) previously DELETED and now present:"
              % len(readded))
        for name, dels in readded:
            print("  RE-ADDED  %s" % name)
            for sha, date, subject in dels[:2]:
                print("            deleted by %s (%s) %s" % (sha, date, subject[:96]))
            print("            ACTION: read that commit's rationale before treating this "
                  "as pending work. A spec deleted as already-shipped that is back "
                  "invites a SECOND implementation of a shipped fix.")

    if stale:
        print("STAGED-SPEC STALENESS — %d spec(s) whose fix already shipped:" % len(stale))
        for name, target, marker, by in stale:
            print("  STALE  %s" % name)
            print("         target %s already contains %r" % (target, marker))
            if by:
                print("         shipped by %s" % by)
            print("         ACTION: git rm hooks/staged/%s" % name)
    for name, why in unverifiable:
        print("  note   %s — unverifiable (%s)" % (name, why))
    if not a.quiet and live:
        for name, target, marker in live:
            print("  live   %s — %r absent from %s (fix not shipped)" % (name, marker, target))
    if not stale and not a.quiet:
        # Say UNKNOWN, not OK, when specs have no marker. The exit code deliberately
        # stays 0 (silence beats a false delete, per the module docstring) and
        # healthcheck 5e keys on it — but the SUMMARY LINE is what a human reads, and
        # "OK — 0 live, 11 unverifiable" is how this queue reached 11 specs, four of
        # which had ALREADY SHIPPED. Two were self-declared installed in their own
        # bodies; two were the same hazard staged twice, 15 days apart, by sessions
        # that could not see each other. Same shape as "0 misaligned of 0 found
        # prints as PASS": the tool was honest and the headline was not.
        if unverifiable:
            print("staged-spec staleness: UNKNOWN — %d live, %d UNVERIFIABLE "
                  "(no marker declared). This is NOT a clean bill: an unverifiable "
                  "spec may already be shipped. Declare a marker in MARKERS above "
                  "for each one." % (len(live), len(unverifiable)))
        else:
            print("staged-spec staleness: OK — %d live, 0 unverifiable" % len(live))

    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
