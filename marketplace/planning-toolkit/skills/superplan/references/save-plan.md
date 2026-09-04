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

### Step 5a.1: SHA-256 plan attestation

Immediately after writing the plan file (before the git commit), compute and persist its SHA-256:

```bash
(cd ~/Documents/knowledge-base/plans && sha256sum YYYY-MM-DD-<slug>.md) \
  > ~/Documents/knowledge-base/plans/YYYY-MM-DD-<slug>.md.attestation
```

The output format is `<sha>  <basename>` (e.g., `abc123def  2026-06-14-plan.md`), which matches the format written by supergoal's parse_plan.py at bootstrap time.

The attestation locks the plan against mid-loop tamper. supergoal's verification hook checks the plan's mtime each turn; when mtime has changed, it re-hashes and aborts the loop with `plan-tampered` if the hash differs. Without this, a silently-mutated plan would let the prior-arc ledger lie.

Intentional updates: stop supergoal, re-run superplan to update the plan (which re-attests), re-invoke supergoal. Do not edit the plan file directly during an active loop.

The mtime-keyed cache avoids re-hashing on every turn — see `${CLAUDE_PLUGIN_ROOT}/skills/supergoal/references/verification-hook.md` Step 1 for the full procedure.

### Step 5a.2: Plan template — required new sections

Beyond the existing Goal / Constraints / Steps / Verification structure, plans must now include:

**`execution_budget`** — a YAML block that caps repair cycles, full-suite runs,
and live probes and routes nonblocking findings to backlog. It prevents a green
vertical slice from expanding into open-ended review or validation work.

**`### Metric Commands`** — explicit code block of shell commands whose output (final line matching `^METRIC <name>=<value>`) is the authoritative measurement. supergoal parses these; conflating with `Verification:` legacy is still supported but emit the explicit section if possible.

**`### Guard Commands`** — code block of commands that must continue to pass (existing tests, lints). Separate from metric — guards catch regressions, metrics drive progress; conflating them lets the model succeed by regressing tests.

**`### Artifact Probe`** — code block of commands that observe the *artifact* (not the metric). Different surface area. Run only at exit as a Goodhart probe — a metric can pass while the artifact is junk. Without this section, supergoal warns and disables the probe; metric-gaming becomes undetectable.

**`### Forbidden Actions`** — list of tool-call patterns the agent must NOT take during the loop. supergoal's hook can be extended to refuse these. Examples:
- `Bash(rm *)`
- `Edit(file_path=/etc/*)`
- `Bash(git push --force *)`

If omitted, supergoal warns and disables the policy axis.

**Falsifier format is a parser contract:** `## Falsifiers` must be markdown
LIST ITEMS — a table parses as zero falsifiers and `parse_plan.py` exits 20
(the dry-run below catches it pre-commit).

**Readiness self-check (supergoal-bound plans).** Nothing verifies superplan's OWN output matches this template, so a deviating plan (prose `## Verification` instead of an executable `### Metric Commands` block; bolded `**Demo:**`; sentence-final baseline) ships clean and fails only at supergoal parse-time. Before declaring ready, dry-run: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/supergoal/scripts/parse_plan.py <plan> --state-dir /tmp/claude/sp-check/ --reset` — exit 0 with `metric_commands: N≥1` = ready; exit 20 = fix the named section. The metric block must RUN as-is in the not-yet-built state (guard with `[ -f X ] &&`) and print a real `METRIC name=<number>`, not a `<placeholder>`.

**A metric that reads a remote-tracking ref MUST `git fetch` inside the metric block.** `git -C "$REPO" show origin/main:<path>` reads the LOCAL remote-tracking ref, so after a PR merges the metric reports the world as of the last unrelated fetch. This survives plan authoring structurally: at baseline the true value and the stale-ref value agree, so a metric verified only at baseline cannot reveal the staleness bug. Emit the fetch for every repo the block reads, and treat "verified at baseline" as unverified for any metric whose source is a ref (`references/run-history.md`).

### Step 5a.3: Plan-pattern library write (on successful supergoal exit only)

When a downstream supergoal run exits with `success`, the terminal-doc writer extracts a reusable pattern template and writes it to `~/Documents/knowledge-base/plan-patterns/<pattern-slug>.md`. See `${CLAUDE_PLUGIN_ROOT}/skills/supergoal/references/plan-pattern-library.md` (absolute path to the sibling supergoal skill's references/ directory) for the template schema. Phase 2e reads from this dir for the next plan.

### Step 5a.4: Parallel-dispatch routing recommendation

If the plan has ≥3 vertical slices that are independent at the file level (no shared mutable state between slices), Step 5b's execution-path recommendation should suggest **Task-tool parallel dispatch** instead of sequential `/supergoal`. Sub-tasks each get **scoped context** (their slice + the relevant plan steps), NOT the full plan — context inheritance corrupts subagent reasoning and explodes token cost.

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
