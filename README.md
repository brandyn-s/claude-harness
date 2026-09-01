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

The rebuild follows one rule: **simple, fast, correct**. The default is small,
keeps local work flowing inside Claude Code's native sandbox, and retains only
the controls that protect a measured failure. The evidence and demotion
decisions are recorded in
[`docs/fresh-laptop-control-audit.md`](docs/fresh-laptop-control-audit.md).


## Fresh-laptop install (recommended)

Clone this repository somewhere separate from Claude Code's live configuration,
then run the installer:

```bash
git clone https://github.com/brandyn-s/claude-harness
cd claude-harness
bash install.sh
python3 bin/fresh_laptop_doctor.py
```

For a new machine, accept the fresh-laptop profile and the recommended core.
The installer then offers the owner-focused Brandyn operator layer. The
portable core installs two ambient rules and three deterministic hooks:

- `outcome-over-verification.md` and `claude-md-quality.md`
- catastrophic Bash safety, config integrity, and MCP result-injection guards
- `acceptEdits` plus sandbox-auto-approved Bash; sandbox escapes require review
- project MCP auto-activation disabled

The operator layer adds one compact discipline rule, the `delivery` Bash policy
pack, explicit review for high-consequence Terraform/AWS/Git/MCP mutations, a
non-blocking repeated-failure detector, and prompt/tool-output secret controls.
It does not restore the phrase-based Stop blocker or the historical ambient
corpus. The doctor reports the operator layer separately when selected.

The profile is previewable and independently applicable:

```bash
python3 scripts/install-profile.py
python3 scripts/install-profile.py --apply
```

Apply creates a timestamped backup when `~/.claude/settings.json` already
exists, preserves unrelated settings, and writes atomically. The installer also
backs up collisions before copying runtime files. Re-running it is idempotent.
See [`profiles/README.md`](profiles/README.md) for the merge contract.

On macOS, run `brew bundle` first. On Linux, install Python 3.10+, Git,
`bubblewrap`, and `socat`. Native Windows is not supported by Claude Code's
sandbox; use WSL2. After installation, `/sandbox` shows the effective boundary.

## Author-workstation profile (explicit opt-in)

Continue through `install.sh` only when you intentionally want the complete
author mirror: all hooks, rules, skills, agents, and host integrations. It uses
the same native sandbox boundary, but has a much larger context and dependency
surface. Its measured cost, using Anthropic's `count_tokens` endpoint rather
than byte estimates, is:

| component | measured tokens |
|---|---|
| always-loaded rules (31 files) | 75,413 |
| skill listing (82 skills, 8 already suppressed to name-only) | 18,687 |
| `CLAUDE.md` + `AGENTS.md` | 3,280 |
| **ambient floor, before your first message** | **97,380** |
| plus broadly-scoped rules that load in most coding sessions | ~12,000 |
| **effective coding session** | **~109,000** |

On a 200K-token context window that is **roughly half the window consumed at
rest**. This is why the full mirror is not the fresh-laptop default.
`bin/ambient-load-report.py` prints the current split.

The skill listing also exceeds its own budget: `skillListingBudgetFraction` is
set to 3%, which is 6,000 tokens on a 200K context against an 18,687-token
listing — **3.1x oversubscribed**. It fits on a 1M-context model. If you adopt
wholesale on a 200K model, expect the listing to be truncated, and prefer
marking more skills `name-only` in `skillOverrides`.

### Advanced-profile dependencies that are not included

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

The full mirror is a host-materialized reference, not a portable file to copy.
`settings.example.json` intentionally contains placeholder hook paths;
`install.sh` materializes paths for the target machine. Do not copy the live
author settings onto a new laptop.


## Optional: measure whether the verification rules are working

This repository spends more ambient context on "verify before claiming done"
than on any other single concern. A few slices have derived partial enforcement,
but the specific act of making a completion claim without same-turn evidence has
no mechanical backing. `manifests/compile.py` derives that topology from live
wiring instead of trusting rule-side declarations.

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

The report **refuses to interpret anything** below 100 readable turns or when it
detects no completion claims. Unreadable transcript tails never satisfy that
sample floor. A low unverified-claim rate is evidence the ambient rules are doing
their job and no gate is warranted; a high one is the first real basis for
building one. Either way the decision comes from a distribution rather than from
an anecdote.

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
Non-catastrophic delivery, portability, and workflow preferences are opt-in
tables evaluated inside that same hook process.

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

## Optional plugin bundles

Plugins are useful when you want one namespaced capability without installing a
user-level harness:

```
/plugin marketplace add brandyn-s/claude-harness
/plugin install safety-net@claude-harness
```

Six bundles are generated: `safety-net` (the three-hook fresh-laptop core),
`planning-toolkit`, `security-scanner`, `knowledge-ops`, `code-intelligence`,
`research-intel`. Install only what you want; skills arrive as
`/plugin-name:skill`. Update with `/plugin marketplace update claude-harness`.

The remaining hook implementations in the bundle are source-available but are
not registered automatically. Add them only after a measured need.

> **Do not make your checkout your live `~/.claude`.** The original *was*
> its own runtime directory, which meant every new kind of runtime artifact
> (session spools, caches, ledgers, receipts) was one missing `.gitignore` rule
> away from being committed. Keep the two separate.

## Tests

```bash
pip install -r requirements-dev.txt
python3 scripts/run-tests.py
```

~3,900 tests across the repository. The runner goes **one directory at a time** on
purpose — a single root-level `pytest` cannot work here, and `scripts/run-tests.py`
explains why in its docstring.
Every discovered test directory must pass; there is no tolerated-failure
baseline.

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

## License

MIT — see [LICENSE](LICENSE).

## Advanced full-mirror synchronization

These commands are for maintainers of a complete cross-runtime mirror, not for
plugin users. Check before apply when repairing the session-closure skills:

```bash
python3 bin/sync-codex-skills.py --check --with-dependencies retro distill ship
python3 bin/sync-codex-skills.py --apply --with-dependencies retro distill ship
```

For the complete installed gather-family closure. `gather-vendor` consumes the same authoritative
direct shared lifecycle dependency as `gather-claude`. Check, apply,
then check again:

```bash
python3 bin/sync-codex-skills.py --check --shared-file gather-conventions.md --shared-file project-dir.md gather-claude gather-vendor
python3 bin/sync-codex-skills.py --apply --shared-file gather-conventions.md --shared-file project-dir.md gather-claude gather-vendor
python3 bin/sync-codex-skills.py --check --shared-file gather-conventions.md --shared-file project-dir.md gather-claude gather-vendor
```
