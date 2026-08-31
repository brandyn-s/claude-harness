# Dirty Tree Discovery — Script and Report Example

Consulted from Phase 1's Dirty Tree Discovery. The bucket-classification
table and tempo policy live in SKILL.md; this file holds the discovery
script and a worked report example.

## Discovery script

```bash
# Source local clone paths from the unified repo map (single source of truth).
# Skips entries marked "(no local clone)" or "(clone if needed)" — those have
# no $HOME path in column 3.
REPO_MAP="${CLAUDE_PLUGIN_ROOT}/skills/_shared/repo-map.md"
# git -C needs Windows-form paths on a Git-Bash host: $HOME is the MSYS form
# (/c/Users/...), which `git -C` rejects with "fatal: cannot change to
# '/c/Users/...'" (exit 128) — even though the bash `[ -d ]` test below
# accepts it. cygpath -m converts $HOME to C:/Users/... . Without this,
# every `git -C "$repo"` fails and the scan silently reports every repo
# clean (2026-05-31 incident: ~/.claude shown clean while 12 files dirty).
# On macOS/Linux cygpath is absent and the fallback leaves $HOME unchanged.
HOME_WIN="$(cygpath -m "$HOME" 2>/dev/null || echo "$HOME")"
# Build the array with while-read: `mapfile` is a bash-4+ builtin absent from
# zsh (the macOS Bash tool shell) and stock macOS bash 3.2 — there the array
# stays empty and the scan silently reports every repo clean.
REPOS=()
while IFS= read -r repo_path; do
  REPOS+=("$repo_path")
done < <(grep -oE '`\$HOME/[^`]+`' "$REPO_MAP" | tr -d '`' | sed "s|\$HOME|$HOME_WIN|" | sort -u)

for repo in "${REPOS[@]}"; do
  [ -d "$repo/.git" ] || continue  # skip if not cloned locally
  count=$(git -C "$repo" rev-list --count --since="90 days ago" HEAD 2>/dev/null || echo 0)
  if [ "$count" -le 4 ]; then tempo="DORMANT"
  elif [ "$count" -le 14 ]; then tempo="MODERATE"
  else tempo="ACTIVE"; fi
  ahead=$(git -C "$repo" log --oneline origin/main..HEAD 2>/dev/null | wc -l)
  echo "=== $(basename "$repo") === [$tempo: $count commits/90d, $ahead unpushed]"
  git -C "$repo" status --short 2>&1 || echo "(not a repo)"
done
```

To add or remove a repo from dirty-tree discovery, edit
`_shared/repo-map.md` — do NOT hard-code paths in the skill.

## Phase 1 report example (all discovery axes)

```
=== Ready to merge (green CI, no auto queued) ===
  1. [PR-READY]    mcp-servers #298   bump trivy-action              author: dependabot
  2. [PR-READY]    mcp-infra #298     bump actions/github-script     author: dependabot
  3. [PR-READY]    mcp-servers #294   revert SESSION_SECRET          author: me

=== Stuck auto-merge (conflicts with main) ===
  4. [PR-CONFLICT] ckb #236  capture: ingest→audit pipeline   queued 11d   author: me
  5. [PR-CONFLICT] ckb #254  docs(byoc): zero-standing-access queued 6d    author: me

=== Failing PR checks ===
  6. [PR-FAIL]     obsidian-infra #3  fix(deps): bump PyJWT (CVE)    [Python Test, Python Lint]
  7. [PR-COSMETIC] mcp-servers #300   bump codeql-action             [dependabot workflow-permission — merge anyway]

=== Awaiting my review (others' PRs) ===
  8. [PR-REVIEW]   mcp-servers #259   Add example-falcon MCP server  author: dylan   18d old
  9. [PR-REVIEW]   mcp-infra #286     Add example-falcon to services author: dylan   18d old

=== Failed commit CI on main (last 7 days) ===
 10. [CI]          mcp-servers main@b942dd3  schedule  [Catalog Drift]   2026-03-23

=== Stale branches (merged, deletable) ===
 11. [BR]          claude-config 55 branches (52 merged into main)

=== Dirty trees (uncommitted work) ===
 12. [DIRTY]       mcp-servers (MODERATE 8/90d, 0 unpushed)   3 modified   prior-session-artifact (2 distill entries, 1 hook update)
 13. [DIRTY]       mcp-infra (DORMANT 2/90d, 1 unpushed)      1 modified   ask (Terraform change in services/)

No action: example-compliance-repo, knowledge-base

Which to fix? (enter number, 'all' for sequential, 'ready' for just PR-READY bucket,
                'branches' to clean stale branches, 'review' to triage PR-REVIEW only,
                or 'dirty' to ship pending artifacts and ask on in-progress work)
```
