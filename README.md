# claude-harness

A working [Claude Code](https://docs.claude.com/en/docs/claude-code) harness:
**73 hooks**, **38 ambient rules**, **83 skills**, and the agent
definitions that tie them together — about 1,573 files.

It is a configuration repo, but the reusable part is not the config. It is the
**method**: what to do when a scanner reports zero, when a metric plateaus, when
a subagent claims success, or when a fix "works" but was never committed. Most
of that method exists because something broke, and the write-ups say so with
dates and measurements.

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
skills/           invocable procedures (83 of them)
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
| **everything** | [`skills/README.md`](skills/README.md) | Index of all 83 skills |

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
