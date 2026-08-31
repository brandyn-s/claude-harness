---
paths:
  - "**/rules/search-efficiency.md"
  - "**/rules/incidents/search-efficiency.md"
---

# search-efficiency: Incident Narratives

Extracted from `rules/search-efficiency.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## 2026-08-29-three-instrument-failures-one-session-two-caught-by-controls

```
WHY: 2026-08-29 settings-audit session. THREE instruments returned misleading
output in one session; the two with positive controls were caught in the same
turn, the one without shipped a false published claim.

1. ONE-SIDED DIFF (no control -> FALSE CLAIM SHIPPED). Ran
   `git diff HEAD -- settings.json | head -30`, saw `-minimumVersion`,
   `-workflowSizeGuideline`, `-skillOverrides`, and reported that the CLI's
   settings rewrite had DROPPED committed keys. Wrote a memory file asserting
   it. All three keys were present the whole time: the rewrite REORDERS keys,
   and the matching `+` lines sat at diff lines 906/898/365 — below the cut.
   Retracted, deleted the memory file, and wrote the retraction into
   reference_claude-code-launchers.md. The real condition was unrelated:
   ~/.claude is 270 commits BEHIND origin, so six newer settings had never
   been PULLED (crossSessionInbound, isolatePeerMachines, dialogExpiry, and
   env MAX_MCP_OUTPUT_TOKENS / FILE_READ_MAX_OUTPUT_TOKENS /
   EXPERIMENTAL_AGENT_TEAMS). "Dropped by a rewrite" and "never pulled" have
   different fixes; only the second was real.

2. BSD GREP ON A BINARY (control caught it). `grep -c TOKEN <Mach-O>` returned
   0 for CLAUDE_CODE_ENABLE_TELEMETRY and CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS
   — both documented and version-gated, so both certainly present. An earlier
   call in the same session HAD worked, which made the zeros credible. Rebuilt
   as `strings -a <bin>` + in-memory count with two positive controls and one
   fabricated negative: 5 / 12 / 4 hits, fabricated 0. Only then was
   CLAUDE_CODE_UNATTENDED_RETRY's 0 trustworthy as real absence.

3. `git grep -E` AND `\b` (control caught it). Every pattern containing `\b`
   returned 0 across a 979-file repo, including `\bctx\.\w+\(` — while
   `ctx.sample(` appeared on a line the SAME run had already printed. Two
   earlier "confirmation passes" (`\bsampling\b`, `\broots\b` -> 0) were
   therefore artifacts, not confirmations.

ROOT CAUSE CLASS: instrumentation. The generalisable split is POLARITY —
search-efficiency already forbade reading truncated output as ABSENCE, and I
read it as a POSITIVE finding instead, which the rule did not name.
FIX: rules/search-efficiency.md gains INSTRUMENT_DIALECT (0 needs a positive
control) and ONE_SIDED_OUTPUT (truncation manufactures false positives too);
FORBIDDEN extended to both polarities.
```

## 2026-08-26-wrapped-query-flag

```
WHY: a handed-over one-liner was long enough to WRAP in the operator's terminal,
and the paste split it into two lines with the break BETWEEN a flag and its
argument. Every value was quoted correctly, so none of the earlier HANDOFF items
applied — length itself was the defect.

Command:
  aws ecs describe-task-definition … --query "…[?name=='X'].value" --output text

The wrap landed before the `--query` value. The operator's shell reported
`argument --query: expected one argument`, then tried to EXECUTE the orphaned
JMESPath as a command (`command not found: taskDefinition.…`). Two operator
round-trips.

FIX: past roughly one terminal width, stage a script and hand over the short
invocation. A staged script is also re-runnable and reviewable, and must be
verified by RUNNING it before handover.
```

## 2026-08-30-capped-recall-grep

```
WHY: 2026-08-30 — grepped `agent-memory/topics/jamf.md` for the Jamf write path
with `| head -20`. The match set was longer than 20, and line 94 — a
`[confirmed]` entry distilled ONE DAY earlier — named BOTH the exact mechanism
(`redeploy_on_update` is a per-request directive, not a persisted setting) AND
the exact wrong oracle I then went on to use (API readback). So a fleet MDM
write was reported VERIFIED on the one oracle that entry explicitly forbids.

The distinguishing property of a capped RECALL grep is that it has NO TELL.
Elsewhere truncation distorts a COUNT and COUNT_OVER_SILENCE catches it; here it
silently removes the entry you are looking for, and you cannot miss what you
never saw — so you proceed as if the knowledge does not exist, with full
confidence. Size the match set with `grep -c` first, then read all of it.

Related: the ambient directive is RECALL_NEVER_CAPPED in
`rules/search-efficiency.md`.
```

## 2026-08-01-asked-to-inventory-claude-configuration-in

```
WHY: 2026-08-01 — asked to inventory Claude configuration in Databricks, I ran
`memory_search("Databricks workspace model serving AI gateway configuration")`.
`agent-memory/topics/databricks.md` did not appear in 8 results, so I reported
"zero Databricks entries across 25,645 indexed chunks" — and had to retract it.
That file is about SCIM, so 5 of my 6 concepts mismatched and sank the 1 that
did. Measured afterward: `"databricks"` ranks it #2 (cos 0.468), `"Databricks"`
#1 (0.466), `"Databricks GovCloud account credentials keychain"` #1 (0.560).
The tool was never at fault. One bad query cost 4 dead-end turns, 3 classifier
denials and a wrong public claim — while line 8 of that very file named the
exact Keychain items those turns were spent hunting for.
```

## 2026-08-08 — a handed-over command whose placeholder zsh parsed as a redirection (3rd recurrence)

Reporting an eviction the user could finish themselves, I pasted:

```
redis-cli -h <primary-endpoint> -p 6379 --tls -a "$TOKEN" DEL mcp-oauth-proxy-clients:<id> ...
```

The user ran it and got `(eval):1: no such file or directory: primary-endpoint`. Angle
brackets are **shell-active**: zsh reads `<primary-endpoint>` as an input REDIRECTION and
aborts before the command executes. A placeholder in a handed-over command is not a
template the user fills in — it is a parse error.

**Two independent defects in one paste**, and the second is the worse one:

1. The unresolved placeholder (the parent rule's step 2, already in prose since
   2026-08-01's `gh api .../pending-deployments` instance).
2. **The command could not have worked with any value substituted.** That ElastiCache
   endpoint accepts connections only from the tasks security group, so no command run from
   the user's laptop reaches it. The real path was `aws ecs run-task` with a
   `containerOverrides.command` on the EXISTING task definition — which also kept the auth
   token off the workstation, since `REDIS_HOST`/`REDIS_PASSWORD` are already injected
   there. I handed over a shape that was wrong about the network, not just the syntax.
   That gap became step 5 of the parent rule's checklist.

**Why the existing rule did not fire.** Steps 1-4 were already present and correct. They
are a numbered list, which `rule-authoring.md` measures as reading *negotiable* (~86%
compliance vs ~99% with a named GUARD). The override I used on myself was "it's obviously
a placeholder, they'll substitute it" — so the fix is the GUARD that names that exact
sentence, not more prose. A KB plan dated 2026-08-01 had already proposed this GUARD for
the first instance and never landed it; that is why there was a third.

## ESCAPED_LITERAL_ZERO — searching for the RENDERED form of a token that is ESCAPED in source (2026-08-30)

Searching a Python file for extractors keyed on a bold-markdown verb, the query was the
literal substring `**`. It returned **0** across every registry file — twice, once via
`grep` and once via a file-reading Python script, which made the zero look corroborated.

The pattern in source is written `r"\*\*(?:get|post|…)\*\*"`. The two asterisks are
**separated by backslashes**, so the substring `**` never occurs. The correct probe is the
escaped form `\*\*` (or an unescaped-alternation check on the verb names). Re-running with
`r"\*\*"` found both lines instantly — and a POSITIVE CONTROL in the same pass ("any
pattern line naming an HTTP verb") is what exposed the bad probe, because it returned 2
while the `**` probe returned 0 on the same file.

**The generalisation, which is not the same as the `\b`/binary cases in the rule:** those
are instrument DIALECT failures (the tool cannot express the pattern). This is a
SOURCE-FORM failure — the instrument is fine and the pattern is wrong, because a regex,
shell string, or markdown token is stored ESCAPED and rendered UNESCAPED. Anything you
have only ever seen RENDERED (`**bold**`, `\n`, `$var`, `[`, a JSON `"k": "v"` spacing)
is a candidate. Grep the escaped form, or grep a neighbouring unescaped anchor.

The cost here was bounded only because the zero contradicted a line I had already READ
with my own eyes minutes earlier — that contradiction is the tell, and it is worth
treating as a hard stop rather than a puzzle. A zero that disagrees with direct
observation is a probe defect, never evidence.

Same session, adjacent: the containment claim "`compliance-endpoints` is the ONLY channel
keyed on a bold verb" was drafted off that broken probe. Had it shipped, the blast-radius
statement in a PR body would have been fabricated from a false zero.
