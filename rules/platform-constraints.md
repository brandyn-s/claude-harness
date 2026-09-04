@rule platform_constraints
@version 2026-08-06
@scope commands, file operations, credentials, dependencies, worktrees, and runtime configuration

# Platform Constraints — Portable Core

Apply the host overlay from `platform-rules/macos/` or
`platform-rules/windows/` when the task touches OS-specific behavior. Do not
apply a Windows incident mechanically on macOS, or vice versa.

## Security invariants

- Never expose secrets in commands, logs, process listings, verbose network
  traces, diagnostics, or error messages.
- Never expand a credential value merely to confirm that it exists. Inspect
  metadata or presence through an approved secret interface.
- Never use `--dangerously-skip-permissions` for spawned Claude processes.
- Resolve destructive targets with read-only checks. A destructive command
  stands alone; do not combine stop/kill/delete/abort with other operations.
- When a guard rejects a command shape, change the approach. Do not disguise
  or fragment the same operation to evade it.
- A deterministic guard blocking the SAME shape twice in one session is a
  signal about your own default, not about the guard. Stop composing that shape
  for the rest of the session rather than re-deriving the fix each time it
  fires: ask the PRODUCER for less (`-n`, `--limit`, `-m`, `sed -n '1,Np' FILE`)
  or redirect to a file and read it.
  Full: incidents#2026-08-15-guard-blocked-the-same-shape-six-times

## Shell and process execution

- Use the active host's shell contract; quote paths and values explicitly.
- In zsh, do not use reserved parameters as scratch names: `path` is the
  `PATH` array and `status`, `pipestatus`, and `ERRNO` are special parameters;
  use names such as `candidate_path` and `rc` instead.
- `IFS=$'\t' read -r a b c` does NOT make tab a hard delimiter: tab is an
  IFS-WHITESPACE character, so consecutive tabs COLLAPSE into one separator and
  an empty field silently shifts every later column left. Emit a placeholder for
  empty fields, or parse the record in Python; never use positional `read` on a
  format with optional fields.
  Full: incidents#2026-08-25-ifs-tab-read-collapses-empty-fields
- Avoid long inline scripts, nested interpolation, and unbounded argv payloads.
  Put complex logic in a reviewed file and execute it directly.
- QUOTE THE HEREDOC DELIMITER (`<<'PY'`, not `<<PY`) whenever the body contains a
  backslash, `$`, or a backtick; the shell otherwise rewrites the body before the
  receiving program sees it and reports nothing. Pass variable data as `argv`
  rather than interpolating it.
  Full: incidents#2026-08-20-unquoted-heredoc-delimiter-altered-the-payload
- A guard/hook block rejects the ENTIRE compound command — no stage ran,
  including stages BEFORE the one that triggered the block. Re-issue every
  stage, and verify each earlier stage's artifact exists before interpreting
  any downstream result: a plausible aggregate success is not that evidence.
  Full: incidents#2026-08-24-blocked-compound-command-no-stage-ran
- A pipeline reports the pipeline's semantics, not automatically the producer's
  exit status. Capture and gate the intended command explicitly.
- A `run_in_background` command's completion notification carries the WRAPPER's
  final exit status. End background wrappers with explicit rc propagation
  (`; rc=$?; ... ; exit $rc`) or run the verdict command alone.
  Full: incidents#2026-08-25-background-notification-carries-the-wrapper-exit
- `npm install <pkg>` PRUNES node_modules entries absent from package.json. Pin
  every load-bearing dep in package.json before installing anything else.
  Full: incidents#2026-08-25-npm-install-pruned-jsdom
- Do not put an important producer behind an early-closing consumer such as
  `grep -q`; it can terminate the producer before artifacts flush.
- Do not use a foreground sleep or poll longer than the tool timeout. Use the
  supported background/wait mechanism, bounded polling, and durable output.
- A background child that reads stdin must receive an explicit descriptor;
  its owner remains responsible for polling and cleanup.
- Do not infer process health from a wide command-line listing when launcher
  environments may contain secrets.

## BSD dialect gaps whose failure mode is SILENCE (macOS)

macOS ships BSD tools that fail by emitting NOTHING with exit 0 (`grep -qv` is not the
inverse of `grep -q`; BSD `sed` BRE has no `\|` alternation; `producer | head -N || echo`
never takes the fallback). Prefer a predicate that emits a NUMBER, and pair every zero
with a known-positive control in the same command (search-efficiency COUNT_OVER_SILENCE).
Full: incidents#2026-08-24-bsd-dialect-gaps-whose-failure-mode-is-silence

## An exported AWS_REGION leaks into tests that derive names from it

A test that derives a resource name from `os.environ["AWS_REGION"]` inherits the operator
shell's value and fails like a code regression; the tell is in the assertion's VALUES. Pin
the region on the test command, and pin env-derived assertions inside the test
(`monkeypatch.setenv`).
Full: incidents#2026-08-25-exported-aws-region-leaked-into-govcloud-tests

## Python and file I/O

- Invoke `python3` on macOS/Linux unless a project-managed interpreter is
  explicitly selected.
- Specify encodings for text I/O. For external APIs, read bytes and decode
  with an explicit, evidence-based policy; `text=True` silently inherits a
  locale.
- Preserve newline and binary semantics for files you did not originate.
- Do not round-trip a formatted JSON/YAML file through load→dump to change a
  few values: the serializer reformats everything. Use anchored text
  replacement with occurrence-count asserts (`assert text.count(old) == 1`),
  then prove validity by parsing the result.
  Full: incidents#2026-08-24-load-dump-round-trip-rewrote-a-registry
- Do not name scratch modules after standard-library or installed packages.
- Never hand-roll a `urllib` Microsoft Graph probe. Import the shared helper:
  `from msgraph_helper import graph_get, odata_quote` (`bin/msgraph_helper.py`,
  app-only GCC High auth via Keychain, no `az login`); a `safe=` set that
  contains a space reproduces the crash `quote()` was meant to prevent.
  Full: incidents#2026-07-05-6th-recurrence-each-new-hand-rolled-urllib-graph
- Use unique temporary directories rather than predictable shared filenames.
- Keep imports portable for modules collected by cross-platform CI.

## Dependencies and builds

- Do not upgrade all packages at once. Change the smallest dependency set,
  review the lock diff, and run import/runtime verification.
- Hash-pinned locks are platform artifacts unless built for every target — and
  INTERPRETER-VERSION artifacts too: a version-conditional marker changes the
  resolved set per Python. Compile against the declared floor and verify the lock
  installs under every interpreter that consumes it — CI's and the Dockerfile's
  are frequently different. pip enables `--require-hashes` IMPLICITLY for a whole
  file when ANY entry carries a hash.
  Full: incidents#2026-08-25-hash-pinned-lock-compiled-on-the-wrong-interpreter
- Verify target architecture when building containers from Apple Silicon.
- Treat a successful package-manager exit with missing imports or partial
  namespaces as failure.

## AWS and external systems

- For AWS work, select the named profile/partition/region and verify caller
  identity before drawing live-state conclusions.
- Distinguish authentication failure, authorization failure, and endpoint or
  connectivity failure. Do not report one as another.
- Keep credential-bearing environment state out of child diagnostics.
- Encode query/filter parameters with the client library rather than manual
  string interpolation.
- A live read proves current state; a repository or historical artifact does
  not.

## Git and worktrees

- Verify repository identity, branch, worktree path, and clean/dirty state
  before mutation.
- `origin/main` in `git checkout -B <b> origin/main` / `git worktree add … origin/main`
  is a LOCAL remote-tracking ref. Branching from it WITHOUT fetching first cuts from a
  stale tree and silently REVERTS whatever merged since. Fetch in the SAME command:
  `git fetch origin main && git checkout -B <b> origin/main`.
  Staged gate: `hooks/staged/branch-base-freshness-guard.spec.md`.
  Full: incidents#2026-08-26-branched-from-a-stale-origin-main-twice
- Treat a worktree session's current directory as runtime state. Do not assume
  paths from the parent checkout resolve after isolation.
- Preserve user changes and shared indexes. Avoid destructive recovery unless
  the exact target and authority are explicit.
- Verify a merged change separately at remote history, local bytes, and any
  long-lived process that must reload it.

## Configuration runtime

`settings.json is live runtime state`: editing source, a template, or another
checkout does not prove that an active session loaded it. Before changing
configuration, snapshot the exact target and related state. Afterward validate
schema, wiring, permissions, loaded-session behavior, and rollback. Prefer
atomic replacement over partial writes.

## Failure and reporting contract

Preserve the original exit code and complete output before filtering. If a
command times out, is killed, partially writes, or runs on an unqualified host,
report that outcome explicitly. Do not convert infrastructure uncertainty into
an application conclusion.

A pre-commit framework prints the FAILING hook FIRST and the passing hooks after
it, so `git commit … | tail -N` shows a wall of `Passed`/`Skipped` while the
commit did NOT happen. For any state-changing command, redirect to a file and read
that, capture `$?`, and assert the intended STATE afterwards (`git log --oneline -1`,
`git status --short`) rather than believing whichever end of the output the filter
chose to show.
Full: incidents#2026-08-26-pre-commit-failure-hidden-by-tail

- ECHO A RESOLVED ID AND STOP IF IT IS EMPTY. An empty shell capture
  interpolated into an AWS `--ids`-family argument does not error — it returns
  a DIFFERENT resource's data, which reads as a successful answer. Gate on the
  capture (`[ -n "$ID" ] || exit 1`), and prefer IaC/source over an ephemeral
  runtime object for a configuration claim — the runtime object disappears when
  the task does.
  Full: incidents#2026-08-29-empty-capture-read-another-security-group

Detailed platform incidents and command-specific mechanisms are retained in
`rules/incidents/platform-constraints.md`; host-specific active overlays are
under `platform-rules/` and load only on the matching host.
