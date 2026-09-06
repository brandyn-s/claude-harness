# Consuming the harness from a private overlay

This repository is the public core. An organisation that uses it will have things
the core must never contain: its MCP servers and their write-indicators, its
repositories, its tenant and org identifiers, its team's skills, its audit
trackers, its `settings.json` allow list. Those live in a **private overlay** —
the organisation's own Claude Code configuration repository — which **vendors this
repository's core paths verbatim at a pinned commit** and layers its own material
around them.

This document is the contract between the two. It has three parts: what is core
and what is overlay, how the pin is recorded and checked, and which direction code
flows.

## 1. Core and overlay

| Core (vendored verbatim, never edited downstream) | Overlay (never in the core) |
|---|---|
| `hooks/*.py`, `hooks/run-hook`, `hooks/session_start_modules/`, `hooks/manifests/`, `hooks/test-hooks/` | `~/.claude/environment-catalog.json` — the organisation's servers, topic files, repos, safe API hosts |
| `rules/*.md`, `rules/manifests/`, `rules/incidents/` | `hooks/protected-repos.json` with real repositories in it (the shipped file is empty) |
| `manifests/compile.py`, `manifests/ambient-budget.json` | organisation skills (`skills/<org>-*/`), agent memory topics, audit trackers |
| `scripts/` (the gates), `bin/` (the tools) | `settings.json` — `permissions.allow`, `mcpServers`, the local hook paths |
| `profiles/`, `contracts/*.example.json`, `install.sh`, `codex/` | launchd/systemd units, keychain item names, anything with a hostname in it |

The test for "is this core?" is the one `hooks/README.md` §Environment catalog
already applies to hooks: **nothing about a particular organisation is in the
code.** A hook that needs an organisation's names reads them from the catalog and
is a no-op while the section is empty. A rule that names a team's repository is an
overlay rule. A skill that calls an organisation's MCP server by its connector id
is an overlay skill.

Two files are core *and* carry overlay data: `contracts/environment-catalog.json`
(shipped empty; the operator's copy lives in `~/.claude/`) and
`hooks/protected-repos.json` (shipped empty). An overlay that edits them in place
lists them under `overrides` in `UPSTREAM.json` so the drift check reports rather
than fails them.

## 2. Pin and check

The overlay records the pin at its root:

```json
{
  "repo": "https://github.com/brandyn-s/claude-harness",
  "version": "1.0.0",
  "commit": "<40-hex sha of the vendored harness commit>",
  "branch": "main",
  "paths": ["hooks/", "rules/", "manifests/", "scripts/", "bin/", "profiles/", "contracts/", "codex/", "install.sh"],
  "overrides": ["hooks/protected-repos.json", "contracts/environment-catalog.json"]
}
```

(`contracts/UPSTREAM.example.json` is a copy of that shape.) Then, in the overlay:

```bash
python3 bin/upstream-check.py --check                 # CI: fail on a fork
python3 bin/upstream-check.py --fetch                 # also report how far behind the pin is
python3 bin/upstream-check.py --upstream-dir ~/src/claude-harness   # offline, from a clone
```

The tool compares the blob SHA of every file under the core paths in the overlay's
`HEAD` with the same path at the pinned commit and classifies each one:

| class | meaning | `--check` |
|---|---|---|
| `identical` | the vendored copy | passes |
| `override` | differs, and is listed in `overrides` | passes, reported |
| `modified` | differs, and is not an override — **a fork** | fails |
| `only-upstream` | at the pin, missing here — a dropped file | fails |
| `only-downstream` | under a core path, not in the harness | passes, reported |
| `behind` | core files changed upstream since the pin | information |

`behind` is not a failure: staying pinned is a choice. `modified` is: a core file
edited in the overlay stops receiving the harness's fixes for that file, and the
guard suites in `hooks/test-hooks/` no longer describe what the overlay runs. The
two honest resolutions are re-vendoring (take the upstream file) and an upstream
pull request (change the core for everyone, then re-vendor).

### Updating the pin

1. In a harness clone, read `CHANGELOG.md` between the pinned version and the
   target. A **MAJOR** bump changes this contract (a core path moves, a hook's
   input or output shape changes, a settings key is renamed); a **MINOR** bump adds
   or changes behaviour (a new hook, a new blocked class, a changed default); a
   **PATCH** bump fixes without changing any verdict.
2. Copy the core paths into the overlay, set `commit` and `version` in
   `UPSTREAM.json`, run `bin/upstream-check.py --check`.
3. Run the overlay's own gates — at minimum the ones it vendored:
   `manifests/compile.py --root . --check --strict-semantic`,
   `bin/architecture-drift-check.py`, `scripts/run-tests.py`. The harness's tests
   run unchanged in an overlay because nothing in them names an organisation.
4. Re-apply the profile: `python3 scripts/install-profile.py` previews what the
   new pin would change in `~/.claude/settings.json`; `--apply` writes it with a
   backup.

### Versions and tags

`VERSION` at the harness root holds the current version; `CHANGELOG.md` has an
entry per version plus an `[Unreleased]` section; releases are tagged
`v<MAJOR>.<MINOR>.<PATCH>` on `main`. The marketplace plugins under
`marketplace/` carry their own `1.1.x` versions (bumped by
`scripts/build-marketplace.py` on content change) — those number the bundles, not
the repository. `scripts/test_version_contract.py` keeps the three in agreement.

## 3. Which way code flows

**Public → private, mechanically.** Every harness change reaches the overlay by
re-vendoring at a new pin. Nothing in the harness needs to know the overlay exists.

**Private → public, only as a de-identified lesson.** An overlay learns things the
core should have — a new leak shape, a hook that fires too often, a rule that
fights another — and the way that lesson travels is a pull request against this
repository that carries the *shape* and not the *instance*: the pattern, a
synthetic fixture, the measurement, never the hostname, the ticket, the person or
the codename. Two gates hold that line:

- `scripts/test_deidentification_residue.py` scans every tracked file (and, via
  the `commit-msg` hook `bin/setup-githooks.py` installs, every commit message)
  for the organisation identifiers that have leaked before. It stores them as
  digests so the test does not republish what it forbids.
- `skills/_shared/lesson-routing.md` is the routing table `capture` and `distill`
  follow when they write a lesson down: which repository each kind of lesson
  belongs in, and what has to be stripped before it crosses.

The asymmetry is deliberate. The public direction can be automated because it
carries no risk; the private direction cannot, because the failure mode — an
organisation's name in a public commit — is not reversible.

## 4. What this replaces

Before this contract the same files were edited in both repositories by hand and
reconciled by memory. On 2026-09-06 that comparison stood at 853 identical files,
621 that differed, 806 only in the overlay and 157 only in the harness — with no
record of which differences were intended. `UPSTREAM.json` is that record;
`bin/upstream-check.py` is the comparison, run in seconds instead of by hand.
