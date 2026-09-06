# Changelog

The repository's version is the single line in `VERSION`; releases are tagged
`v<MAJOR>.<MINOR>.<PATCH>` on `main`. What each part means for a private overlay
that vendors this repository is in
[`docs/consuming-from-a-private-overlay.md`](docs/consuming-from-a-private-overlay.md):
MAJOR changes the consuming contract, MINOR adds or changes behaviour, PATCH fixes
without changing a verdict. The marketplace bundles under `marketplace/` carry
their own `1.1.x` numbers; those version the bundles, not the repository.

Before 1.0.0 the history is narrative: [`docs/EVOLUTION.md`](docs/EVOLUTION.md).

## [Unreleased]

## [1.0.0] — 2026-09-06

First versioned release. Everything below landed on the `fix/eval-1-2-3` branch
from the 2026-09-06 evaluation.

### Added

- `script-content-guard.py`: the Bash guard's catastrophic checks applied to the
  body of a script file at Write/Edit time and to a local script a command
  executes. Closes the 2026-08-12 `zsh verify_probes.sh` leak path. Calibrated by
  replaying 13,894 script writes from 933 sessions (0.53% fire rate).
- `check_python_source_exfil` in `bash-security-guard.py`: an ast taint walk that
  applies the curl policy to Python source — a credential file, a `SECRET`-shaped
  environment variable, a keychain read or a local file reaching a request body,
  `params=` or URL of a host outside `SAFE_RE` blocks; auth headers, `auth=` and
  the OAuth credential grant pass. Six calibration cuts on the same corpus, from
  350 fires to 1.
- The operating loop: `rules/session-boundaries.md`, `compaction-budget.py`
  (handoff nudge from the second compaction; ledger audit at PostCompact),
  `proceed-gate.py` (DO / NOT / CHECK for a bare `proceed`; INTENT.md → ledger),
  `skills/frame/` (INTENT.md), `session_start_modules/model_notes.py`.
- `bin/ledger-audit-report.py`: the measurement behind the acceptance ledger's
  hypothesis (does compaction drop acceptance state?).
- `bin/build-doc-counts.py`: every inventory number in README, ARCHITECTURE and
  AGENTS is generated from the tree and gated in CI.
- `install.sh --dry-run`; `HARNESS_ASSUME_DEFAULTS=1` for the prompts.
- `codex/`: the Codex posture patch and `AGENTS.md` overlay.
- `VERSION`, this file, `contracts/UPSTREAM.example.json`,
  `bin/upstream-check.py` and `docs/consuming-from-a-private-overlay.md`: the
  contract for a private overlay that vendors this repository.
- `scripts/deidentification_residue.py`: the residue scanner as a CLI, run by
  `.githooks/commit-msg` (commit messages), `.githooks/pre-commit` (staged files,
  marketplace drift) and a CI step over a pull request's commit messages;
  `skills/_shared/lesson-routing.md`: which lessons belong in the public core and
  what is stripped before one crosses.
- `scripts/migrate-to-core.py`: a kitchen-sink `settings.json` to the core posture
  (sandbox on, blanket allows removed, dangerous-mode prompt restored, phrase
  Stop blockers unregistered), preview by default, backup on `--apply`.
- `bin/lean-core-ab.py` and `docs/plans/2026-09-06-lean-core-ab.md`: the
  pre-registered lean-ambient-core A/B — arms, day-alternating switch, the fixed
  decision rule and bisect order.
- `bin/skill-usage-report.py` and `docs/skill-listing-decisions.md`: skill
  invocation counts from transcripts and the `skillOverrides` decisions they
  support (23 skills `name-only`). `skills/roundtable/skill-usage-audit.py` is a
  front over it.
- `bin/lean-core-ab.py retro`: the plan's metrics straight from a transcript
  backup, joined to the ambient rule bytes live on each session's day; the plan's
  §Baseline records the natural experiment it found and the client-version
  artifact it removed from the P1 proxy.
- `bin/replay-script-content-guard.py --check` and `.githooks/pre-push`: the
  guard replay as a gate when a push changes the guard predicates.
- `bin/codex-posture-check.py`: the Codex install against `codex/config.toml.patch`.
- `bin/upstream-check.py --pin`: classify an existing overlay before it adopts the
  contract; the adoption procedure in `docs/consuming-from-a-private-overlay.md`.
- Residue gate: two structural rules — a vendor's per-tenant subdomain, an email
  address at a non-placeholder domain.
- `.gitattributes`: the marketplace catalog and version ledger are
  `linguist-generated`; `AGENTS.md` §2 records why the bundles stay committed.

### Changed

- The operator profile is the recommended install and now carries the
  session-boundary contract (4 rules, 11 hook registrations).
- `session_ledger.render_for_injection` is frame-first (rejected → what done
  means → how) and labels INTENT.md-sourced entries.
- `manifests/compile.py --check` runs in CI with a fresh index (no `--no-reindex`).
- `bin/architecture-drift-check.py`: an undocumented wired hook and a phantom
  inventory row are hard failures.
- `scripts/build-marketplace.py` gates dispatcher closure: a bundle that ships a
  dispatcher ships every closed child it runs.
- Each `hooks/staged/*.spec.md` carries an owner, a "why not yet" and a "ship via".

### Fixed

- `ENV_VAR_DIAGNOSTIC` missed the exact 2026-08-12 leak line (nested `${#VAR}`
  inside the `:+` branch) even inline.
- `hooks/README.md`, `ARCHITECTURE.md` and `docs/EVOLUTION.md` describe the tree
  they ship with (seven wired hooks had no row; the counts were stale).
