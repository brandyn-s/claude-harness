#!/bin/bash
# Snapshot ~/.claude/projects transcripts to a durable path outside ~/.claude.
#
# WHY
#   Local transcripts are the AUTHORITATIVE record for every session-history,
#   scope and retrospective claim (rules/transcript-over-summary.md), and
#   /retro, /mega-distill and /mega-capture all depend on them.
#
#   They are protected today only by `cleanupPeriodDays: 36500`, and that
#   setting has an OPEN silent-failure bug: anthropics/claude-code#41458 —
#   a user ran 99999 continuously for two months (git-verified) and still lost
#   490 session JSONLs. One cause was patched in 2.1.203 and that incident
#   predates the fix, but the issue was never closed.
#
#   Measured 2026-08-01, before retention was raised: 2,177 transcripts, of
#   which 2,176 were under 30 days old and exactly ONE was older. Everything
#   before ~a month had already been swept.
#
#   This backup is the only control that does not depend on that mechanism.
#
# HOW
#   rsync --link-dest hardlinks unchanged files against the previous snapshot,
#   so each additional daily snapshot costs only what actually changed — a few
#   MB, not 1.9 GB. Transcripts are append-only, so a modified file lands as a
#   new inode and the older snapshot keeps its own version intact.
#
#   Deliberately NOT in a git repo: 1.9 GB of session content, some sensitive.
#   Deliberately NOT under ~/.claude: that is the directory being swept.
#   Deliberately NOT /tmp or ~/claude-scratch: both are non-durable per
#   rules/worktree-by-default.md.
set -uo pipefail

SRC="${CLAUDE_TRANSCRIPT_SRC:-$HOME/.claude/projects}"
DEST_ROOT="${CLAUDE_TRANSCRIPT_BACKUP:-$HOME/claude-transcript-backups}"
KEEP="${CLAUDE_TRANSCRIPT_KEEP:-30}"
STAMP="$(date +%Y-%m-%d)"
DEST="$DEST_ROOT/$STAMP"
LOG="$DEST_ROOT/backup.log"

log() { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$*" | tee -a "$LOG"; }

[ -d "$SRC" ] || { echo "FATAL: source $SRC does not exist" >&2; exit 2; }
mkdir -p "$DEST_ROOT" || exit 2

# newest existing snapshot becomes the hardlink base
PREV="$(find "$DEST_ROOT" -maxdepth 1 -type d -name '20*-*-*' 2>/dev/null | sort | tail -1)"
LINK_ARG=()
[ -n "$PREV" ] && [ "$PREV" != "$DEST" ] && LINK_ARG=(--link-dest="$PREV")

SRC_N=$(find "$SRC" -name '*.jsonl' -type f 2>/dev/null | wc -l | tr -d ' ')
log "START src=$SRC files=$SRC_N dest=$DEST prev=${PREV:-none}"

# `${arr[@]+"${arr[@]}"}` NOT `"${arr[@]}"`: macOS /bin/bash is 3.2, where
# expanding an EMPTY array under `set -u` is an unbound-variable ERROR (bash only
# made empty-array expansion safe in 4.4). LINK_ARG is empty in exactly two real
# cases — the FIRST run on a machine (no prior snapshot) and any SECOND run on the
# same day (PREV == DEST, so the guard above leaves it unset) — and both died here
# with `LINK_ARG[@]: unbound variable`, after the START line and before any OK, so
# the log showed a run that began and silently never completed.
#
# MEASURED 2026-08-12 on the deployed copy, 3 shapes: no prior snapshot -> rc=1;
# prior snapshot from an OLDER day -> rc=0; prior snapshot from the SAME day ->
# rc=1. The earlier prune test seeded `2026-01-0N` dirs, so PREV was always
# present AND different from DEST — the one shape that works — which is why a
# known-positive/known-negative pair still covered a single branch.
rsync -a --delete-excluded \
      --include='*/' --include='*.jsonl' --exclude='*' \
      ${LINK_ARG[@]+"${LINK_ARG[@]}"} "$SRC/" "$DEST/"
RC=$?
if [ $RC -ne 0 ]; then
  log "FATAL rsync exit=$RC"
  exit 1
fi

# Verify by COUNT, not by rsync's exit code. A backup nobody counted is a
# backup nobody has.
DST_N=$(find "$DEST" -name '*.jsonl' -type f 2>/dev/null | wc -l | tr -d ' ')
DST_SZ=$(du -sh "$DEST" 2>/dev/null | cut -f1)
APPARENT=$(du -sh --apparent-size "$DEST" 2>/dev/null | cut -f1 || echo "n/a")

if [ "$DST_N" -lt "$SRC_N" ]; then
  log "FAIL verification: src=$SRC_N dst=$DST_N (short by $((SRC_N - DST_N)))"
  exit 1
fi
log "OK   files=$DST_N size=$DST_SZ (apparent=$APPARENT) snapshots=$(find "$DEST_ROOT" -maxdepth 1 -type d -name '20*-*-*' | wc -l | tr -d ' ')"

# Prune oldest snapshots beyond KEEP. Conservative by design: the entire point
# of this script is retention, so it only ever prunes whole dated snapshots and
# never touches the newest one.
# NOT `mapfile`: macOS /bin/bash is 3.2 and has no mapfile. Under `set -u` the
# failure cascaded -- `mapfile: command not found` then `SNAPS: unbound variable`
# -- so the prune step never ran and snapshots grew without bound. It was
# invisible until the launchd agent logged stderr to a file (2026-08-12); an
# interactive run had never surfaced it, because the backup itself succeeds first
# and the script's own log line still printed OK.
SNAPS=()
while IFS= read -r d; do
  [ -n "$d" ] && SNAPS+=("$d")
done < <(find "$DEST_ROOT" -maxdepth 1 -type d -name '20*-*-*' | sort)

if [ "${#SNAPS[@]}" -gt "$KEEP" ]; then
  PRUNE_N=$(( ${#SNAPS[@]} - KEEP ))
  i=0
  while [ "$i" -lt "$PRUNE_N" ]; do
    old="${SNAPS[$i]}"
    i=$(( i + 1 ))
    [ "$old" = "$DEST" ] && continue
    log "PRUNE $old"
    rm -rf "$old"
  done
fi
exit 0
