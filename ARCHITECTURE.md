# Architecture

How this Claude Code harness is put together, and why each layer exists.

There are five extension layers, inside Claude Code's native permission and
sandbox boundary. They differ in **when they load** and **whether the model can
decline them** — that second axis is the one that matters.

| Layer | Loads | Model can ignore it? |
|---|---|---|
| **Hooks** (73 available; 3 in the default) | on matching tool calls | **No** — enforced by the runtime |
| **Rules** (38) | always, in context | Yes (they are text) |
| **Skills** (81) | on invocation | Yes |
| **Agents** | on dispatch | Yes |
| **Reference docs** | on demand | Yes |

## Deployment profiles

The inventory is not the default installation.

See `docs/fresh-laptop-control-audit.md` for the evidence behind the split and
the first demoted conflict.

| Profile | Ambient rules | Wired hooks | Intended use |
|---|---:|---:|---|
| **Fresh laptop** | 2 | 3 | portable kernel; simple, fast, correct |
| **Brandyn operator** | 3 | 6 | personal delivery, authority, non-progress, and secret controls |
| **Author workstation** | 36 | 53 | explicit opt-in for the compatible advanced set |

The fresh-laptop profile uses `acceptEdits` and lets sandbox-contained Bash run
without prompts. Commands that need to escape the sandbox return to the normal
permission flow. It does not grant blanket `Bash` permission. This preserves
delivery speed without stacking auto mode, blanket Bash authority, custom
guards, and a disabled sandbox into one difficult-to-reason-about control plane.

The `brandyn-operator` overlay preserves that kernel while adding only controls
tied to the owner's recurring work. It is the middle layer between the portable
core and the full author mirror; it does not load the historical rule corpus or
reinstate completion-language blocking.

Organization-specific runtime capability belongs behind a separate plugin
boundary that the profiles here do not enable: an overlay may reference an
external marketplace only once the plugin it names exists and resolves, because
Claude Code reports a missing plugin at every startup. Such a plugin must not
own the sandbox, permissions, generic Bash policy, or ambient rules, so the
portable harness remains independently installable and understandable.

The Bash hook has one always-on catastrophic core. Delivery, portability, and
workflow preferences are opt-in tables evaluated by that same process. This
keeps credential exposure, exfiltration, reverse shells, security-control
disablement, and broad destruction deterministic without turning personal Git,
AWS, Windows, polling, or prose conventions into universal safety policy.

## 1. Hooks — programmable enforcement

`hooks/` holds Python that the Claude Code runtime executes around tool calls.
A `PreToolUse` hook can **block** a call outright. Hooks complement native deny
rules and OS-level sandboxing; they are reserved for semantic constraints those
native controls cannot express.

The design premise: **the agent is a privileged but untrusted actor.** It holds
tools that can destroy data, so "the model was told not to" is not a control. A
guard that matches command *text* has no memory to wear down and returns the same
verdict every time.

Representative hooks:

| Hook | Event | Blocks |
|---|---|---|
| `bash-pretooluse-dispatcher.py` | PreToolUse(Bash\|PowerShell) | (runs the six unconditional Bash hooks — bash-security-guard, destructive-ops-guard, git-destructive-checkout-guard, bash-tail-buffering-guard, zsh-dialect-guard, poll-loop-nudge — in one interpreter; the first exit 2 wins, a rewrite feeds the hooks after it) |
| `bash-security-guard.py` | PreToolUse(Bash) | catastrophic credential, exfiltration, code-execution, security-disablement, and destructive shapes; optional policy tables |
| `output-secret-redact.py` | PostToolUse | secrets in tool output |
| `prompt-secret-scan.py` | UserPromptSubmit | pasted credentials |
| `read-deny-guard.py` | PreToolUse(Read) | reads of denied paths |
| `bash-tail-buffering-guard.py` | PreToolUse(Bash) | `producer \| tail` shapes that hide output |
| `memory-write-guard.py` | PreToolUse(Write) | oversized memory entries |
| `session-start.py` | SessionStart | (composes startup context) |

Hooks are wired in `settings.json` — see `settings.example.json`. Default and
load-bearing hooks have direct behavior tests in `hooks/test-hooks/`; every
wired command hook also receives path and crash-safety checks. The auxiliary
hook audit reports direct-test coverage gaps rather than claiming every source
file has a dedicated test.

## 2. Rules — always-loaded engineering discipline

`rules/*.md` are always in context, so they are a **budget**, not a dumping
ground. Each is a decision contract: invariants, required checks, forbidden
shortcuts, and override guards.

Most exist because something broke. The narrative sits separately in
`rules/incidents/`, and long-form rationale in `docs/rule-reference/` — both
loaded on demand. That split is deliberate: the *contract* is short enough to
stay resident, and the *story* is available when diagnosing.

Load-bearing examples:

- `verify-effectiveness.md` — source / configured / deployed / live / measured are
  distinct states, and the ladder runs both ways.
- `diagnose-before-fix.md` — read the actual error before proposing a fix.
- `verify-before-assuming.md` — a zero from an unqualified instrument means
  *unknown*, not *absent*.
- `check-before-change.md` — recover the rationale before changing a default.
- `scope-discipline.md` — ship the requested deliverable before building tooling
  to make shipping easier.

`rule_context_budget.py` and `rule-size-guard.py` keep this layer from growing
without bound.

## 3. Skills — invocable procedures

`skills/<name>/SKILL.md` with frontmatter describing when to use it. Claude picks
one by matching the description, so **the description is the routing logic** —
it should say what triggers the skill *and* what should not.

Bigger skills push detail into `references/` so `SKILL.md` stays scannable.
`scripts/` holds deterministic helpers, because anything that must be exact
should not be re-derived by a model each run.

Clusters here: planning (`superplan`, `supergoal`), knowledge
(`capture`, `recall`, `distill`, `garden`), verification
(`validate-changes`, plus the installed `superpowers:verification-before-completion`), security review
(`semgrep`, `codeql`, `fp-check`, `threat-model`), research
(`deep-dive`, `gather-*`, `scout*`), and meta-maintenance
(`audit-*`, `healthcheck`, `context-budget`, `harness-prune`).

## 4. Agents — bounded delegation

`agents/*.md` define subagents with restricted tool sets. The important property
is that **read-only is a tool-set property, not a prompt property**: telling an
agent "do not write files" does not reliably bind it. If a dispatch must not
write, give it an agent type without `Write`/`Edit`.

## 5. Memory — the convention, not the content

`agent-memory/` ships empty on purpose. In the original it held one file per
operated system, carrying vendor quirks and API gotchas — inherently specific to
one environment. See `agent-memory/README.md` for the pattern, which is the part
that transfers.

## Layout

```
rules/            always-loaded contracts (+ incidents/, manifests/)
hooks/            enforcement (+ test-hooks/, session_start_modules/, staged/)
skills/           invocable procedures (81)
agents/           subagent definitions
docs/rule-reference/   long-form rationale, on demand
platform-rules/   host overlays (macOS / Windows)
bin/ scripts/     supporting tools
tests/            hook and skill tests
templates/        starter configs
contracts/ manifests/  machine-readable component metadata
```

## Recurring principles

**Simple, fast, correct.** In that order as a design test, not as permission to
trade one away. Prefer a native Claude Code control over a custom equivalent;
keep the default small; preserve automatic local flow inside a strong boundary;
retain only the evidence needed to establish the requested outcome.

**Core components must earn promotion.** A rule or hook enters the fresh-laptop
core only when (1) a measured failure exists, (2) native permissions, sandboxing,
or an on-demand skill cannot cover it, (3) it has a direct behavior test, and
(4) its context or runtime cost is bounded. Otherwise it remains on-demand or
author-profile-only.

**Pair every zero with a known-positive control.** A scanner reporting no
findings and a scanner that is broken look identical. The CI job here plants a
secret and fails if gitleaks does *not* find it.

**Prefer a predicate that emits a number.** `grep -c` over `grep -q`: an empty
stream is indistinguishable from a negative result.

**Verification is bounded.** It exists to answer one material decision, then
stop. `outcome-over-verification.md` puts a budget on it.

**A gate narrowed to pass is worse than the gap it hid,** because nothing signals
that coverage moved.

## Adapting it

Start with `bash install.sh`, accept the fresh-laptop profile and core, then
stop. Promote components only through the gate above. The author-workstation
profile is a source of candidates and history, not the default architecture.
`UBIQUITOUS_LANGUAGE.md` defines the vocabulary the full mirror assumes.
