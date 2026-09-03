---
name: audit-rules
description: "Measure rule compliance from transcripts and recommend promotions for the most-violated rules."
when_to_use: |
  Measure rule compliance from session transcripts, classify rules by defense layer,
  and recommend promotions (prompt→hook or prompt→skill-step) for the most-violated rules.
  Use when: "audit rules", "rule health", "measure compliance", "which rules are violated",
  "rule lifecycle", "promote rules". Do NOT use for: single-rule debugging (diagnose-before-fix),
  validating a specific change (validate-changes), or knowledge base curation (garden).
disable-model-invocation: true
argument-hint: "[measure | promote [rule-name] | full]"
effort: medium
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: AskUserQuestion Bash Glob Grep Read WebFetch WebSearch Write
---

# audit-rules — Rule Compliance & Lifecycle

Periodic health check for the rule system. Scans session transcripts for
violations, classifies rules by defense layer, and recommends enforcement
promotions for the most-violated rules.

## Modes

- `/audit-rules` or `/audit-rules full` — full workflow (measure → classify → recommend)
- `/audit-rules measure` — scan transcripts only, output violation rates
- `/audit-rules promote <rule-name>` — embed a specific rule as an explicit step in the skills that generate violating code

## Oracle integration (Phase 3 of 2026-05-26 lift)

Audit-rules now emits findings via `skills/_shared/oracle/`, the same
finding-tracker substrate `audit-skill` uses. Each rule violation
becomes a Finding with a `transcript_pattern` reproducer that re-runs
the scanner on demand; closed findings persist via `triage_status`.

**Pipeline**:

```bash
# 1. Scan → Finding YAML (with coverage gaps for uncovered rules)
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit-rules/scripts/scan_to_findings.py \
    --include-uncovered \
    --out AUDIT-TRACKERS/rule-violations.findings.yaml

# 2. Contract check (label/reproducer pairing must be consistent)
${CLAUDE_PLUGIN_ROOT}/bin/audit-skill-oracle.py contract-check \
    AUDIT-TRACKERS/rule-violations.findings.yaml --strict

# 3. Pre-action gate (act-on drops STALE, gates dispatch)
${CLAUDE_PLUGIN_ROOT}/bin/audit-skill-oracle.py act-on \
    AUDIT-TRACKERS/rule-violations.findings.yaml --out worklist.yaml

# 4. Promotion-verification feedback (Layer D fix_loop)
${CLAUDE_PLUGIN_ROOT}/bin/audit-skill-oracle.py verify-fix \
    AUDIT-TRACKERS/rule-violations.findings.yaml \
    --finding-id <rule-id> --pre-ref <pre-sha> --post-ref <post-sha>
```

The act-on report partitions findings into:
- **STILL-FIRES**: rule violation rate ≥ threshold (default 10%)
- **STALE**: rate has dropped below threshold (auto-promotion verified)
- **MANUAL**: coverage-gap finding for uncovered rules (needs detector
  authored before automated verdict possible)
- **TRIAGE-CLOSED**: explicitly closed via `set-triage-status`

> **Worktree caveat**: the oracle runs every reproducer with cwd pinned
> to its own repo root (`bin/audit-skill-oracle.py`: `REPO =
> Path(__file__).resolve().parent.parent`, used as `cwd=str(REPO)`) —
> i.e. the LIVE `~/.claude` checkout, even when you pass a tracker from
> a worktree. Scanner/detector fixes built in a worktree do NOT change
> act-on verdicts until they merge; expect a STILL-FIRES lag on findings
> your in-flight fix resolves (2026-06-12: V5 read 9.2% in the
> fixed-scanner tracker while act-on, re-running the live scanner,
> still reported it firing at 15.9%).

Coverage gap: ~8 of ~31 ambient rules have detectors in
`scan_violations.py` (V1-V6 ship-wide, V7 and V8 added 2026-05-26 from
the Phase 7a FORBIDDEN-signature seeds). Coverage-gap findings (code
`GAP`) surface the remaining ~23 rules in the tracker as
`type: manual + label: unverified` so the gap is observable rather
than silent. Authoring a new detector follows the V1-V8 pattern in
`references/scan_violations.py`.

Detector ledger:

| Code | Scanner key                  | Rule (FORBIDDEN ID or behavior)          |
|------|------------------------------|------------------------------------------|
| V1   | encoding-missing-open        | `open()` without `encoding=`             |
| V2   | missing-stdout-reconfigure   | `sys.stdout.reconfigure` missing on Win  |
| V3   | inline-python-c              | `python -c "..."` >300 chars             |
| V4   | str-replace-crlf-risk        | `.replace('\n', ...)` near file read     |
| V5   | git-commit-no-branch-check   | `git commit` with no branch verify       |
| V6   | websearch-webfetch-used      | `WebSearch`/`WebFetch` used              |
| V7   | curl-verbose-with-auth       | `curl_verbose_with_auth_or_secret_header`|
| V8   | pip-install-upgrade-all      | `pip_install_upgrade_all_outdated`       |
| V9   | _disabled_                   | `subprocess_run_text_true` (73% FP rate) |

### Detector-authoring seeds (Phase 7a)

Some ambient rules carry snake_case `FORBIDDEN: <identifier>` blocks
that encode the anti-pattern in identifier form (e.g.,
`FORBIDDEN: pip_install_upgrade_all_outdated`). These are
auto-extractable into keyword signatures — useful starting points for
detector authoring.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit-rules/scripts/extract_forbidden_signatures.py
```

The extractor emits a registry mapping rule → list of snake_case
identifiers + their keyword decompositions. The corresponding GAP
findings in `AUDIT-TRACKERS/rule-violations.findings.yaml` carry the
identifier list in the description, so operators can prioritize
detector work on rules that have parseable seeds (currently
~2 rules with ~16 total signatures vs ~25 with prose-only forbidden
blocks).

Note: keyword signatures are NOT auto-detectors — the keywords are
too generic to fire reliably on their own. They're the seed an
operator uses to author a real V7+ detector in `scan_violations.py`.

## Durable false-positive suppressions (Phase 5)

When a violation is INTENTIONAL (binary-mode `open()` is rightly
omitting `encoding=`, the operator authorized a research session to
use `WebSearch`, etc.), add a durable entry to
`AUDIT-TRACKERS/rule-suppressions.yaml`:

```yaml
suppressions:
  - rule: encoding-missing-open
    pattern: "open('/path/to/binary"
    reason: "binary I/O intentionally omits encoding="
    added: "2026-05-26"
    expires: "2026-12-31"   # optional; rule rate must hold below
                            # threshold without this suppression
```

Two match modes:
- `pattern:` — case-insensitive substring on the violation excerpt;
  best for "this code shape is always intentional"
- `session_id:` — short ID prefix (first 12 chars); best for
  "this one session was approved"

The scanner reads this file on every run and excludes matching
violations BEFORE rate aggregation. The JSON output exposes
`suppressed_count` per rule and a top-level `suppressed` dict so
operators can audit how many violations were filtered.

Difference from `triage_status: FALSE_POSITIVE`:
- `triage_status` closes ONE finding (one wave of the tracker)
- `rule-suppressions.yaml` filters ALL future violations matching
  the pattern (durable across re-runs)
- Use `triage_status` for "this finding was wrong"; use
  `rule-suppressions.yaml` for "this code shape will keep producing
  violations and they're all intentional"

## Demotion workflow (Phase 6)

When a hook turns out to be too aggressive (it blocks legitimate
code at a high rate), the rule needs to move BACK toward less-strict
enforcement: `hook-block → hook-warn → prompt-only`. Demotion is the
opposite of promotion.

Signals that a rule is a demotion candidate:
- The hook's PreToolUse block-rate against historical transcripts
  exceeds ~10% (see `rules/verify-effectiveness.md` GUARD
  `hook's unit tests pass`)
- Operator workflow shows repeated bypass attempts in transcripts
  (multiple blocked tool_use within minutes for the same pattern)
- The rule's session_rate stays HIGH after promotion (suggesting
  agents are working around the hook rather than complying — a sign
  the hook's mental model doesn't match agent behavior)

### Automated demotion-candidate detection (Phase 7b)

Run the detector to surface rules that are hook-enforced AND have
high session_rate — the joint condition that signals demotion is
worth investigating:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit-rules/scripts/detect_demotion_candidates.py
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit-rules/scripts/detect_demotion_candidates.py \
    --threshold 30 --days 30 --json
# Reuse the Step 1 scan instead of re-scanning (faster; keeps numbers
# identical to the report the operator already saw):
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit-rules/scripts/detect_demotion_candidates.py \
    --scan-json /tmp/claude/scan.json --json
```

Rules with an effective entry in `AUDIT-TRACKERS/demotions.yaml` are
reported under `already_demoted` (with date, PR, and rationale), NOT as
candidates — a demotion the operator already decided is not an
investigation item. The output names each remaining candidate, its
enforcing hook, session_rate, and a hypothesis string covering the three
possible causes (coverage gap / agent workaround / hook over-fires).
Investigation determines which subclass applies:

- **Coverage gap** → widen the hook (extend its rule-firing surface
  to cover the missing case; PR against `hooks/<name>.py`)
- **Agent workaround** → document the workflow that agents are
  reaching for instead of complying; consider whether the rule's
  goal should be expressed differently
- **Hook over-fires** → genuine demotion: change `decision: "block"`
  → `decision: "warn"` in the hook, OR delete the hook entry from
  `settings.json` and rely on the prompt-only rule

To request demotion, mark the rule's tracker finding with a triage
note:

```bash
${CLAUDE_PLUGIN_ROOT}/bin/audit-skill-oracle.py set-triage-status \
    AUDIT-TRACKERS/rule-violations.findings.yaml \
    --skill audit-rules --code <V?> \
    --status DEFER \
    --note "DEMOTION REQUESTED: <hook-name> blocks legitimate <X> at <rate>%; demote to warn"
```

The DEFER closure documents the demotion request. The actual
implementation (editing the hook to emit `decision: "warn"` instead
of `"block"`, or moving the rule from hook-enforced to prompt-only)
is a separate edit cycle — typically a follow-up PR.

**The demotion PR MUST add an entry to `AUDIT-TRACKERS/demotions.yaml`**
(scanner_rule, classifier_rule, hook, scope, date, pr, rationale). The
ledger is what keeps the classifier, the demotion detector, and Step 3's
promotion logic from re-reporting a deliberate demotion as a broken or
promotable hook. 2026-08-22 incident: the encoding guard's 2026-06-27
platform demotion lived only in hook comments and git history, so a
55.7%/55.0%-net-silent reading looked like a 40x firing-path regression
and cost a full instrument-verification pass to resolve.

After demotion is implemented, run `lifecycle_check.py` to verify
the warn-mode rate matches the documented expected range (20-40%
per the defense-layer table above); if it stays at 0%, the demotion
may have been over-applied and warn is also under-firing.

## Step 1: Scan Transcripts for Violations

Run the violation scanner against the last 14 days of transcripts:

```
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit-rules/references/scan_violations.py
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit-rules/references/scan_violations.py --rule encoding-missing-open  # filter
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit-rules/references/scan_violations.py --json                        # machine output
```

> **Capture --json output without `2>&1`** — the per-session progress
> indicator (`  ...N/total`) goes to stderr by design. Redirecting
> stderr to stdout (`> out.json 2>&1`) pollutes the JSON with a
> leading non-JSON line and breaks `json.load()`. Use plain
> `> out.json` (let stderr surface in the terminal) or
> `> out.json 2>/dev/null` if quiet. Distilled 2026-05-27.

This produces a per-rule violation table (counts, unique sessions, session
rate). The scanner:
- Discovers transcript dirs under `~/.claude/projects/*/` and `~/.claude/session-transcripts/`. Exits with an error if none exist.
- Only counts violations in **assistant-generated content** (not rule text in system-reminders).
- Distinguishes **executed** code (tool_use inputs — what hooks see) from
  **display-only** code fences in chat (which no hook surface intercepts).
- Deduplicates by session ID across discovered directories.
- Runs EIGHT opinionated detectors (V1–V8 in `scan_violations.py`): missing `encoding=`, missing `sys.stdout.reconfigure`, long inline `python -c`, `str.replace('\n', …)` near a file read, `git commit` with no `git branch` check, `WebSearch`/`WebFetch` usage, `curl -v` with auth header (V7), and bulk `pip install --upgrade` (V8). See the detector ledger above for the full table.

> The scanner is NOT a generic rules/*.md interpreter — it measures an
> opinionated subset. Adding a new rule does not automatically add a
> detector. Treat the table as a sample of high-value patterns, not a
> census of every rule.

### Scanner JSON schema (`--json`)

```
{
  "sessions_scanned": int,
  "lines_scanned": int,
  "scan_window": ["<iso>", "<iso>"],
  "suppressed": {"<rule>": int},          // rule-suppressions.yaml filtered
  "violations": {
    "<rule>": {
      "count": int,                        // total hits (NOT "hits")
      "unique_sessions": int,
      "session_rate_pct": float,
      "examples": [["<session-prefix>", "<excerpt>"], ...],
      "suppressed_count": int,
      // only for rules in RULE_BLOCK_SIGNATURES:
      "blocked_then_fixed_sessions": int,
      "net_silent_sessions": int,
      "net_silent_rate_pct": float,
      // only for encoding-missing-open (V1):
      "path_split": {"scratch": int, "durable_or_unknown": int, "non_literal": int}
    }
  }
}
```

Every V1–V8 detector appears in `violations` — zero-hit rules get a
zero-count entry, so "measured clean" is distinguishable from "detector
removed". `path_split` buckets V1 hits by the open() argument: `scratch`
(/tmp, /private/tmp, /dev, /var/folders, $TMPDIR — the shape the
2026-06-27 macOS demotion deliberately accepts), `durable_or_unknown`
(any other literal path — the portability risk the warn still targets),
and `non_literal` (variable argument, path unknowable from the excerpt).

If mode is `measure`, present the results and stop.

## Step 2: Classify Rules by Defense Layer

Run the rule classifier:

```
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit-rules/references/classify_rules.py
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit-rules/references/classify_rules.py --rule encoding   # filter
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit-rules/references/classify_rules.py --json
```

The classifier auto-resolves the config root from its own location (works
from `~/.claude/` or a repo checkout) and:
- Reads each rule→hook entry in `HOOK_RULE_MAP` and determines strength by
  scanning the hook's source for `decision: "block"`, `sys.exit(2)`, or
  `permissionDecision: "deny"` (block signals) vs `decision: "warn"`.
  PostToolUse hooks that emit `decision: "block"` are correctly classified
  hook-enforced — the old PreToolUse-vs-PostToolUse heuristic mis-labeled
  them as warn-only.
- Cross-checks `HOOKS_DIR` for hooks that have block/warn signals but are
  NOT in the curated map and surfaces them as "uncurated hooks" — a
  coverage signal for map staleness.
- Consults `AUDIT-TRACKERS/demotions.yaml`: a rule whose demotion is
  effective on this platform is reported `hook-warned (demoted <date>, …)`
  even though its hook source still carries a platform-gated block signal.
  Source-scanning alone cannot see a `sys.platform` gate around the block
  emission — the ledger is the authority for deliberate demotions.
- Walks `skills/*/SKILL.md` looking for embedded-rule markers (e.g.,
  `git branch --show-current`, `encoding='utf-8'`, `sys.stdout.reconfigure`)
  to populate skill-enforced entries — no hand-curated SKILL_RULE_MAP.

Defense layers:

| Layer | Definition | Expected Violation Rate |
|---|---|---|
| prompt-only | Text in rules/*.md only | 20-50% (IFScale) |
| hook-warned | Hook detects + warns | 20-40% (warning ignored) |
| hook-enforced | Hook detects + blocks | ~0% |
| skill-enforced | Explicit step in a skill | Low when skill invoked |

> **Fixed 2026-07-04** (was: "Known limitation (2026-07-03)" — `prompt-only (est.)` only matched the older `- **bolded**` bullet convention, never DSL `INVARIANT`/`GUARD`/`FAILURE` lines, so it silently reported `0` for the entire corpus regardless of real prompt-only count). `_RULE_UNIT` in `classify_rules.py` now also counts top-level `INVARIANT`/`GUARD pattern=`/`FAILURE <name>:` lines as one rule each (PROCEDURE headers and STEP_N lines are deliberately excluded — they're the "how" for an INVARIANT declared elsewhere in the same file, not a separate rule). On the real corpus this moved `total_rule_lines` from 67 to 535 and `prompt-only (est.)` from 0 to 432 — most of the rule corpus has no hook/skill backstop, which the old count was hiding entirely.

## Step 3: Cross-Reference Violations with Defense Layers

Join the violation data (Step 1) with the classification (Step 2).
Produce a ranked table:

```
Rule                         | Violation Rate | Defense Layer  | Action
-----------------------------|---------------|----------------|--------
str-replace-crlf-risk        | 44.2%         | prompt-only    | PROMOTE
encoding-missing-open        | 40.4%         | hook-enforced  | OK (fixed)
inline-python-c              | 38.2%         | prompt-only    | MONITOR
missing-stdout-reconfigure   | 29.5%         | prompt-only    | MONITOR
```

Rules with >10% violation rate AND prompt-only defense → recommend PROMOTE.
Rules already hook-warned with >20% violation rate → recommend upgrade from warn to block —
UNLESS the rule has an effective entry in `AUDIT-TRACKERS/demotions.yaml`.

**Demotion-ledger gate (check FIRST, before any layer-based action)**: a
rule in the demotion ledger was deliberately moved to warn (or to a
platform-gated block) by an operator decision with recorded evidence. Do
NOT recommend re-promotion for it unless new evidence overturns the
recorded rationale — and say so explicitly ("in demotion ledger,
2026-06-27, PR #1471: ~73 false stops/14d"). The classifier already
annotates these rules `hook-warned (demoted <date>, see
AUDIT-TRACKERS/demotions.yaml)` and its `--json` output carries the
ledger under `demotions` (each entry with `effective_here` for this
platform). A high warn-band rate on a ledgered rule is the *expected
consequence of the demotion*, not a promotion signal.

**Hook-enforced + high-rate gate (verify-instrument-before-fix)**: If a rule
is already classified hook-enforced AND its rate is >10%, do NOT recommend
upgrading enforcement strength. Instead, READ the hook source and identify
the **coverage gap** — the surface the hook doesn't fire on. The scanner's
detection regex typically catches code in tool_use inputs (Bash, Write/Edit
of any file) while the hook may only fire on a specific tool/path subset.
(2026-05-17 incident: encoding-missing-open scored 39.1% but the hook ALREADY
blocked on .py Write/Edit + heredoc Bash since 2026-04-21/2026-05-02; the
real gap was inline `python -c "...open(...)..."` bodies. Recommending
"upgrade warn to block" would have wasted a PR. The fix was a new hook
function `check_inline_python_encoding` covering the missing surface — PR
#904.)

REQUIRED probe procedure (no shortcut to hypothesis):

1. Sample 3-5 scanner-flagged excerpts from the scanner's JSON output.
2. **Run the reusable probe harness — do NOT hand-build one:**
   `python3 skills/audit-rules/probes/probe.py --rule <rule-name>`. It drives
   each fixture in `probes/<rule>/fixtures.json` through the real hook via
   `subprocess.run`, seeds real files on disk for PostToolUse hooks, and
   prints a BLOCK/ALLOW matrix. `--list` shows rules that already have
   fixtures. To probe a NEW rule, create `probes/<rule>/fixtures.json` (copy
   the `encoding-missing-open` schema) covering the matrix: Write of `.py`,
   Write of non-`.py` (`.json`, `.md`), Edit of `.py`, Bash inline
   `python -c "..."`, Bash heredoc — plus any shape the scanner flags but a
   hook may miss (e.g. `cat > foo.py <<EOF … open() … EOF`, `echo … | python3`).
3. **Record the BLOCK/ALLOW verdict for each probe BEFORE forming the
   coverage-gap hypothesis.** The hypothesis must be derived from the
   probe matrix, not from reasoning about the excerpts.
4. **Store probe fixtures in a sibling JSON file**, not as literals in
   the .py probe script. A patched hook will (correctly) fire on literal
   `open('foo.json')` payload strings in a .py file — that's the hook
   working as designed, but it blocks your test infrastructure. The same
   applies to the LIVE guards while you audit: fixture literals carried
   in a Bash heredoc or inline `python -c` body trip the running
   PreToolUse guards mid-session (2026-06-12: blocked twice running
   detector unit tests inline). Run probe/test harnesses from a written
   `.py` file — post-write-edit masks string-literal fixtures; inline
   bodies get no such masking.
5. **Transcript forensics: hook feedback location differs by event.**
   When classifying scanner hits as hook-fired vs silent, PreToolUse
   denials appear in the SAME tool_use's tool_result (as the error
   text); PostToolUse block feedback does NOT — it lands elsewhere in
   the transcript. Checking only the triggering tool_use's result
   systematically mislabels PostToolUse-defended hits as "silent". Grep
   the whole session for the hook's block signature instead (e.g.
   post-write-edit's `without encoding='utf-8' at`). 2026-06-12 wave:
   all 21 Write/Edit hits were mislabeled silent by a same-result check;
   the session-wide grep found the block signature in 9 sessions and
   flipped the verdict from "firing path broken" to "block-then-fix
   cycles".

   **This split is now automated by the scanner** for rules in its
   `RULE_BLOCK_SIGNATURES` map: it reports `net_silent_rate_pct` +
   `blocked_then_fixed_sessions` (table column "Net-silent / block-then-fix"),
   so judge a hook-enforced rule by its **net-silent rate**, not the attempted
   `session_rate_pct` (2026-06-16: `encoding-missing-open` read 12.5%
   attempted but ~1.3% net-silent). To cover an unmapped rule, add its guard's
   block-signature substring(s) to the map (verify in transcripts first).

The verb "confirm" here means "run the probe and observe", not "reason
about it". 2026-05-22 incident (PR #947 then #948): I sampled 5 excerpts
(all short `open('settings.json')` patterns), HYPOTHESIZED display-only
code fences were the source, recommended a scanner-narrowing fix. Metric
didn't drop (33% → 35%). Only when I built the synthetic probe did two
real bugs surface (no-mode `open()` in post-write-edit; prefix-only ctx
in bash-security-guard inline/heredoc). The probe would have surfaced
both in 5 minutes; the hypothesis route cost 1 extra PR.

Rules already hook-enforced with <20% violation rate → OK.
Rules with <5% violation rate → no action needed.

**Threshold rationale (2026-04-17):** Lowered from 20% to 10% after the
`str-replace-crlf-risk` case — 16.4% was clearly worth promoting but fell below
the old threshold. Many sessions don't exercise the relevant work at all, so a
10% rate on sessions that DO exercise it is enough signal to act.

## Step 3b: Post-Promotion Lifecycle Feedback

Before presenting new recommendations, check whether rules promoted in the
last 30 days are actually seeing reduced violation rates. Without this check,
promotion is a one-way ratchet with no feedback loop.

Run the lifecycle checker:

```
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit-rules/references/lifecycle_check.py
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit-rules/references/lifecycle_check.py --days 60 --json
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit-rules/references/lifecycle_check.py --window 21  # pre/post comparison window (default 14d)
```

This script:
1. Greps `git log` for promotion commits with subjects matching
   `^(feat|chore|fix|distill)(<scope>): \b(embed|promote|skill-enforce[d]?|hook-enforce[d]?)\b`
2. Infers the rule name from kebab-case tokens in the subject (filtering
   common-word noise like `skill-enforced`, `audit-rules`).
3. For each promotion, invokes the scanner with `--rule <name>` over the
   14 days BEFORE the commit and the 14 days AFTER, in JSON mode.
4. Verdicts: **OK** when relative reduction ≥30%, **INEFFECTIVE** when
   smaller, **INCONCLUSIVE** when either window lacks transcripts.

INEFFECTIVE promotions should be revisited — strengthen the embedded
step or escalate to a hook. The signal is most reliable when the
promoted rule has high baseline traffic in the pre-window.

## Step 4: Recommend Promotions

For each rule marked PROMOTE, identify:

1. **Which skills generate the violating code?** — search transcripts for
   skill invocations in sessions where the violation occurred
2. **Where in the skill should the rule be embedded?** — identify the step
   that produces the output (e.g., "Step 3: Write the script")
3. **What should the embedded step say?** — draft the exact text to add

Present recommendations as a table with skill name, step number, and
proposed insertion text.

## Step 5: Apply Promotions (if mode is `full` or `promote`)

For each approved promotion:
1. Read the target skill's SKILL.md
2. Add the rule as an explicit step or sub-bullet at the identified location
3. Run `/validate-changes` on the modified skill

**Confirm with user before applying.** Present the diff for each skill
modification and wait for approval.

---

## Example Output

The scanner produces a raw table; Claude composes the action column by
joining with classifier output. Raw scanner output (`scan_violations.py`,
real run 2026-08-22 — the `Count` column matches the JSON `count` key;
zero-hit detectors appear as zero rows, meaning "measured clean"):

```
Window: 2026-08-08 → now
Sessions: 149 | Lines: 130,218

Rule                                      Count   Sessions     Rate  Net-silent / block-then-fix
----------------------------------------------------------------------------------------------------
  encoding-missing-open                    1081         83    55.7%  net-silent 82 (55.0%); 1 blocked-then-fixed
  str-replace-crlf-risk                      31         13     8.7%  —  (no guard signature mapped)
  git-commit-no-branch-check                 12          9     6.0%  —  (no guard signature mapped)
  inline-python-c                             6          5     3.4%  net-silent 1 (0.7%); 4 blocked-then-fixed
  missing-stdout-reconfigure                  1          1     0.7%  —  (no guard signature mapped)
  websearch-webfetch-used                     0          0     0.0%  —  (no guard signature mapped)
  curl-verbose-with-auth                      0          0     0.0%  —  (no guard signature mapped)
  pip-install-upgrade-all                     0          0     0.0%  —  (no guard signature mapped)
```

The "Net-silent / block-then-fix" column (mapped rules only) splits the
attempted `Rate` into executed-unblocked (net-silent — the real gap) vs
blocked-and-retried; judge hook-enforced rules by net-silent. BUT check
the demotion ledger before reading a high net-silent as a firing-path
failure: the 55.0% above is the encoding guard's warn posture working as
demoted (2026-06-27, PR #1471) — the warn path deliberately omits the
block signature so warned-but-proceeded counts as net-silent.

Composed report Claude produces by joining with the classifier:

```
=== RULE COMPLIANCE AUDIT (14 days, 149 sessions) ===

Top Violated Rules:
  1. encoding-missing-open     55.7%  hook-warned (demoted 2026-06-27)  → NO ACTION (in demotion ledger)
  2. str-replace-crlf-risk      8.7%  hook-warned                       → MONITOR (<10%)
  3. git-commit-no-branch-check 6.0%  hook-enforced                     → MONITOR
  4. inline-python-c            3.4%  hook-enforced (0.7% net-silent)   → OK (working)

Promotions: none (no rule >10% with prompt-only defense).
```

## When to Run

- Monthly or quarterly as a health check
- After adding new rules (verify they're being followed)
- After adding new hooks (verify violation rate decreased)
- After a session with multiple user corrections

## Examples

**Example 1: Post-sprint rule compliance check**
User says: `/audit-rules`
Actions: Runs `scan_violations.py` (last 14 days) for the six built-in
detectors, then `classify_rules.py` to label each by defense layer, then
`lifecycle_check.py` for promotions in the last 30 days. Joins the three
outputs into a ranked recommendation table.
Result: "448 sessions scanned. `str-replace-crlf-risk` 44.2% hook-warned → upgrade to block. `encoding-missing-open` 40.4% hook-enforced → probe for coverage gap (already blocking; suspect surface missed)."

**Example 2: Focus on one rule**
User says: `/audit-rules measure` then filters via the scanner:
`scan_violations.py --rule encoding-missing-open --days 30`
Actions: Reports session rate and unique sessions for that rule, alongside
example excerpts. The user can then run the classifier with `--rule encoding`
to see which hook(s) defend the rule, and check lifecycle status with
`lifecycle_check.py`.
Result: "encoding-missing-open 40.9% (181 sessions). Defense: post-write-edit.py (hook-enforced) + bash-security-guard.py inline-python check. Probe for coverage gaps in display-only fences."

## Success Criteria

- Violation rates measured from real transcript data, not inferred
- Every rule classified by current defense layer
- Promotions cite specific violation rates and target skills
- No promotion recommended for rules with <5% violation rate
- Applied promotions confirmed via validate-changes
