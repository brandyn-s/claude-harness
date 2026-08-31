#!/usr/bin/env bash
# C8 trigger fixture: GNU-only shell idioms that fail on macOS BSD.
# Intentional bad code — flagged by audit-skill's BSD-divergence check.

# Line below: real `sed -i` without BSD backup arg (no leading #)
sed -i s/foo/bar/ some-file.txt

# Line below: real `date -d` (GNU-only; macOS uses `date -v`)
yesterday=$(date -d "yesterday" +%Y-%m-%d)

# Line below: real `xargs -r` (GNU --no-run-if-empty; BSD doesn't have it)
find . -name '*.tmp' | xargs -r rm

echo "$yesterday"
