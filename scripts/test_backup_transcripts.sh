#!/bin/bash
# Contract test for bin/backup-transcripts.sh on macOS /bin/bash 3.2.
#
# WHY ALL THREE SHAPES: the prior test seeded a `2026-01-0N` snapshot, so PREV was
# always present AND different from DEST — the one hardlink shape that works. Both
# the FIRST run on a machine (no prior snapshot) and any SECOND run on the same day
# (PREV == DEST) leave LINK_ARG empty, and expanding an empty array under `set -u`
# is an unbound-variable error in bash 3.2. Measured 2026-08-12 on the deployed
# copy: 2 of those 3 shapes exited 1 after logging START and before any OK, so the
# scheduled agent showed runs that began and never completed.
#
# Asserts the OUTCOME (an OK line + the file count) rather than the exit code
# alone, because the pre-fix script also reached exit 0 in some shapes while its
# prune step had failed.
set -u

SCRIPT="${1:-$(cd "$(dirname "$0")/.." && pwd)/bin/backup-transcripts.sh}"
FAILURES=0
TMPROOT="$(mktemp -d "${TMPDIR:-/tmp}/backup-test.XXXXXX")"
trap 'rm -rf "$TMPROOT"' EXIT

echo "testing: $SCRIPT"
echo "bash:    ${BASH_VERSION}"

# One case: seed shape -> expect an OK line, the right file count, and no stderr.
run_case() {
  label="$1"; seed="$2"; keep="${3:-30}"; want_snaps="${4:-}"
  root="$TMPROOT/$(echo "$label" | tr ' ' '_')"
  src="$root/src"
  mkdir -p "$root" "$src/proj"
  printf '{"a":1}\n' > "$src/proj/one.jsonl"
  printf '{"b":2}\n' > "$src/proj/two.jsonl"
  today="$(date +%Y-%m-%d)"
  case "$seed" in
    none)  : ;;
    older) mkdir -p "$root/2026-01-01" ;;
    same)  mkdir -p "$root/$today" ;;
    many)  for i in 1 2 3 4 5; do mkdir -p "$root/2026-01-0$i"; done ;;
  esac

  CLAUDE_TRANSCRIPT_SRC="$src" CLAUDE_TRANSCRIPT_BACKUP="$root" \
    CLAUDE_TRANSCRIPT_KEEP="$keep" \
    /bin/bash "$SCRIPT" >"$root/out.txt" 2>"$root/err.txt"
  rc=$?

  ok_lines=$(grep -c 'OK   files=' "$root/backup.log" 2>/dev/null || true)
  copied=$(find "$root/$today" -name '*.jsonl' -type f 2>/dev/null | wc -l | tr -d ' ')
  err_bytes=$(wc -c < "$root/err.txt" | tr -d ' ')
  snaps=$(find "$root" -maxdepth 1 -type d -name '20*-*-*' 2>/dev/null | wc -l | tr -d ' ')

  bad=""
  [ "$rc" = "0" ]        || bad="$bad rc=$rc"
  [ "$ok_lines" = "1" ]  || bad="$bad ok_lines=$ok_lines"
  [ "$copied" = "2" ]    || bad="$bad copied=$copied"
  [ "$err_bytes" = "0" ] || bad="$bad stderr=${err_bytes}B"
  if [ -n "$want_snaps" ] && [ "$snaps" != "$want_snaps" ]; then
    bad="$bad snapshots=$snaps(want $want_snaps)"
  fi

  if [ -n "$bad" ]; then
    echo "  FAIL  $label —$bad"
    [ -s "$root/err.txt" ] && sed 's/^/          /' "$root/err.txt" | head -3
    FAILURES=$((FAILURES + 1))
  else
    echo "  ok    $label (snapshots=$snaps)"
  fi
}

# The three LINK_ARG shapes. `none` and `same` are the ones that regressed.
run_case "first run, no prior snapshot" none
run_case "prior snapshot from an older day" older
run_case "second run on the SAME day" same

# Prune still bounded, and today's snapshot always survives.
run_case "prune beyond KEEP" many 2 2

echo
if [ "$FAILURES" -eq 0 ]; then
  echo "PASS — all shapes"
  exit 0
fi
echo "FAIL — $FAILURES case(s)"
exit 1
