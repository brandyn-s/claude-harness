# claude-harness

A working [Claude Code](https://docs.claude.com/en/docs/claude-code) harness:
**73 hooks**, **38 ambient rules**, **82 skills**, and the agent
definitions that tie them together — about 1,568 source files, plus a generated
plugin tree under `marketplace/` that roughly doubles the file count and is not
meant to be read (see [marketplace/README.md](marketplace/README.md)).

It is a configuration repo, but the reusable part is not the config. It is the
**method**: what to do when a scanner reports zero, when a metric plateaus, when
a subagent claims success, or when a fix "works" but was never committed. Most
of that method exists because something broke, and the write-ups say so with
dates and measurements.


## Before you adopt: measured cost and prerequisites

Two ways to use this repository, with very different costs. **Read this before
cloning the whole thing** — the numbers below are measured with Anthropic's own
tokenizer (`/v1/messages/count_tokens`), not estimated from byte counts.

### Tier 1 — install a plugin bundle (recommended)

```
/plugin marketplace add brandyn-s/claude-harness
/plugin install safety-net@claude-harness
```

Each bundle is self-contained and ships **no ambient rules**, so a session costs
roughly stock Claude Code plus a few hundred tokens of skill descriptions. This
is the tier to start with.

### Tier 2 — clone the whole configuration (the author's mirror)

This is a real power-user configuration, and it is priced like one:

| component | measured tokens |
|---|---|
| always-loaded rules (31 files) | 75,413 |
| skill listing (82 skills, 8 already suppressed to name-only) | 18,687 |
| `CLAUDE.md` + `AGENTS.md` | 3,280 |
| **ambient floor, before your first message** | **97,380** |
| plus broadly-scoped rules that load in most coding sessions | 24,830 |
| **effective coding session** | **122,210** |

On a 200K-token context window that is **roughly half the window consumed at
rest**. Anthropic's guidance is that context is "a finite resource with
diminishing marginal returns"; this configuration deliberately spends a lot of
it on always-loaded engineering discipline. That trade is defensible for the
author, who wrote every rule in response to a specific measured failure, and it
may not be the trade you want on day one. `bin/ambient-load-report.py` prints
the current split so you can decide with numbers rather than vibes.

The skill listing also exceeds its own budget: `skillListingBudgetFraction` is
set to 3%, which is 6,000 tokens on a 200K context against an 18,687-token
listing — **3.1x oversubscribed**. It fits on a 1M-context model. If you adopt
wholesale on a 200K model, expect the listing to be truncated, and prefer
marking more skills `name-only` in `skillOverrides`.

### Prerequisites that are NOT included

Roughly ten skills require MCP servers that are not part of this repository and
are not public:

| server | skills that hard-require it |
|---|---|
| `memory-search` | `capture`, `distill`, `recall`, `review-learnings` |
| `codebase-memory-mcp` | `api-ingest`, `code-explore`, `codebase-memory-exploring`, `codebase-memory-quality`, `codebase-memory-tracing`, `verify-search-result` |

Those skills will no-op or error without their server. The
`code-intelligence` plugin bundle is affected as a whole and is best read as a
worked example rather than installed. Research skills additionally want
Tavily / Exa / Firecrawl API keys.

### What has been measured, and what has not

Measured on a clean Linux container with none of the author's tooling: the
by-hand install completes, all 48 wired hooks resolve, and 511 hook invocations
across seven realistic payload shapes produced **zero crashes and zero blocks
on innocuous actions**. `settings.example.json` still carries 49 placeholder
paths you must edit. Not measured: behavior inside a live authenticated session,
and any A/B of this harness against stock Claude Code on task outcomes. Adopt
accordingly.


## Optional: measure whether the verification rules are working

This repository spends more ambient context on "verify before claiming done"
than on any other single concern, and — unlike git discipline or secret
redaction — **none of it has mechanical backing**. Every rule in that cluster
reports `enforced_by: []`, and `manifests/compile.py --check` will now tell you
so honestly.

The obvious move is a Stop hook that blocks an unverified completion claim. That
move is not shipped, for a reason worth reading: the argument for it rested on a
count of hook *blocks* with no denominator — how many compliant actions the rules
had already shaped. An adversarial cross-vendor review rejected that as
survivorship logic, and it was right. Building an enforcing gate on it would
repeat the error one layer down.

So what ships is the instrument that produces the missing denominator:

```jsonc
// ~/.claude/settings.json — opt in explicitly
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command",
                     "command": "python3 ~/.claude/hooks/completion-claim-observer.py" } ] }
    ]
  }
}
```

It **never blocks** — exit 0 unconditionally, no `decision` key, no network — and
appends one JSONL row per turn to `~/.claude/state/completion-claims.jsonl`:
whether the turn made a completion claim, and whether verification-shaped
evidence appeared in the same turn's tool output.

```bash
python3 bin/completion-claim-report.py          # distribution
python3 bin/completion-claim-report.py --json   # machine-readable
```

The report **refuses to recommend anything** below 100 observed turns, for the
same reason the gate is not shipped. A low unverified-claim rate is evidence the
ambient rules are doing their job and no gate is warranted; a high one is the
first real basis for building one. Either way the decision comes from a
distribution rather than from an anecdote.

The detector was qualified against five fixtures before shipping — claim with
tool evidence, claim with prose evidence only, claim with none, a non-claim, and
a *hedged* non-claim ("I would need to run the suite before saying anything is
fixed"). That last case initially registered as a claim, which would have
inflated the unverified rate in the direction that flatters the case for a gate;
the negation guard exists because of it.

## Why this might be worth reading

**Enforcement is mechanical, not advisory.** The design assumes the agent is a
privileged but untrusted actor. Anything that must not happen is blocked by a
hook that runs regardless of what the model decided — not by a rule asking it to
remember. `hooks/bash-security-guard.py` is the clearest case: it matches command
*text*, has no memory to wear down, and returns the same verdict every time.

**Rules are compressed incidents.** `rules/` reads as engineering discipline;
`rules/incidents/` holds the failures that produced it. Some examples:

- `gitleaks --config /dev/null` disables the entire ruleset, so it reports
  "no leaks found" over thousands of commits and the zero looks like a clean bill.
- A `Condition` on an IAM statement whose action does not support that condition
  key is a **deny**, not a narrower allow — and `plan`, `apply`, and the whole
  unit suite stay green, because only a real invoke fails.
- An alarm built as "require a healthy heartbeat, treat missing data as
  breaching" cannot tell BROKEN from NEVER RAN: the emitter dying is what
  removes the datapoint.
- A test that *re-implements* the path it verifies is testing your model of the
  code, not the code.

**Zeros are not trusted without a control.** A recurring theme: pair every
negative result with a known-positive in the same invocation, or you cannot
distinguish "nothing there" from "instrument not working." The CI job in this
repo does this to itself — it fails if gitleaks does *not* fire on a planted
secret before it believes a clean scan.

## Layout

```
rules/            ambient engineering rules (+ incidents/ and manifests/)
hooks/            PreToolUse / PostToolUse / session-lifecycle enforcement
skills/           invocable procedures (82 of them)
agents/           subagent definitions
docs/rule-reference/   long-form rationale, loaded on demand
platform-rules/   host-specific overlays (macOS / Windows)
bin/ scripts/     supporting tools
tests/            hook + skill tests
templates/        starter configs
```

Start with `ARCHITECTURE.md`, then `rules/`. `UBIQUITOUS_LANGUAGE.md` defines
the vocabulary the rest of the repo assumes.

## If you only read one thing

This repo is large, and the honest reaction to a 1,500-file configuration is
that you almost certainly do not need it. So, in order:

| Budget | Read | Why |
|---|---|---|
| **one file** | [`hooks/bash-security-guard.py`](hooks/bash-security-guard.py) | The whole argument in one artifact: a guard that matches command *text*, so it cannot be argued out of a verdict |
| **three files** | + [`rules/verify-effectiveness.md`](rules/verify-effectiveness.md), [`rules/diagnose-before-fix.md`](rules/diagnose-before-fix.md) | The two rules that pay for themselves fastest |
| **the argument** | [`ARCHITECTURE.md`](ARCHITECTURE.md) | Five layers, and which of them can actually enforce anything |
| **the receipts** | [`rules/incidents/`](rules/incidents/) | The failures each rule was written against |
| **everything** | [`skills/README.md`](skills/README.md) | Index of all 82 skills |

Taking one hook is a legitimate outcome. Nothing here requires adopting the
whole thing, and most of it you shouldn't.

## Installing it

**As plugins (recommended)** — versioned, updatable, and *namespaced*, so nothing
collides with skills you already have:

```
/plugin marketplace add brandyn-s/claude-harness
/plugin install safety-net@claude-harness
```

Six bundles are published: `safety-net` (the enforcement hooks),
`planning-toolkit`, `security-scanner`, `knowledge-ops`, `code-intelligence`,
`research-intel`. Install only what you want; skills arrive as
`/plugin-name:skill`. Update with `/plugin marketplace update claude-harness`.

**By hand**, if you would rather read every file before it runs:

```bash
git clone https://github.com/brandyn-s/claude-harness
cd claude-harness
cp settings.example.json ~/.claude/settings.json   # then edit the hook paths
cp -r hooks rules ~/.claude/                       # or just the ones you want
```

Copying gives you no versioning, no updates, and no namespacing — a skill you
copy will shadow one of your own with the same name. `install.sh` automates a
fuller setup. `platform-rules/` covers what is host-specific. Requires Python
3.11+; `requirements-dev.txt` covers the tests.

> **Do not make your checkout your live `~/.claude`.** The original *was*
> its own runtime directory, which meant every new kind of runtime artifact
> (session spools, caches, ledgers, receipts) was one missing `.gitignore` rule
> away from being committed. Keep the two separate.

## Tests

```bash
pip install -r requirements-dev.txt
python3 scripts/run-tests.py
```

~3,900 tests across 44 directories. The runner goes **one directory at a time** on
purpose — a single root-level `pytest` cannot work here, and `scripts/run-tests.py`
explains why in its docstring.

It also carries a **known-failing baseline**, printed on every run and gated in
both directions. Those failures are tests asserting on inventories that this
curated subset legitimately changed (which hooks are registered, which skills
exist). They are not deleted, because deleting them would green the suite by
reducing coverage and leave no signal that coverage had moved. Going *over* the
baseline is a regression; going *under* it means an entry is stale and should be
removed — both fail, so the baseline cannot quietly become a place failures go to
be forgotten.

## What this is a subset of

This is a curated export of a larger private configuration, carrying the parts
that are not tied to one particular environment. **32 skills were removed** — the
ones whose job was operating internal systems (tenant-bound provisioning,
monitoring, compliance assessment, and deployment tooling).

Two consequences worth knowing:

- Some incident narratives reference a skill that is not here (`/investigate`,
  `/cc-monitor`, and others). The *lesson* in those write-ups stands on its own;
  the cross-reference will not resolve.
- `agent-memory/topics/` ships empty on purpose. It held one file per operated
  system, which is inherently organisation-specific. See
  `agent-memory/README.md` for the convention, which is the transferable part.

A handful of identifiers in kept files were replaced with neutral placeholders
(`example.internal`, `ExampleTarget`, `contributor-a`). Where you see one, the
original named something internal.

## Contributing

Issues and PRs are welcome, particularly bug reports against the hooks. Note
that much of what looks arbitrary is load-bearing: the odd-looking clauses are
usually a specific failure encoded so it cannot recur. Check
`rules/incidents/` before concluding a rule is overcautious.

## License

MIT — see [LICENSE](LICENSE).
