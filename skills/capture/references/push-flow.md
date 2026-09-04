# Capture push flow — conditional and recovery procedures

Relocated verbatim from `skills/capture/SKILL.md` on 2026-09-04 (docs/skill-cap-decisions.md): the
macOS-only Step 4c and the Step 5 item-4 push playbook are procedures a routine capture never reaches.
The body keeps a pointer at each site.

## Step 4c

**Step 4c: Persist credential identifiers to Keychain (conditional)**

Fires when EITHER (1) this session surfaced a **credential identifier set** — an
app reg / API client whose IDs were explicitly named ("App ID:", "Client ID:",
"Tenant ID:", "Object ID:", a `<PREFIX>_<ROLE>` env-var family), or the user
asked to store params; OR (2) the **incomplete-triplet sweep** (path 2) finds a
Keychain secret missing its sibling IDs. Most captures skip this step.

macOS only — guard `[ "$(uname)" = Darwin ]`, else skip with a note.

**NON-SECRET IDENTIFIERS ONLY.** Client/app/tenant/directory/object/SP IDs,
account numbers, endpoints. **NEVER auto-store a secret VALUE** — if a secret is
referenced but absent, report it must be added manually (`security
add-generic-password -U -a NAME -s NAME -w`, no-echo prompt). **NEVER store
error-message IDs** — AADSTS700016 "client ID … not found" / "tenant not
registered" are FAILED-auth IDs; the value's CONTEXT must read as an own/working
credential, not an error.

Detection — gather candidates from BOTH paths, then confirm ONCE:
1. **Label-adjacency** (per-session, high precision): extract IDs explicitly
   named this session as `(role, value)`. Do NOT blind-scan every GUID —
   example / other-tenant / transient IDs are false positives.
2. **Incomplete-triplet sweep** (gap-driven, provenance-independent): from
   `security dump-keychain 2>/dev/null | grep '"acct"'` (names only), for each
   `*_SECRET`/`*_API_KEY` the expected siblings are the same prefix with
   `_CLIENT_ID`/`_TENANT_ID` (or `_API_ID`); flag any MISSING. For each gap,
   check whether the session (or the curated IDs memory it cites) surfaced a
   value for that prefix's app/tenant — if so, propose filling it. Catches IDs
   written without an "ID:" label (e.g. `client: <guid>`) that path 1 misses.

Write:
3. **Derive** `<PREFIX>_<ROLE>` names, reusing the sibling secret's prefix so the
   triplet (tenant + client + secret) co-locates. **Idempotency**: `security
   find-generic-password -s NAME -w` — equal → SKIP, absent → NEW, diff → UPDATE.
4. **Confirm once** via `AskUserQuestion`: the union of both paths' candidates as
   `KEY = value (NEW | UPDATE old→new)`. If declined, write nothing.
5. **Write** approved: `security add-generic-password -U -a NAME -s NAME -w VALUE
   -j "<source>; non-secret id"` — `-w VALUE` in argv OK for non-secret IDs ONLY,
   NEVER a secret (see `platform-constraints.md` wide-process-listing). Verify +
   report stored / updated / skipped.

**Skip when**: no credential set surfaced AND the sweep finds no fillable gap.
Silent when it does not fire.

## Step 5 push playbook

These paragraphs sit inside Step 5 item 4 ("Run the canonical compiler, then push"), after the
four-call git flow and the worktree `--delete-branch` note.

**PREVENT the DIRTY case instead of resolving it — do this BEFORE `git checkout -b`.**
The conflict below is avoidable, because `generated/`, README.md and Home.md are
DISPOSABLE build products (the KB's own CLAUDE.md says so), so there is nothing to
merge on them — only to regenerate. Sequence:

```bash
cd ~/Documents/knowledge-base && git fetch origin --quiet
git rev-list --count main..origin/main      # behind?  0 = branch now
git diff --name-only main..origin/main      # what do the incoming commits touch?
```

If behind by >0: check whether the incoming set includes `generated/`, README.md or
Home.md. **Only if it does** must you `git checkout -- generated/ README.md Home.md`
to drop your rebuilt artifacts — a fast-forward refuses only when it would overwrite
a dirty file it actually touches, so when the incoming commits are (say) `plans/`-only
your build output is not in the way and there is nothing to discard. Then
`git merge --ff-only origin/main`, THEN branch, THEN re-run `kb.py build` so every
artifact is generated from the MERGED topic set. Your authored topic edits survive
untouched as working-tree dirt across the fast-forward — but confirm via the
`git diff --name-only` above that no topic YOU edited is in the incoming set; if one
is, resolve that file by hand rather than fast-forwarding over it.

Doing this proactively costs 3 read-only commands; doing it reactively costs a
worktree, a `--theirs` checkout, a rebuild, a merge commit, and a re-armed PR
(both shapes on record: `references/run-history.md`).

**If the merge conflicts on a TOPIC file you appended to** (a parallel session
captured to the SAME topic the same day): this is an append-vs-append conflict,
not a generated-file one. Resolve by KEEPING BOTH SIDES: both dated H2 entries
(HEAD's then origin/main's, in hunk order, blank line between), and both sides'
`Current understanding` additions merged into one section with the newer
`regenerated:` date. Never drop the other session's entry to simplify the
conflict; then re-run `kb.py build` + `check` so chunk sizes re-validate.

**If the armed PR goes `mergeStateStatus: DIRTY`** (a parallel capture merged to main
after you branched — `generated/`, README.md, and Home.md are COMPILED, so any two
capture PRs conflict on them): resolve in a WORKTREE off your capture branch, never in
the shared checkout (other sessions' dirty topic files block the merge there).
In the worktree: `git merge origin/main`, take main's side of the
generated files (`git checkout --theirs README.md Home.md generated/`), re-run
`python3 ~/Documents/knowledge-base/tools/kb.py build` (regenerates every artifact from
the MERGED topic set) then `check`, `git add` + commit the merge, push. Auto-merge stays
armed and proceeds once checks re-run. Never hand-edit the generated files to resolve
their conflicts.
