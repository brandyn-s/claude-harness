# Step 5a: Save plan to disk and commit (mandatory)

The save+commit+PR mechanics for /superplan Step 5a. Always run immediately
after Step 4 readback succeeds — do not defer.

## Procedure

1. Create the output directory if it doesn't exist:
   `mkdir -p "$HOME/Documents/knowledge-base/plans"`

2. Generate a topic slug from the task description (lowercase, hyphens,
   max 50 chars, ASCII).

3. Write the full plan — including the `## Session Context` block from
   Phase 4c if present — to
   `$HOME/Documents/knowledge-base/plans/YYYY-MM-DD-<slug>.md`.
   Use today's date in YYYY-MM-DD format.

4. **Readback verification**: re-read the saved file and confirm it contains
   the plan's Goal heading and final step. A successful Write does not
   guarantee the bytes are on disk (encoding, partial writes, hook interference).

5. **Commit and push via standard git+PR flow.** Saving to disk alone is not
   enough — the session-start auto-checkpoint hook will absorb uncommitted
   plan files onto a `checkpoint/<timestamp>` branch that is never merged to
   main, leaving the plan invisible from a fresh clone or a `main`-anchored
   next session. Run from inside `~/Documents/knowledge-base/`:

   ```bash
   cd ~/Documents/knowledge-base
   git checkout -b plan/<slug>
   git add plans/YYYY-MM-DD-<slug>.md
   # If Phase 3.5 ran, also stage the baseline artifact
   if [ -f "plans/YYYY-MM-DD-<slug>-baseline.md" ]; then
     git add plans/YYYY-MM-DD-<slug>-baseline.md
   fi
   git commit -m "plan: <short topic description>"
   git push -u origin plan/<slug>
   gh pr create --title "plan: <short topic description>" --body "Plan file for <topic>. Auto-merging."
   gh pr merge --auto --squash --delete-branch
   ```

**Worktree-persistence corollary (2026-08-24):** if Step 5 ran from a WORKTREE
(dirty primary checkout), the merged plan exists on origin/main but NOT in the
primary checkout's working tree — and supergoal resolves the plan by local
path. After the merge verifies, materialize it:
`git -C ~/Documents/knowledge-base show origin/main:plans/<file> > plans/<file>`
(untracked copy; verify its SHA against the attestation).

If the path conflicts with an existing plan file (same date + slug), append
`-v2`, `-v3`, etc. Do not overwrite without confirming with the user.

## Failure modes

`/superplan` runs in main thread; the `worktree-enforcement.py` hook does not
block main-session writes — it only enforces on subagent writes — so the
realistic failures are environmental, not policy-driven:

- **Path translation**: forward-slash absolute paths work in Git Bash and
  Python; if a hook or tool rejects the path, retry with the `C:\...` form.
- **Permissions / disk full**: capture the raw error, surface to the user, and
  offer a fallback path under the user's home directory.
- **Readback mismatch**: if the readback shows truncated or wrong content, do
  NOT claim the plan is saved — re-write and re-verify, or surface the failure.
- **Auto-checkpoint absorption**: if Step 5 commit is skipped, session-start
  auto-checkpoint commits the file onto `checkpoint/<timestamp>` branch with
  no PR path. Plan becomes invisible from `main` (recoverable via
  `git log --all -- plans/<file>` then
  `git checkout <branch> -- plans/<file>`, but recovery costs 5-10 turns).
  Always run Step 5 immediately after Step 4 readback succeeds.

## INCIDENT 2026-05-03→04

/superplan Step 5a saved `plans/2026-05-03-code-search-recall-ceiling-and-agentic-retrieval.md`
to disk at session end. Plan was never committed. Session-start
auto-checkpoint absorbed it onto `checkpoint/20260503161206`. Today's session
resumed with `/superplan <plan path>`, `Read` returned "File does not exist".
Recovery via `git log --all` + `git checkout checkpoint/... -- plans/...`
cost ~5 turns. Fix shipped in this same /retro: Step 5 (commit+PR) is now
mandatory.
