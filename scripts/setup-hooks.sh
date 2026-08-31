#!/usr/bin/env bash
# One-time activation of .githooks/ for this clone.
# Run after `git clone`. Idempotent — safe to re-run.
set -e
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
echo "Activated .githooks/ as the git hooks source."
echo
echo "Hooks installed:"
for f in .githooks/*; do
  [ -f "$f" ] && [ "$(basename "$f")" != "README.md" ] && echo "  $(basename "$f")"
done
