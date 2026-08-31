# Audit remediation — 2026-07-26

Working record for the remediation of the three review reports
(`claude-config-detailed-review`, `claude-sessions-14d-review`,
`claude-review-red-team`). The red-team report is treated as the correction layer
wherever the reports conflict.

This document states what was verified, what shipped, what is deliberately
deferred, and what needs an explicit decision. It is the handoff surface.

---

## Repository drift vs the reports

The reports reviewed `main` at `3fc8d65d`. Two commits landed after that
(`6b4480a6`, `e6a8961b`), so the static findings are essentially current.

One drift fact materially affects how the reports should be read:

> The **local checkout was 14 commits BEHIND** the review baseline, not ahead.
> `3fc8d65d` (the reviewed commit) is a *descendant* of the local `HEAD`
> (`e3d1fc9a`). So "the report says X but my file says Y" would have been a
> stale-base artifact, not a report error.

All remediation work was therefore branched from `origin/main` (`e6a8961b`), never
from the local `HEAD`.

`PR #1709` (`agent/activate-safety-net-plugin`) is already open and covers
finding **C1** (inactive marketplace plugin). No C1 work was duplicated here.

---

## Platform contracts pinned verbatim

Every contract below was re-verified against first-party docs on 2026-07-26 and is
quoted, not paraphrased. Two of them contradict a report claim.

| Contract | Verbatim finding | Effect |
|---|---|---|
| Fixed thinking budgets | *"Fable 5, Sonnet 5, and Opus 4.7 and later always use adaptive reasoning. The fixed thinking budget mode and `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING` do not apply to them."* / *"Other values apply only with a fixed thinking budget."* | `MAX_THINKING_TOKENS=65536` is inert → removed |
| `SessionStart` matchers | `startup, resume, clear, compact, fork` | `compact` exists → the PreCompact→SessionStart(compact) ledger design is implementable |
| `PostCompact` | *"Runs after Claude Code completes a compact operation. Use this event to react to the new compacted state, for example to log the generated summary or update external state."* | No decision control, no context injection. Red team **upheld** |
| `PreCompact` | *"Exit with code 2 to block compaction… You can also block by returning JSON with `"decision": "block"`."* | **Stronger than reported**: a ledger-persist failure can fail *closed* |
| `PreToolUse` `ask` | *"`"ask"` prompts the user to confirm"* and *"A hook's `"ask"` also forces a permission prompt in auto mode: the classifier can still deny the tool call, but it can't approve the call silently."* | The H1 fix is exactly correct, and load-bearing under this host's `auto` default |
| `TaskCreated` | *"Runs when a task is being created via the `TaskCreate` tool."* | Does **not** cover direct Agent/Workflow dispatch. Red team **upheld** |
| `ConfigChange` | Matchers include `user_settings`, `project_settings`, `local_settings`, `policy_settings`, `skills` | Fires for policy settings too; only the *blocking authority* over policy remains open |
| Subagent frontmatter | Supported: `name, description, tools, disallowedTools, model, permissionMode, maxTurns, skills, mcpServers, hooks, memory, background, effort, isolation, color` | `allowedAgentTypes` absent → unsupported, removed |
| `tools` omitted | *"Inherits every tool available to subagents if omitted."* | Omitting `tools` is a **grant of everything** |
| Nesting default | *"By default, a subagent can't spawn subagents of its own… While nesting is off, Claude Code withholds the `Agent` tool from every subagent except a fork, which inherits the parent's full tool list."* | **CONTRADICTS** the 14-day report's "2.1.219 made depth-three the default" |
| `mcpServers` | *"MCP servers available to this subagent."* | Additive (a grant), not a restriction. Red team **upheld** |
| Project MCP trust | *"A cloned repository can't approve its own servers: `enableAllProjectMcpServers` or `enabledMcpjsonServers` committed to the project's `.claude/settings.json` is ignored in an untrusted folder"* — **but** approvals from *"your user `~/.claude/settings.json`"* *"still apply in an untrusted folder"* | See H2 note below |
| `anthropic/requiresUserInteraction` | Prompts *"on every call, even in `acceptEdits`, `auto`, and `bypassPermissions`"*, no "don't ask again", allow rules *"don't skip the prompt either"*. But *"In `dontAsk` mode, which never prompts, Claude Code denies the call instead"*, and with `--permission-prompt-tool` an allow *"is converted to a deny"* | Strong for owned MCP mutations; **not** a complete consent system. Red team **upheld** |

### H2 — the mechanism matters

The red team narrowed H2 to "workspace trust prevents a newly cloned repository
from silently approving itself", which the quoted text confirms. But note *where
our setting lives*: `enableAllProjectMcpServers: true` is in the **user**
`~/.claude/settings.json`, and user-settings approvals **do** still apply in an
untrusted folder. So the setting genuinely does auto-approve project servers once a
folder is trusted, and the red team's "still enlarges exposure after trust" stands.
Setting it to `false` with an explicit `enabledMcpjsonServers` allowlist remains
the correct fix. Not applied here — it changes MCP connection behaviour for every
project and warrants its own change.

### Report claims invalidated or corrected

1. **"2.1.219 increased default nested-subagent depth from one to three"** —
   current docs say nesting is **off by default**. The red team was right to flag
   this as an unresolved first-party conflict; the documentation side says
   disabled. This *lowers* the severity of the unrestricted-`worker` finding,
   though the **fork exception** means `Agent` is still reachable.
2. **"15 registered hook event families"** — the live settings register **14**
   (measured from the enforcement surface by `bin/acceptance_probe.py`). Red team
   confirmed.
3. **OTel** — **CORRECTED 2026-08-06**: the earlier conclusion that OTel was
   disabled was unsupported. Anthropic documents `CLAUDE_CODE_ENABLE_TELEMETRY=1`
   as the OTel enable control; `DISABLE_TELEMETRY=1` is not documented as its
   kill switch, and user-source absence does not rule out a higher-precedence
   managed value. Repository templates request metadata-only logging, while the
   winning startup state and backend receipt remain separately unverified.

### Newly found, not in any report

**`READ_ONLY_PATTERNS` matched read verbs as raw substrings**, so a read verb
inside another word marked a security operation read-only and allowed it silently.
`exfiltrate_widget` matched `get` inside "wid**get**"; `budget_set`,
`target_delete` and `widget_purge` would have passed unreviewed on a
mutation-capable server. Found by writing the unclassifiable-operation negative
fixture. Fixed by anchoring verbs on `_`/string boundaries.

---

## Workflow journal structure — measured, not assumed

Read-only probe of **108 local journals** (2026-07-26):

* Journals carry exactly **two** record types: `started` and `result`.
  `started` keys = `[agentId, key, type]`; `result` keys = `[agentId, key, result, type]`.
* There is **no terminal workflow record type** and **no run-level metadata file**
  anywhere on disk. Run success is *not answerable from the journal alone*.
* `result` payloads are **schema-free**: 990 dicts (arbitrary StructuredOutput
  keys — `verdict`, `findings`, `existence_ratio`, …) and 107 bare strings. No
  status field, no error field, no receipt.
* **55 of 1151** logical children have no result record, across **17 of 108** runs.
  **5 runs produced ZERO child receipts** — one after dispatching 12 children.
* **0** children reported an error verdict.

That last pair is the design-critical finding: **every truth gap is silence, not a
reported failure.** So the remedy is receipt *coverage plus a conservative
aggregation rule*, not better parsing of the result payload.

### Denominator honesty

The reports' **2/46** counted runs that *claimed* `completed` while every final
child errored — they had the orchestrator's claimed state. The replay here has **no
run-level metadata to read**, so it can only report "evidence does not support a
success claim" = **17/108**. These are different denominators answering different
questions and must not be presented as restatements of each other.

---

## What shipped

### Phase 0 — reproducibility and rollback

| File | Purpose |
|---|---|
| `bin/config_rollback.py` + tests | Version-pinned config snapshot / one-command rollback |
| `bin/acceptance_probe.py` | Records **effective** state, not configured |

`config_rollback` safety properties: `snapshot` refuses to overwrite an existing
id; `restore` writes a **pre-restore snapshot first** so a rollback is itself
reversible; `restore` refuses to write without `--confirm`; it never deletes
live-only files; and it excludes transcripts/memory because *a rollback must never
rewrite the record of what happened*.

`acceptance_probe` records hook **registrations** (event / matcher / timeout) —
the registration is the enforcement surface, not what a script contains — plus
permission counts, MCP registry, and explicit `unverified` markers for dimensions
whose effective value cannot be observed.

### Phase 1 — truthful workflow state and durable receipts

| File | Purpose |
|---|---|
| `bin/workflow_truth.py` + 25 tests | Terminal state derived from evidence |
| `bin/workflow_truth_replay.py` | Read-only shadow replay, half-open `[start, end)` windows |
| `bin/run-status.py` (extended) + 11 tests | Durable receipts + verified-success gate |

`workflow_truth` keeps `completed_success` / `completed_partial` / `failed` /
`killed` **distinct**, so a deliberate kill is never scored a defect (red-team
correction). Missing or unknown required results are PARTIAL or FAILED, **never**
success. Attempt lineage is preserved so legitimate retries don't condemn a run,
while a retry that vanished cannot inherit a superseded attempt's success.

`run-status.py done` now **refuses to write `.done` without evidence**
(`--verify-cmd`, `--verified-by`, or an explicitly-marked `--force`). Previously
any caller could assert success with none — the same summary-as-success defect the
journals exhibit. This mirrors `durable_run.success_marker`, which already had the
gate.

### Phase 2 — consent enforcement

`hooks/security-write-confirm.py` now returns a real
`permissionDecision: "ask"` instead of an advisory `systemMessage`, and fails
closed in three previously-silent cases: unresolvable wrapper envelopes,
unclassifiable operations on security servers, and mid-word read-verb matches.

`ask` (not `deny`) is deliberate — it preserves bulk workflows by prompting rather
than hard-failing. `SECURITY.md` and `rules/security-confirmations.md` were
corrected: they described the hook as "advisory-by-design", which was not an
enforcement mechanism.

**OPA is a different control.** It gates *authorization*; the hook gates human
*consent*. OPA cannot establish that a human approved a specific target, so
neither substitutes for the other.

### Phase 3 — worker privilege boundary

| File | Change |
|---|---|
| `agents/worker.md` | `disallowedTools: [Agent]` |
| `scripts/validate-agent-frontmatter.py` + 12 tests | CI gate on agent frontmatter |
| `.github/workflows/validate.yml` | wires the gate in |
| `agents/README.md`, `agents/TEMPLATE.md` | when to use `tools:` vs `disallowedTools:` |

**Scope narrowed from the reports, on evidence.** The reviews proposed splitting
`worker` into researcher / bounded-writer / verifier / orchestrator. Reading the
actual routes first showed all **20** are domain-tool query/operations (Ramp,
Ashby, Linear, Tailscale, Jamf, Box, Athena, Hologram, …) — there is no
orchestrator route and no writer route among them. Building four roles would have
created three agents nothing dispatches. The finding (`worker` has no `tools:`, so
it *"Inherits every tool available to subagents"*) is real; the fix is one deny.

**Why `disallowedTools` and not a positive `tools:` allowlist.** The reports'
"positive allowlists" advice is right for narrow specialists — and the five
specialists here already do it. For a deliberately generic worker fronting ~34 MCP
servers it would require enumerating every MCP tool by name, and the reference
warns *"If no entry in the list resolves to a tool, the subagent usually fails to
launch"*. One renamed MCP tool would break dispatch, making the "hardening" a
reliability regression. Deviation recorded rather than applied silently.

`Agent` is denied even though nesting is off by default, because of the documented
fork exception: *"Claude Code withholds the `Agent` tool from every subagent except
a fork, which inherits the parent's full tool list."*

The new CI gate covers the class, not just this instance: unsupported frontmatter
fields now fail (`allowedAgentTypes` could sit in `worker.md` looking like
enforcement precisely because nothing validated agent frontmatter), and an agent
declaring neither `tools` nor `disallowedTools` warns. Mutation-verified across
four cases including UNKNOWN-vs-FAIL (exit 2 on an unreadable directory, so a
broken run cannot read as a pass).

### H3 — `[gone]` branch pruning no longer destroys unpushed work

| File | Change |
|---|---|
| `hooks/session_start_modules/repo_sync.py` | ancestry check + recovery ref + `-d` |
| `hooks/post-merge-sync.py` | same guards at the duplicated call site |
| `hooks/test-hooks/test_repo_sync.py` | +9 fixtures (18 total in the file) |

**The false premise, quoted from the code it justified:**

> `-D` (force) is safe here because gone-upstream means GitHub already accepted
> and removed the remote — local-only divergent history is not possible without a
> separate non-tracking branch.

`[gone]` is a fact about the **upstream ref**, not about local history. Any commit
made after the last push is invisible to it, which is routine.

**Reproduced on a disposable repo**, then re-run against the fix — same scenario, a
`[gone]` branch carrying one never-pushed commit:

| | old code (`branch -D`) | new code |
|---|---|---|
| `track_state` | `[gone]` | `[gone]` |
| tip contained in `main` | `False` | `False` |
| branch survives | **`False`** | `True` |
| commit still named by | **`''`** (reflog only) | `'feature'` |
| branches deleted | 1 | 0 |

Three guards now, in order: **(1)** the tip must already be contained in an
accepted base (`origin/main`, `origin/master`, `main`, `master`); **(2)** a
recovery ref is written under `refs/gone-recovery/<branch>` *before* deletion;
**(3)** `-d` instead of `-D`, so git independently refuses anything unmerged even
if guards 1–2 were wrong.

A branch failing the check is **left alone**. Accumulating a stale branch is
cosmetic; deleting someone's only reference to unpushed work is not. `post-merge-sync`
additionally reports `N PRESERVED (unmerged local commits)` so the skip is visible
rather than silent.

**Recovering a pruned branch:**

```sh
git for-each-ref refs/gone-recovery/          # what was deleted, and its tip
git branch <name> refs/gone-recovery/<name>   # restore it
git update-ref -d refs/gone-recovery/<name>   # tidy up once satisfied
```

One boundary case is pinned by test: a branch at the *same commit* as `main` has
zero divergence, so it genuinely is contained in `main` and remains deletable. The
guard asks "is this tip already reachable?", not "does this branch have its own
name" — the first fixture I wrote got this wrong and the test caught it.

The two call sites duplicate the logic by design (`post-merge-sync.py` must stay
import-free of the session-start package); both carry the same guards and a comment
saying to change them together.

### Phase 4 — acceptance ledger (dual-run)

| File | Role |
|---|---|
| `hooks/session_ledger.py` + 35 tests | Atomic per-session acceptance ledger |
| `hooks/precompact-ledger.py` | `PreCompact` → persist + stamp compaction |
| `hooks/session_start_modules/ledger_rehydrate.py` | `SessionStart(compact/resume/fork)` → **inject** |
| `hooks/postcompact-audit.py` | `PostCompact` → **audit only** |
| `hooks/test-hooks/test_precompact_ledger.py`, `test_postcompact_audit.py` | 19 hook tests |

This closes a documented open item. `ARCHITECTURE.md` previously read: *"Nothing
currently reads `.precompact-state.json` for recovery — preserving real in-progress
state across compaction is an open item (08-b4 report)."* Confirmed by grep: the
only references to that file were a cleanup list and its own tests. The old
checkpoint wrote a static hint (*"Re-read CLAUDE.md, check git status"*) with **no
acceptance state and no consumer**, so there was no rehydration path at all.

Design decisions worth recording:

* **Fails open, deliberately.** `PreCompact` *can* block (exit 2), and this does
  not use it. Auto-compaction fires near the context limit, so blocking converts a
  recoverable hiccup into a session-ending failure — the rationale already
  documented in `precompact-checkpoint.py`. My earlier "can fail closed" note was
  a capability observation, not a licence; overriding that prior decision would
  have re-introduced a known session-corrupting failure.
* **Atomic writes** (temp + `os.replace`): a torn ledger is worse than an absent
  one, because a reader cannot distinguish truncated from complete.
* **Rejected entries render first and are never evicted** under the entry budget.
  Reintroducing an already-rejected option is the specific documented drift mode.
* **Scoped to continuation sources.** Injection fires on `compact`/`resume`/`fork`
  and refuses on `startup`/`clear` — a prior conversation's requirements must not
  be presented as a fresh session's.
* **One file per session**, avoiding the shared-file read-modify-write contention
  M10 identified.
* **Durability half only.** A PreCompact hook receives session metadata, not the
  conversation, so it cannot infer intent. Claiming otherwise would be the
  "heuristic-as-telemetry" anti-pattern the review named.
* **Causality NOT assumed.** The red team retracted the "compaction caused the
  correction concentration" claim; this makes acceptance state durable so the
  hypothesis becomes testable, without asserting the cause.

**Old checkpoint deliberately retained** — dual-run until parity is measured.

A second bug was caught here by fixtures-first: the `PostCompact` audit initially
compared a stop-word-stripped probe against an unstripped summary as a *contiguous
substring*, so `"produce the handoff document"` looked missing from a summary
containing it verbatim. Nearly every entry would have reported as dropped,
including the `rejected_dropped` alarm — and an alarm that always fires trains
operators to ignore it, burying the real signal. Fixed to token containment; the
residual limitation (morphological variants read as missing) is documented and
pinned by a test rather than papered over with stemming.

---

## Deliberately NOT done (needs a decision)

### ~~Phase 3 — narrowing the generic `worker`~~ — SHIPPED (narrowed scope)

See "Phase 3 — worker privilege boundary" under *What shipped*. One item is
deliberately left for you: pinning `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`.

**Why I did not pin it.** `rules/subagent-verification.md` records a deliberate
decision dated **2026-07-24** (two days before this work):

> `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1` disables nesting — **DEFERRED** here
> 2026-07-24: depth-1 would break worker parallel-sub-dispatch; trigger = a local
> over-spawn incident.

The variable is currently unpinned in both `settings.json` and the live config, so
the fleet relies on a default that the subagents doc (nesting **off**) and the
2.1.219 changelog (**depth 3**) disagree about. Pinning it explicitly is the right
end state.

But two things stopped me from doing it autonomously. First, the stated trigger — a
local over-spawn incident — has **not** occurred, so setting it now overrides a
current decision on its own terms. Second, the decision's *reason* is contradicted
by this phase's measurement: `worker` does not sub-dispatch (all 20 routes are
domain queries; the parent fans out). A wrong reason is grounds to **re-decide**,
not grounds for me to reverse a two-day-old deliberate choice unilaterally.

Denying `Agent` on `worker` achieves the same protection for the agent in question
without touching a fleet-wide default, so the exposure is already reduced.

**Your call:** pin `"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1"` (nesting off,
matching what `worker` actually needs), pin `"2"` or `"3"` to make the current
behaviour explicit, or leave it unpinned and update the rule's stale rationale.

### Original Phase 3 proposal (superseded, kept for the record)

The finding is real: `agents/worker.md` has **no `tools:` allowlist**, and per the
verified contract that **inherits every tool available to subagents**.

Measured context that changes the risk picture:

* **20 of 20** agent routes in `skill-rules.json` point at `worker`. It is the
  single most load-bearing agent in the architecture.
* Nesting is **off by default**, so `worker` cannot spawn subagents today — except
  via the documented **fork** exception.
* `worker.md`'s body never instructs sub-dispatch, and already tells it that
  remote MCP calls fail from subagents.

So this is a **latent over-grant**, not active fan-out risk. Narrowing the tool
set on the agent behind every route is a behavioural change with real breakage
potential, so it is proposed rather than applied:

- split into `researcher` (read-only), `bounded-writer`, `verifier`, and
  `orchestrator` roles;
- give **only** `orchestrator` the `Agent` tool;
- positive `tools:` allowlists per role plus explicit MCP denials;
- pin `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` explicitly rather than relying on a
  disputed default;
- negative probes for direct, nested, **forked**, background, Bash-mediated and
  MCP-mediated bypass.

### ~~Phase 4 — lifecycle ledger~~ — SHIPPED (dual-run)

See "Phase 4 — acceptance ledger" under *What shipped*. `SessionEnd` and the Stop
split remain deferred; the compaction half is done and dual-running.

### Accepted as-is (owner decision, 2026-07-26)

- **H2 `enableAllProjectMcpServers: true`** — kept. The friction of per-repo MCP
  approval across the clone-and-inspect workflows outweighs a risk that is bounded
  to *already-trusted* repos, and the H1 `ask` gate now covers the mutation path
  that actually causes harm. Mechanism and exact fix recorded above if the threat
  model changes.
- **`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`** — left unpinned. Low impact:
  `worker` already denies `Agent`, so the disputed default cannot be reached
  through the agent behind all 20 routes.
- **OTLP bearer token** — not rotated.

### Second pass — the "gates that don't gate" class (H4, M4, M5, L1)

All four were re-verified as live on `1dfdebef` before any change; none was stale.
They share one shape: **a control that reported OK while not actually checking.**

**H4 — blocking-guard timeout drift.** Measured **44 of 57** shared hook
registrations drifted, including *every* blocking security guard
(`bash-security-guard` 30→3, `destructive-ops-guard` 30→3, `pre-agent-dispatch`
30→3, `security-write-confirm` 30→3). A timed-out PreToolUse hook never returns its
decision, so the action proceeds **unguarded** — and measured wrapper start-up alone
is 1.4–4.1s, so a 3s budget can kill a guard before its body runs. A fresh/example
install was therefore materially weaker than the live host in the layer meant to be
strongest. `architecture-drift-check` reported OK throughout because it compared
event names and script presence but **never timeouts**.

Fixed on all **three** independent sources (live, example, installer): 42 example
timeouts and 19 installer timeouts aligned to live; drift is now **0 of 55**. The
gate now enforces two conditions on blocking events — the example may not be
*lower* than live, and no blocking guard may sit at or below a 10s floor in either
file. A third defect surfaced while fixing: the installer wires `config-guard` and
`memory-write-guard` as two standalone 3s hooks where live routes them through one
`write-edit-dispatcher` at 30s — budgets are now matched and the **topology
divergence is documented in-place** rather than silently papered over (restructuring
the installer is M1–M3 scope).

**M4 — the skill-rubric CI gate was fail-open.** `if <checker>; then echo ok; fi`
with no `else`: in Bash a false condition with no `else` leaves the compound command
successful, so a below-threshold skill printed `::error::` and the required check
went green. Verified live — `search-campaign` scored 12/14 while CI passed. The exit
contract moved **into the tool** (`--gate N` exits 1) rather than YAML shell logic,
and is honoured across every output mode (a dropped `gate_rc` on the default tabular
path was caught during verification — it printed "GATE FAILED" and still exited 0).
`search-campaign` was then genuinely fixed to 14/14 by adding the missing worked
example and five evaluations, so the gate ships **green**, not red.

**M5 — the manifest graph was not queryable.** Both documented queries crashed with
`TypeError: argument of type 'NoneType' is not a container or iterable`, because
`dict.get("matcher", "")` returns `None` when the key exists with a *null* value —
the default only covers a *missing* key, and matcher-less events legitimately carry
`matcher: null`. Normalized via a single `_matcher()` helper. Separately,
`compile.py --check` exited 0 with five manifests still carrying `TODO_EVENT` /
`TODO_MATCHER`, so the graph encoded placeholder topology as fact. Placeholders are
now rejected — in **values** only, so an honest `# TODO:` comment still passes. The
five were corrected by category rather than filled with guesses: two registered
hooks got real values read from live settings; `rule-size-guard` records its intended
event **plus an explicit "not registered, does not currently fire" note**; and
`hook_input` (a shared library imported by 3 hooks) and `sync-repo` (a CLI) were
never hooks at all — their event/matcher are now `null` so queries cannot report
them as enforcement. Guessing a plausible event for those two would have been worse
than the placeholder.

**L1 — docs overstated behavior.** Each claim was checked against source, not the
report. `README` listed `settings.json` as "Platform-neutral" while both settings
files invoke macOS-only `afplay`. `SECURITY.md`, `ARCHITECTURE.md` and
`hooks/README.md` claimed a JSONL audit trail for *every* Bash security decision,
while `bash-security-audit.py` explicitly `return`s on `passthrough` events **and**
no-ops entirely at `CLAUDE_EFFORT=low` — so it is not a complete record (the
blocking guard still runs in both cases; only the log is reduced). `SECURITY.md`
also listed CodeQL/Trivy/Checkov/cosign as local CI controls when this repo
implements **Gitleaks only** and the container scanning belongs to other repos'
pipelines. All corrected with the qualification stated inline.

### Still not attempted

`H5` (marketplace bundle self-containment — packaging was just reworked by #1709;
re-measure before touching), `H7` (retrospective extractor rebuild — a genuine
rewrite: record-oriented event model, ID dedup, cumulative-usage handling, ~8
fixture families; deserves its own arc), `M1–M3` (installer menu capture, overwrite
without warning, stale catalog — one "installer correctness" PR), `M6` (mirror
workflow contract), and `M7–M11` (of these, **M10** — Stop-hook telemetry
contention — is the most defensible next step and interacts with the acceptance
ledger shipped above).

(H3 — `[gone]` branch force-delete — **is** now done; see its section above.)

---

## Sensitive-artifact handling

The analysis `work/` tree (~91 MB) is **not** distribution-safe and was not
committed. Nothing from it is quoted here.

Most credential-pattern hits in that tree are the repo's own detector patterns and
test fixtures inside two full clones — not live secrets.

**One genuinely sensitive value**: a 48-character bearer token embedded in
transcript-derived JSON, captured from a launch-agent plist
(`OTEL_EXPORTER_OTLP_HEADERS`, endpoint `service.mcp.example.internal`). It is an **OTLP
telemetry ingest credential**, not an identity or cloud credential. It appears
only in transcript tool-results and bench JSON — **not** in any live launch agent
or `settings.json`. The value was never printed during this review; it was
identified by context and a truncated hash.

Rotation is **low-risk and supported**: `mcp-infra` manages this with
`OTEL_BEARER_TOKEN` **plus** `OTEL_BEARER_TOKEN_PREVIOUS` and an
`otel_token_rotation` module — a two-slot design, so rotating does not break
collectors mid-flight. **Recommended: rotate it**, then sanitize or delete the
derived artifacts. Requires your authorization (external system).

---

## Verification

| Check | Result |
|---|---|
| `pytest bin/ -q` | 60 passed (run from outside the repo, so no cwd dependency) |
| `pytest hooks/test-hooks/test_security_write_confirm.py -q` | 46 passed |
| `bin/architecture-drift-check.py` | exit 0, gate OK |
| `scripts/validate-hook-paths.py` | exit 0 |
| `manifests/compile.py --check --no-reindex` | exit 0 |
| `bin/reconcile-skill-tools.py --all` | exit 0 |
| `config_rollback snapshot` / `diff` | 258 files pinned to `e6a8961b`; diff clean |
| `workflow_truth_replay` (108 journals) | 91 success / 12 partial / 5 failed; receipt coverage 0.9522 |
| `acceptance_probe` | `MAX_THINKING_TOKENS='65536'` → INERT; 14 hook events; **ask rules: 0** |
| Live ledger lifecycle e2e | persist (`compaction_count` 2, 4 entries preserved) → inject on compact/resume/fork, refuse on startup/clear/empty → audit **caught the dropped rejection** |
| `pytest` ledger + pre-existing compaction/session-start tests | 65 passed (old checkpoint path unbroken) |

`ask rules: 0` independently corroborates H1: before this change there was no
`ask`-tier enforcement configured anywhere.

## Rollback

```sh
# configuration (live ~/.claude)
python3 bin/config_rollback.py list
python3 bin/config_rollback.py diff    --id known-good-2026-07-26-pre-remediation
python3 bin/config_rollback.py restore --id known-good-2026-07-26-pre-remediation --confirm

# repository changes
git -C <repo> log --oneline origin/main..fix/audit-remediation-2026-07-26
git -C <repo> revert <sha>          # per-commit
```

Every commit on this branch is additive or surgical; the two `settings*.json`
edits are a single deleted line each with no serialization churn.

---

# Pass 3 — remaining M-tier findings (branch `fix/audit-pass3`, base `d2901c98`)

Every finding below was re-verified as **live** before any change; none was
stale. Each fix ships with the gate that would have caught it, and **every new
gate was mutation-verified by watching it fail on the state it exists to catch**.

## What was fixed

| # | Finding | Was | Now |
|---|---|---|---|
| 1 | audit-skill CI gate | verdict came from `grep -q "^FAIL"` on prose, with `--ndjson` truncation risk from SIGPIPE | `--all --strict`; the tool's exit code gates |
| M8a | `hooks/sync-repo.py` | `cmd_pull` returned `None`; `main()` had no `sys.exit`, so N failed repo syncs still exited 0 | returns the failure count; `sys.exit(main())` |
| M8b | `repo_sync.py` auto-checkpoint | `checkout -b` / `add -A` / `commit` return codes discarded; failed `checkout -b` left the next two mutating the WRONG branch. Unchecked `fetch` → rebase onto a **stale** ref | each step checked; aborts and preserves the dirty tree; fetch failure skips the rebase |
| M7 | `SECURITY.md` supply chain | claimed `persist-credentials: false` on **all** checkouts (false — `gitleaks.yml` persisted the token across a third-party scan) and `pip-compile` lock files (false — none exist) | workflow fixed so the first claim is true; the second retracted with the real state, the accepted scope, and why closing it needs three platform locks |
| M10 | friction telemetry | unsynchronized read-modify-write of a **tracked** KB topic on every turn; **measured 5/5 trials losing a concurrent session's record** | per-session spool outside all repos + locked rollup; spool bounded |
| M1 | installer menus | `$(ask_choice …)` captured the whole menu, so **every** numbered branch fell through to skip — measured: 0 rules installed | menus → stderr, value → stdout; helpers extracted to be testable |
| M2 | starter collision inventory | checked 5 paths, copied 11 — 6 files silently overwritten while reporting "existing files kept" | one manifest feeds both |
| M3 | skills catalog | "All portable skills (51)" against **105**; 3 wrong category counts; 4 dangling names | counts computed; dead names removed (verified absent repo-wide) |
| M6 | mirror workflow | `--all` mirrored only main, `--tags` pushed **zero** tags, `delete:` pruned nothing | main + tags explicitly, tags fetched first, dead trigger removed |

**M5 was already shipped in PR #1730** (manifest null-matcher fix + placeholder
gate) and verified present on `main`; it needed no rework.

## Two recurring patterns worth naming

**A doc claim is a testable assertion.** Three claims in this pass were simply
false (`persist-credentials`, `pip-compile` locks, the mirror's flags). Where the
claim could be made true, it was, and a test now pins it; where it could not
(platform-specific locks), the doc records the real state and a **negative** test
stops the retracted claim from silently returning.

**Assert on the artifact, not a proxy** (`rules/tdd-mutation-testing.md` item 18).
`test_friction_header_is_canonical` grepped the hook SOURCE for a literal
f-string; the M10 refactor moved rendering behind a dict lookup, so the proxy
broke while the rendered format was unchanged. It now asserts on rendered output
— strictly stronger. Three of my own new tests hit the mirror-image trap, where a
whole-file regex matched the very string quoted in the test's own docstring or in
a warning comment; each was narrowed to the executed command lines.

## Verification (final state of the branch)

```
pytest hooks/test-hooks/ bin/ scripts/ manifests/ -q  ->  1519 passed, 49 skipped, rc=0
                                                          (was 1489 at pass-2 exit; +30)

architecture-drift-check.py     -> rc=0
validate-hook-paths.py          -> rc=0
validate-skills.py --gate 13    -> rc=0
manifests/compile.py --check    -> rc=0
validate-agent-frontmatter.py   -> rc=0
audit-skill.py --all --strict   -> rc=0
bash -n install.sh              -> rc=0
mirror.yml                      -> parses as YAML
```

Empirical checks beyond the suite:

- installer, throwaway `HOME`, choice = "pick individually" + one `y`
  → **pre-fix: 0 rules installed** ("Skipping rules"); **post-fix: 1 rule, menu visible**
- mirror, two local bare repos → canonical branch + **both** tags; feature branch
  correctly excluded; **0 tags before the new fetch step, 2 after**
- friction concurrency test run **10× consecutively** → 10/10 stable

## Still not attempted

H5 (packaging reworked by #1709 — re-measure first), H7 (extractor rebuild
deserves its own arc), M9, M11.

## Owner decision recorded

M6 mirror contract: **canonical-only (main + tags, no pruning)**. The
fetch-all-refs + `--prune` alternative was declined because it re-introduces the
per-feature-branch CI churn the workflow deliberately removed.
