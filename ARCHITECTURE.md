# Architecture

How this Claude Code harness is put together, and why each layer exists.

There are five layers. They differ in **when they load** and **whether the model
can decline them** — that second axis is the one that matters.

| Layer | Loads | Model can ignore it? |
|---|---|---|
| **Hooks** (73) | on every matching tool call | **No** — enforced by the runtime |
| **Rules** (38) | always, in context | Yes (they are text) |
| **Skills** (82) | on invocation | Yes |
| **Agents** | on dispatch | Yes |
| **Reference docs** | on demand | Yes |

## 1. Hooks — the only layer that actually enforces

`hooks/` holds Python that the Claude Code runtime executes around tool calls.
A `PreToolUse` hook can **block** a call outright. This is the only layer with
that property, and it is where anything load-bearing belongs.

The design premise: **the agent is a privileged but untrusted actor.** It holds
tools that can destroy data, so "the model was told not to" is not a control. A
guard that matches command *text* has no memory to wear down and returns the same
verdict every time.

Representative hooks:

| Hook | Event | Blocks |
|---|---|---|
| `bash-security-guard.py` | PreToolUse(Bash) | credential reads, destructive shapes, fragile inline code |
| `output-secret-redact.py` | PostToolUse | secrets in tool output |
| `prompt-secret-scan.py` | UserPromptSubmit | pasted credentials |
| `read-deny-guard.py` | PreToolUse(Read) | reads of denied paths |
| `bash-tail-buffering-guard.py` | PreToolUse(Bash) | `producer \| tail` shapes that hide output |
| `memory-write-guard.py` | PreToolUse(Write) | oversized memory entries |
| `session-start.py` | SessionStart | (composes startup context) |

Hooks are wired in `settings.json` — see `settings.example.json`. Each has tests
in `hooks/test-hooks/`.

**If you take one thing from this repo, take this layer.** A rule asking the
model to remember something has a failure rate; a hook does not.

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
(`validate-changes`, `verification-before-completion`), security review
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
skills/           invocable procedures (82)
agents/           subagent definitions
docs/rule-reference/   long-form rationale, on demand
platform-rules/   host overlays (macOS / Windows)
bin/ scripts/     supporting tools
tests/            hook and skill tests
templates/        starter configs
contracts/ manifests/  machine-readable component metadata
```

## Recurring principles

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

Nothing requires adopting the whole thing. Take a hook, take a rule, ignore the
rest. Start with `hooks/` — it is the layer with teeth and the least coupled to
anyone's environment. `install.sh` handles a fuller setup;
`UBIQUITOUS_LANGUAGE.md` defines the vocabulary the rest assumes.
