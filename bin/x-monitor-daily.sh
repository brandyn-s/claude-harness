#!/bin/zsh
# x-monitor daily sweep (launchd: com.example.x-monitor-daily).
# Sequence: full sweep over a 2-day window (overlap is safe — delta-flagging
# dedupes against seen-state), then an engagement recheck on tracked negative
# findings (velocity alerts), then a refreshed 7-day consolidated collection.
# Each stage fails soft and the script continues — a transient API error on
# the sweep must not suppress the recheck. Exit is non-zero if ANY stage
# failed so launchctl's last-exit-code surfaces it.
set -u
X="$HOME/.claude/bin/x-monitor.py"
FROM=$(date -v-2d +%F)
rc=0

caffeinate -i python3 "$X" --mode full --from-date "$FROM" || rc=1
caffeinate -i python3 "$X" --mode recheck || rc=1
caffeinate -i python3 "$X" --mode consolidate --days 7 || rc=1

exit $rc
