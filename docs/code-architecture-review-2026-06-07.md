# Code Architecture Review — 2026-06-07

Scope: the enforcement layer of `claude-config` — the hook subsystem (~24k LOC),
plus `bin/`/`scripts/` tooling and the installer. Method: five parallel deep
reviews of the security guards, session lifecycle, sync/converters, tooling, and
routing hooks; every headline finding was reproduced against the live code
before a fix was written. Baseline health was already strong (769 hook tests
passing, clean `validate-hook-paths`, disciplined CI); this review targeted the
gaps the green suite hid — several *because* tests asserted a self-invented
contract instead of the real one.

## Systemic patterns
Three root causes explained most of the high-severity findings:

1. **Wrong hook output contract, locked in by tests.** Hooks signalled
   block/warn with `print({"result": ...})` + exit 0 instead of the Claude Code
   contract (exit 2, or `systemMessage`/`hookSpecificOutput.permissionDecision`).
   The harness ignored the unknown shape, so the guard looked active and its
   test passed while it did nothing.
2. **Guards that only inspect `str` / `Write` / `Edit` shapes** silently no-op'd
   on dict/list MCP results and `MultiEdit` payloads — the now-common shapes.
3. **Substring / quote-stripping as the matching primitive** created bypasses
   (quoted credential paths, `git -C`, `gh api` org writes) and false positives
   (`404` inside `1404`).

## Fixed (with regression tests)

### CRITICAL
- **`atomic_write` concurrent-write crash + non-durability** (`hooks/atomic_write.py`).
  Fixed temp name caused collisions (measured 132/300 failures under 6 threads);
  no fsync risked truncated targets. → unique pid+uuid temp name, flush+fsync,
  dir fsync, `unlink(missing_ok=True)`.
- **Output trimmer emitted invalid JSON** (`hooks/mcp-output-trimmer.py`). Generic
  path byte-sliced serialized JSON mid-object into `updatedMCPToolOutput`. →
  JSON-aware reduction that stays valid and within `MAX_OUTPUT_CHARS`; structured
  trimmers now enforce the char cap.
- **Quoted-path credential bypass** (`hooks/bash-security-guard.py`). `cat ".env"`
  / `cat "$HOME/.ssh/id_rsa"` passed because quoted content was stripped before
  matching. → strong read+path signal strips quote *characters*, keeping the path.

### HIGH
- **`git -C <protected> push/commit` bypassed all repo-scoped guards** → added
  `_normalize_git_command` + `_resolve_git_cwd` (parse `-C`/`--git-dir`/`--work-tree`).
- **`gh api --method POST /repos/example-technologies/...`** bypassed the org guard
  → match REST paths, treat `--method`/`-X` as writes.
- **`rm -rf "/"` / `'/'` / `//`** evaded the destructive pattern → dedicated raw
  pattern anchored at a command position (no commit-message false-block).
- **Secret env var in curl/wget request body** (`-d`/`-F`) → new exfil pattern
  (auth *headers* intentionally still allowed).
- **`xxd`/`od`/`base64` readers of `.ssh` keys** bypassed (over-broad `GIT_SSH_OK`
  matched `ssh` inside `.ssh`) → readers added, `GIT_SSH_OK` anchored at command
  position.
- **`MultiEdit` bypassed config-guard self-protection and memory-write-guard**
  → both scan `edits[].new_string`.
- **`result-injection-guard` skipped dict/list MCP results** → uses
  `hook_input.tool_response_str()`.
- **`skill-alias` "block" paths didn't block** (exit 0 + `{"result":...}`) →
  exit 2 + stderr reason.
- **session-stop dirty-repo warning never surfaced** (dead `{"result":"warn"}`)
  → `systemMessage`.
- **Auto-merge marker written non-atomically** (`post-merge-sync.py`), undermining
  the lost-commits push-guard → routed through `atomic_write`; misleading test
  tightened.
- **`git_lock` never existed**, so the episodic-memory "lock" was a no-op →
  shipped `hooks/git_lock.py` (O_EXCL file lock with timeout + stale reclaim).
- **Strategic synthesis (45s call) under a 15s hook budget**, running before the
  config drain → timeout lowered to 8s, moved to run last after
  `_apply_pending_config`/manifest.
- **Installer `wire_hooks` crashed** on multi-token matchers (`int('Read')`) for
  both install presets; `run-hook` was git-tracked non-executable and never
  installed → parse-from-right, dedup all hooks, ship+chmod `run-hook`, set the
  exec bit.

### MEDIUM
- **session manifest date** built from UUID fragments → only accept real
  `YYYY-MM-DD`.
- **context-monitor** state keyed by project (concurrent-session conflation,
  torn-read reset) → per-session state file via `atomic_write`.
- **post-failure-guide** substring over-fire (`404`/`None`) → word-boundary
  match; identifier keys case-sensitive.
- **pdf/cklb/nessus converters** lacked the crash-safety wrapper → added.
- **`CODE_SEARCH_VOCAB_OK=1`** override advertised but unimplemented → honored.

### LOW
- CI skill-rubric messaging claimed "all S-tier / 13/13" while the rubric has 14
  checks and 4 skills are A-tier (13/14) → messaging corrected to the real gate.
- `hooks/README` listed `promise-checker` as StopFailure; it's a Stop hook → fixed.

## Deliberately deferred (documented, not changed)
- **`post-merge-sync` hardcodes `main`** (silently no-ops on `master`-default
  repos). The fix touches the `reset --hard` path, which has no behavioral tests;
  changing it without a temp-repo test harness risks the exact data-loss class
  the guard exists to prevent. The reset path's per-commit tree-diff safety check
  + backup ref were inspected and are sound. Recommend a follow-up that adds the
  temp-repo tests first, then default-branch detection.
- **Other blocking guards fail open on crash** (exit 0). Flipping
  worktree-enforcement / destructive-ops-guard to fail-closed is a behavior change
  that could block legitimate ops on a hook bug; left as a deliberate decision.
- **3 manifest semantic-drift warnings** (warn-only): `obsidian`/couchdb,
  `linear-status`/linear-server, `audit-skill`/tavily. Cosmetic `requires_tools`
  drift; no functional impact.

## Verification
`pytest hooks/test-hooks/` → 800 passed / 86 skipped (was 769/86; +31 regression
tests). `validate-hook-paths`, manifest `--check`, and the skill-rubric gate all
pass.
