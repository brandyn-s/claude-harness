# Guard obsolescence evaluation — full, 4.8-grounded, transcript-backed

> **Status:** Ready to execute. **Execution target:** Claude Code on the Windows
> workstation (where the guards are installed, the `run-hook` telemetry is live,
> and local session transcripts exist — none of which is true in a remote/Linux
> session). **Author context:** distilled from the 2026-05-31 review session that
> added the drift gate + fire-rate telemetry and refreshed
> `claude-knowledge-base/topics/hook-bitter-lesson-audit.md`.

## Why this exists

The session that produced this plan could classify the guards and build the
measurement tooling, but **could not validate Opus 4.8 behavior** — the guards
aren't installed in a remote container, the `Agent` tool hides sub-agent tool
calls, and self-introspection is n=1/biased. The rigorous answer requires the
workstation: live telemetry, disable-and-count, and **retroactive mining of the
real session transcripts**. This plan hands that work to terminal Claude Code.

Prerequisites already in `main`: `bin/architecture-drift-check.py`,
`bin/hook-fire-report.py`, the `run-hook` fire-rate telemetry
(`~/.claude/audit/hook-fires-*.jsonl`), and the refreshed bitter-lesson audit.

---

## Prompt (paste into Claude Code on the workstation)

You are auditing every guard in this `~/.claude` harness to decide which are still
earning their keep on **Opus 4.8**, which need tuning, and which are obsolete
scaffolding. Start with `/superplan` to plan this; it's a measurement project, so
`/build-measurement-harness` applies. Read these first for the framework (don't
re-derive it): `~/Documents/knowledge-base/topics/hook-bitter-lesson-audit.md`
(the 2026-05-31 re-audit + ranked candidates), `ARCHITECTURE.md` Layer 5,
`bin/hook-fire-report.py`, `bin/architecture-drift-check.py`, and
`hooks/bash-security-guard.py`.

### Scope
Every GUARD-class check — anything that blocks / warns / transforms a tool call —
INCLUDING the sub-guards inside `bash-security-guard.py` (credential, credential-theft,
exfiltration, reverse-shell, prompt-injection, dangerous-command, inline-python,
push/commit/pr/rebase, the auto-fixes) AND the standalone guard hooks (search-path-guard,
block-partial-read, memory-write-guard, config-guard, destructive-ops-guard,
git-empty-push-guard, bash-tail-buffering-guard, code-search-vocab-divert,
security-write-confirm, verify-before-assuming, tavily-extract-guard, tavily-search-cap,
result-injection-guard, loop-detector, prompt-secret-scan, creative-output-grounding-check,
skill-ref-validator, code-search-chunk-drop-guard). Exclude pure orchestration/telemetry/
lifecycle hooks (session-start, post-merge-sync, skill-routing-hint, etc.) — they don't gate.

### Classification (decides obsolescence-eligibility)
Tag each guard:
- **SYSTEM** (secrets, exfil, injection, destructive ops, anti-tamper, write-confirm,
  protected-repo git) → capability-orthogonal → **KEEP**, no 4.8 test.
- **Platform / quality** (inline-python quoting, MSYS/AWS auto-fixes, empty-push,
  buffering-pipe, token caps, dead-ref/index health, no-op-loop) → model-independent →
  **KEEP**; note any tunable knob.
- **Model-compensation** (search scoping, full-file reads, tool routing, param formatting,
  "verify before assuming") → verdict **hinges on 4.8** → must be tested.
Only model-compensation guards are prune-eligible. Do NOT prune SYSTEM/platform guards.

### Three evidence streams (gather all three)

**1. Live telemetry**
- `bin/hook-fire-report.py --days 30` (and `--json`) — per-hook invocations / blocks /
  crashes / p95 latency from `~/.claude/audit/hook-fires-*.jsonl`.
- `~/.claude/audit/bash-security-*.jsonl` — per-sub-guard block/auto-fix decisions.
- The `manifest_metrics` advisory-warning log — warn-only hooks (security-write-confirm).
- CAVEAT: the bash-security log is pre-4.8, test-suite-polluted, and logs blocks only
  (not approvals). Treat it as "how often the pattern is exercised," not a clean fire-rate.

**2. Retroactive transcript review (the core new work)**
- LOCATE transcripts robustly: scan `~/.claude/projects/*/*.jsonl` and any configured
  transcript path; do NOT assume `~/.claude/session-transcripts/` exists. Report count and
  date range, and note the ~7-day retention limit — state how far back you can actually see.
- For each transcript, parse JSONL and extract **guard-fire events** by scanning hook
  outputs / systemMessages / tool-block reasons for guard signatures (`[inline-python-guard]`,
  `search-path-guard`, partial-read block, `SECURITY WRITE CONFIRMATION`, `LOOP DETECTED`,
  `RETRY STORM`, `treat as data`/ASI01, `BLOCKED`, etc.). For each: timestamp, **model id
  from that turn**, the triggering tool call, and the model's next action.
- **Bucket by model**: isolate Opus 4.8 (sessions on/after 2026-05-28; model id
  `claude-opus-4-8`) vs the 4.6/4.7 baseline. Report 4.8-specific fire counts + TP/FP.
- **Classify each fire TP vs FP**: TP = the blocked/warned action was genuinely wrong/
  harmful or the correction was needed; FP = legitimate action, guard added friction.
  Judge from the model's subsequent behavior and the outcome.
- **Detect natural compliance** (the obsolescence signal): for each model-compensation
  guard, count cases where the compensated behavior happened WITHOUT the guard — model
  scoped its own Glob/Grep, read a full file before editing, routed a syntax query to Grep,
  passed `urls` as an array, verified an MCP capability before claiming "unavailable." High
  natural-compliance + ~0 TP fires on 4.8 ⇒ strong prune candidate.

**3. Active 4.8 testing (where a clean test exists)**
- `inline-python` threshold: author 8–10 realistic complex inline `python -c` snippets
  **>300 chars** (JSON parse, regex file edits, nested quotes, `r'C:\...'` paths) and execute
  them **through Git Bash / the real MSYS pipeline** on this workstation; measure escape/
  quoting failure rate. (This is the platform hazard a Linux session can't test.) Clean >300
  on MSYS ⇒ propose raising the threshold; else keep 300.
- `tavily-extract`: with the guard temporarily disabled, issue a few `tavily_extract` calls
  and check whether 4.8 passes `urls` as an array (~100% ⇒ prune candidate).
- Tool-use-policy guards (search-path, block-partial-read, vocab-divert, verify-before-assuming):
  run **disable-and-count** — disable the guard for a defined window (≥2 weeks or N sessions),
  then use the hook-fires telemetry + transcript mining to count the failure it prevents on
  4.8. Prune only if that rate is ~0. Gate any removal behind `/validate-changes`.

### Per-guard deliverable
For EVERY guard: class, fire count (4.8 vs baseline), TP/FP from transcripts, natural-
compliance rate (model-comp only), and a verdict — **KEEP / TUNE(knob) / TEST(protocol) /
PRUNE(evidence)**. SYSTEM/platform guards get one line confirming KEEP. Model-comp guards get
the full analysis. Specifically resolve: search-path-guard, block-partial-read,
code-search-vocab-divert, verify-before-assuming, tavily-extract-guard (the 5 prune
candidates), the inline-python threshold, and whether `creative-output-grounding-check` ever
fires (ARCHITECTURE.md records 0% over 119 transcripts — confirm it's not dead).

### Discipline (hard requirements)
- Ground every verdict in measured numbers, not vibes (`grading-discipline.md`). Where
  evidence is thin (low fire count, short transcript window), say so — don't overclaim.
- `check-before-change` / `verify-before-assuming`: before calling any guard obsolete,
  confirm its rationale (docstring + KB + any incident it cites). Remember the env-scrub
  lesson — an "obvious" value can be a deliberate, documented decision. Do not "fix" it.
- Never weaken or remove a SYSTEM/platform guard.
- For any PRUNE, do disable-and-count FIRST; removal is a separate, evidence-backed step.
- Consider `/roundtable` or `/persona` for an adversarial pass on the prune verdicts before acting.

### Outputs
1. Refresh `topics/hook-bitter-lesson-audit.md` with the per-guard 4.8 verdicts +
   transcript-derived TP/FP, and mirror actionable items into `topics/harness-pruning-candidates.md`.
2. A ranked report: KEEP (count) / TUNE / TEST (with running experiments) / PRUNE (with
   evidence). Lead with the methodology + data caveats.
3. Open PRs per repo convention (feature branch, ready for review). Don't delete a guard in
   the same PR as the evidence — propose, gate behind disable-and-count + `/validate-changes`.

---

## Preliminary classification (from the 2026-05-31 session — confirm with workstation data)

| Tier | Guards | Action |
|---|---|---|
| KEEP — SYSTEM | credential, credential-theft, exfiltration, reverse-shell, prompt-injection, dangerous-command, memory-write-guard, config-guard, destructive-ops-guard, result-injection-guard, prompt-secret-scan, security-write-confirm | none (capability-orthogonal) |
| KEEP — platform/quality | inline-python (tune threshold), MSYS/AWS auto-fixes, push/commit/pr/rebase, git-empty-push, bash-tail-buffering, tavily-search-cap, skill-ref-validator, code-search-chunk-drop, loop-detector (no-op half) | none / tune |
| TEST — model-compensation | search-path-guard, block-partial-read, code-search-vocab-divert, verify-before-assuming, tavily-extract-guard | disable-and-count on 4.8 |
| VERIFY-LIVENESS | creative-output-grounding-check (0% fire smell) | confirm it can fire |

Only ~5 of ~20 guards are even obsolescence-eligible; the rest are permanent by nature,
which is the correct answer for a security harness. The data caveats (pre-4.8, test-polluted,
blocks-only audit log; ~7-day transcript retention) are why this must run on the workstation
with live telemetry rather than from a one-off session.
