# Tier writing guide

Detailed per-tier instructions for writing distilled lessons. Loaded by
`/distill` Step 4 when the writing decisions for a specific tier need
the full procedure. The high-level overview lives in `SKILL.md` Step 4.

## Writing rules by tier

### SKILL-ROUTED (Step 1c override)

Lessons routed to a specific skill bypass T0-T5 entirely. Persist the
correction by editing the target skill's `SKILL.md` directly:

1. **Locate the relevant step** in `$SKILLS_ROOT/{skill-name}/SKILL.md`
   — the step where the wrong behavior occurred (e.g., a missing
   precondition belongs near Step 0; a wrong default belongs in the step
   that sets it).
2. **Use Edit, not Write**: surgical insertion preserves existing
   numbering, frontmatter, and references. Add the correction as a new
   bullet under the relevant step, or as a parenthetical caveat. Match
   the surrounding tone (markdown body — no DSL).
3. **Length**: keep the addition under 5 lines. If the correction
   requires more guidance, append a reference file under
   `$SKILLS_ROOT/{skill-name}/references/` and link to it with a
   one-line pointer in `SKILL.md`. Respect the 500-line `SKILL.md` cap
   (see `rules/skill-standards.md`).
4. **Format the marker entry** with `tier: "SKILL-ROUTED"` and
   `target: "{skill-name}/SKILL.md"` (e.g., `distill/SKILL.md`). The
   `last-distill.schema.json` regex `^(T[0-5](-hook|-startup|-ci)?|SKILL-ROUTED)$`
   accepts the sentinel.
5. **Report** as `SKILL-ROUTED` in the lessons table with the target
   skill and a one-line summary of the edit.

Do NOT also write the same lesson to rules, MEMORY.md, topic files, or
agent memory — skill-routed lessons load only when the target skill is
invoked, which is the entire point of the routing.

### T0 (Enforce)

Stage hook specifications for later installation via `/ship-hook`.

**T0-hook** (stage a specification, do NOT install inline):
1. **Design**: Determine hook event (PostToolUse for fixes, PreToolUse
   for blocks), matcher (tool name pattern), behavior (fix silently vs
   block with stderr), timeout (3-8s).
2. **Write specification** to `$CONFIG_ROOT/hooks/staged/{name}.spec.md`
   containing: hook event, matcher, behavior description, enforcement
   logic pseudocode, and a concrete test case (known-bad input ->
   expected block/fix).
3. **Declare a completion marker** in `bin/staged-spec-staleness.py`'s `MARKERS`
   map, in the same change that stages the spec. `hooks/test-hooks/test_staged_spec_staleness.py::TestEverySpecIsVerifiable`
   FAILS without it, deliberately:

   ```python
   "your-spec-name.spec.md": {
       "target": "hooks/the-file-the-fix-modifies.py",
       "marker": "THE_SYMBOL_THE_FIX_INTRODUCES",   # a constant/env-var name, NOT prose
       "new_file": True,        # ONLY when `target` is a file the fix CREATES
       "shipped_by": None,      # fill in when it ships
   },
   ```

   **Verify the marker is ABSENT from the target before committing.** A marker that is
   already present reports the spec STALE and prints a `git rm` for live work. Prefer a
   symbol name over prose: prose gets reworded, and `"pytest"` or `"VERDICT_COMMANDS"`
   may already appear in the target for unrelated reasons.

   WHY THIS IS REQUIRED, measured 2026-08-27: `hooks/staged/` held **11 specs**. FOUR
   had already shipped — two said so in their own bodies, and two were the *same
   hazard staged 15 days apart* by sessions that could not see each other. The other
   seven had no marker, so the checker printed `OK — 0 live, 11 unverifiable`. The
   queue is not self-cleaning and nothing surfaces it; the author staging the spec is
   the only person who knows how its completion will be detectable.
4. **Report**: Staged spec path, event, matcher, proposed behavior, declared marker.
5. **Do NOT write the hook script, register in settings.json, or test
   inline.** Hook installation during /distill is risky — partial
   registration (script exists but settings.json not updated, or vice
   versa) leaves broken enforcement. The user or a dedicated
   `/ship-hook` workflow installs staged specs with full atomic
   write + registration + test.

Why staged: Distill runs during /retro which touches multiple
persistence targets. Writing a hook script + modifying settings.json +
testing inline adds 3 failure modes to an already-complex flow. Staging
separates "decide what to enforce" from "modify live infrastructure."
(Confirmed: T0-hook inline implementation caused 2 partial-install
incidents before this change.)

**T0-startup**: Tell the user what check to add to `session-start.py`
(function name, what it validates, what it warns).

**T0-ci**: Tell the user what validation to add to the `validate` CI
workflow (what file to check, what assertion to make).

### T1 (Rules) and T2 (runtime project memory)

Invocation authorizes both tiers, but their write targets differ:

- **T1:** append to or surgically edit the appropriate file under
  `$CONFIG_ROOT/rules/`.
- **T2 in Claude Code:** append to
  `$HOME/.claude/projects/$PROJECT_ID/memory/MEMORY.md` after resolving the
  project id with the shared project-dir convention.
- **T2 in Codex:** search `$STATE_ROOT/memories/MEMORY.md` and existing
  extension notes, then create one small governed add/update/delete note at
  `$STATE_ROOT/memories/extensions/ad_hoc/notes/<UTC-timestamp>-<short-slug>.md`.
  Never edit the generated Codex `memories/MEMORY.md` index directly.

**"Why it escaped" check (T1 only):** Before writing a new rule, ask:
"Is there an existing rule, hook, or skill that should have prevented
this? If yes, why didn't it work?" If the answer is "the rule exists
but was too vague / didn't cover this case / had the wrong glob," fix
the existing rule instead of adding a new one. A rule written without
understanding why the previous guardrail failed risks stacking a new
rule alongside a broken one. (dotnet/fsharp postmortem "Why It
Escaped" — Context7 registry 2026-04-07)

**T1 size-budget check:** Before appending to a rule
file, check its current size: `wc -c "$CONFIG_ROOT/rules/<name>.md"`. The
rule-size-guard hook refuses writes that push a rule past 38,000
chars. Periodic descopes (2026-05-18, -19, -21) recurred because
/distill appended without checking.

If the rule is approaching the threshold, use the **T1 rule/incident split
pattern**:

- Keep the strongwording (INVARIANT/FORBIDDEN/GUARD/ON/PROCEDURE/FAILURE)
  in the rule itself. This is T1 — loaded every session.
- Move the verbose INCIDENT narrative (specific symptoms, recovery
  procedures, file:line citations, multi-paragraph context) to
  `$CONFIG_ROOT/rules/incidents/<name>.md` under a `## <slug>` anchor.
  This is an on-demand incident reference, not a T2 system-fact write.
- In the rule, leave a one-line pointer:

  ```
  # INCIDENT <date> <short tag>: <one-sentence summary>. Detail:
  # rules/incidents/<name>.md#<slug>
  ```

The incident file uses `## <slug>` headers matching the slug used in the
rule's pointer. Existing demo: `rules/incidents/platform-constraints.md`
(the pattern was deployed 2026-05-21 against the recurring
platform-constraints budget pressure).

When to use the split:
- Always when the rule is already >35K chars and the new entry is
  >5 lines.
- When the incident narrative is mostly forensic (what file, what
  line, what PR fixed it, how long it cost) rather than rule-shaping
  (what pattern to refuse, what alternative to use).
- Strongwording-only additions (a 2-line FORBIDDEN with a 1-line WHY)
  stay in the rule regardless of size — they're load-bearing for
  guidance.

For T1, identify the most appropriate existing rules file:
- Platform/shell/encoding → `rules/platform-constraints.md`
- Git workflow → `rules/git-hygiene.md`
- Security write ops → `rules/security-confirmations.md`
- Bulk data → `rules/bulk-data.md`
- Agent routing → `rules/agent-delegation.md`
- If no file fits, create a new rules file.

**Contended-checkout clobber guard (T1 + SKILL-ROUTED, any `~/.claude` edit):**
`~/.claude` is a git checkout shared by parallel sessions and a SessionStart
repo-sync hook. An in-place, UNCOMMITTED rule/skill edit can be silently
reverted before /retro Step 5 ships it — the sync hook (or a parallel
session's checkout) resets the working tree, and Edit's success return does
NOT prove on-disk persistence. So do NOT leave a `~/.claude` edit dangling for
Step 5 to ship later. Either:
- (a) commit it on a feature branch in the SAME turn you write it, or
- (b) make the edit in a worktree off origin/main and PR immediately:
  `git -C ~/.claude worktree add ~/worktrees/<name> -b <branch> origin/main`.

After writing, `grep` the file to confirm the edit survived before moving on.
INCIDENT 2026-06-11: a T1 edit to `verify-before-assuming.md` (Edit reported
success) was clobbered within minutes; caught only by a stray reminder, then
re-applied + shipped from a worktree (#1189). The worktree path (b) is the
robust default in a contended `~/.claude`.

### T4 API gotcha dual-write

(T3 was retired 2026-06-10 — B7/F3 owner decision. The `memory/*-patterns.md`
stubs are gone; everything domain-specific is T4 → `agent-memory/topics/`.)

If the lesson is API-related (mentions an endpoint, HTTP method,
status code, permission scope, token type, auth flow, or rate limit),
ALSO write it to the API docs library at
`~/Documents/api-docs/{api-name}/gotchas.md`.

Detection keywords: `GET`, `POST`, `PATCH`, `DELETE`, `401`, `403`,
`400`, `scope`, `permission`, `token`, `OAuth`, `OBO`, `AADSTS`,
`missing_scope`, `rate limit`, `throttl`, `consent`, endpoint path
patterns (`/users`, `/groups`, `/v1.0/`, `/beta/`).

API name mapping (from lesson context):
- Microsoft Graph / Entra / Azure AD / conditional access →
  `microsoft-graph`
- Slack / Enterprise Grid / XOXP / XOXB → `slack`
- CrowdStrike / FQL / Falcon → `crowdstrike`
- Hologram / SIM / IoT fleet → `hologram`
- Tailscale / tailnet / ACL → `tailscale`

Dual-write procedure:
1. Write the primary entry to the topic file (normal T4 flow).
2. Check if `~/Documents/api-docs/{api-name}/gotchas.md` exists.
3. If it exists: append the same entry (same format as T4) to the
   file.
4. If it doesn't exist: create it with a header and the entry.
5. Report: "Dual-write: also appended to
   api-docs/{api-name}/gotchas.md".

This ensures the API docs library stays in sync with operational
discoveries. The topic file remains the primary source (loaded by
worker agents); the api-docs copy makes it searchable via code-search
semantic queries.

### T4 (Topic files / Agent memory)

Append using the standard format. Every entry MUST have a root cause
line:

```markdown
### [observed] [tool-gotcha] Brief title (YYYY-MM-DD)
- Root cause: {why this happened - the actual bug, misconfiguration, or constraint}
- Fix: {what resolves the root cause, not a workaround}
- [PLATFORM CONSTRAINT]: {only if root cause is genuinely unfixable - explain why}
- Evidence: brief reference to what happened in this session
- Distilled by /distill
```

Never write "Workaround: do X instead" without first stating the root
cause and whether it was fixed. If the root cause was fixed in this
session, the entry should document the fix. If not fixed, explain
what the fix would be.

For promotions (`[observed]` → `[confirmed]`): Edit the existing
entry in-place. Update the tag, add the confirmation date, and note
"Confirmed by /distill (YYYY-MM-DD)".

### T5 (Skip)

Report in the table with the reason and location of existing entry.
No writes.

## After all writes

Report a summary:
- Session metrics header (from Step 1b)
- How many lessons found
- How many written (by tier)
- How many skipped (with reasons)
- Any promotions performed
- **Worst offender**: the single pain point that consumed the most
  turns or retries
