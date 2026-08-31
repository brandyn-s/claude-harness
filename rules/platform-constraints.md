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
  fires. Measured 2026-08-15: `bash-tail-buffering-guard` blocked six times in a
  single session — five distinct `producer | tail/grep/head` constructions plus
  a trailing `echo`/`cat` after a verdict command — each block correctly
  explained and each followed later by the same reflex. The guard has no memory
  to wear down and the verdict never changes; the cheapest response after the
  first block is to ask the PRODUCER for less (`-n`, `--limit`, `-m`,
  `sed -n '1,Np' FILE`) or redirect to a file and read it, and to keep doing
  that unprompted.

## Shell and process execution

- Use the active host's shell contract; quote paths and values explicitly.
- In zsh, do not use reserved parameters as scratch names: `path` is the
  `PATH` array and `status`, `pipestatus`, and `ERRNO` are special parameters;
  use names such as `candidate_path` and `rc` instead.
- `IFS=$'\t' read -r a b c` does NOT make tab a hard delimiter. Tab is an
  IFS-WHITESPACE character, so consecutive tabs COLLAPSE into one separator and
  an empty field silently shifts every later column left. Different mechanism
  from the no-word-split trap above, and it bites the same shape: parsing a TSV
  whose optional middle column may be empty. Measured 2026-08-25 on
  `git worktree list --porcelain` — entries with no `branch` line emit
  `path\t\t1\t0`, `read` assigned the detached flag into `branch`, and ~52 of
  165 worktrees were misclassified with no error. Emit a placeholder for empty
  fields, or parse the record in Python; never use positional `read` on a
  format with optional fields.
- Avoid long inline scripts, nested interpolation, and unbounded argv payloads.
  Put complex logic in a reviewed file and execute it directly.
- QUOTE THE HEREDOC DELIMITER (`<<'PY'`, not `<<PY`) whenever the body contains a
  backslash, `$`, or a backtick. An unquoted delimiter makes the shell perform
  parameter and backslash processing on the body BEFORE the receiving program
  sees it, so `\n` arrives as a real newline and `$x` arrives empty. Nothing
  reports an error: the body is delivered, just altered. Measured 2026-08-20 — a
  heredoc writing a JS probe into a file collapsed `'\nCFG='` into a literal line
  break, producing an unterminated string literal; the injected script threw at
  parse time, the element it was meant to append never existed, and the read that
  looked for that element reported "no output" — which reads as a failed
  measurement rather than a corrupted payload. `tdd-mutation-testing.md` records
  this for mutation payloads and names only `` ` `` and `$`; the trigger set
  includes BACKSLASH and the hazard is not specific to mutation testing. When the
  body must carry escapes, use a quoted delimiter and pass variable data as
  `argv` rather than interpolating it.
- A guard/hook block rejects the ENTIRE compound command — no stage ran,
  including stages BEFORE the one that triggered the block. Re-issue every
  stage, and verify each earlier stage's artifact exists before interpreting
  any downstream result: a plausible aggregate success is not that evidence.
  Measured 2026-08-24 (3rd occurrence of the class): a blocked
  `cat >> tests/… <<'PY' … && pytest | tail` was re-run as pytest alone;
  "18 passed" read as the new tests passing while the append never executed —
  caught only when a mutation run selected zero of the new tests.
  (git-hygiene states this for git state; the hazard is any compound.)
- A pipeline reports the pipeline's semantics, not automatically the producer's
  exit status. Capture and gate the intended command explicitly.
- A `run_in_background` command's completion notification carries the WRAPPER's
  final exit status. `cmd > log; tail log` notifies exit 0 even when cmd failed
  (2026-08-25: a judge run that correctly exited 1 on its own gate was reported
  as a successful background task). End background wrappers with explicit rc
  propagation (`; rc=$?; ... ; exit $rc`) or run the verdict command alone.
- `npm install <pkg>` PRUNES node_modules entries absent from package.json —
  it removed jsdom (the render gate's engine) while adding pptxgenjs
  (2026-08-25). Pin every load-bearing dep in package.json before installing
  anything else.
- Do not put an important producer behind an early-closing consumer such as
  `grep -q`; it can terminate the producer before artifacts flush.
- Do not use a foreground sleep or poll longer than the tool timeout. Use the
  supported background/wait mechanism, bounded polling, and durable output.
- A background child that reads stdin must receive an explicit descriptor;
  its owner remains responsible for polling and cleanup.
- Do not infer process health from a wide command-line listing when launcher
  environments may contain secrets.

## BSD dialect gaps whose failure mode is SILENCE (macOS)

macOS ships BSD tools, and the ones below fail by emitting NOTHING with exit 0 — which is
indistinguishable from the negative result you were hoping for. All measured 2026-08-24, in
one session:

- **`grep -qv PATTERN` is not the inverse of `grep -q`.** `-q` reports whether the PATTERN
  matched, not whether the inverted selection is non-empty. BSD grep returned `rc=1` while
  `grep -v PATTERN | wc -l` reported **109** non-matching lines. Use `grep -c` and compare
  the integer.
- **BSD `sed` BRE has no `\|` alternation** (a GNU extension), so
  `sed -n '/passed\|failed/p'` matches the LITERAL string `passed|failed`. Proved with a
  control: the BRE form printed nothing on a real `52 passed` run, while
  `sed -nE '/passed|failed/p'` printed both lines. Use `sed -E`.
- **`producer | head -N || echo "no matches"` can never take the fallback.** The `||` binds
  to `head`, which exits 0 on empty input, so absence prints as silence. Different mechanism
  from the `$(producer || echo default)` concatenation trap above — that one produces a wrong
  VALUE, this one produces no branch at all.

The shared root cause is a habit, not three bugs: defaulting to a shell predicate whose
failure mode is an empty stream, then reading the empty stream as a negative result. Prefer a
predicate that emits a NUMBER, and pair every zero with a known-positive control in the same
command.

## An exported AWS_REGION leaks into tests that derive names from it

A test that builds a resource name from `os.environ["AWS_REGION"]` inherits the operator
shell's value, and the resulting failure looks exactly like a code regression. Measured TWICE
in one session (2026-08-25 and 2026-08-26), same repo, same cause: `4 failed, 402 passed` and
later `4 failed` again, both reporting
`'…-desired-123456789012-us-east-2' == '…-us-gov-east-1'` — a commercial region leaking into
a GovCloud suite. Re-running with `AWS_REGION=us-gov-east-1` passed 4/4 both times, and
neither change had touched the rollout path.

The tell is in the assertion's VALUES, not the pass/fail counts: a region mismatch inside a
diff about secrets or IAM means the environment, not the diff. CI is green forever because
its workflow `env:` block pins the region. For any GovCloud repo whose tests derive names
from the region, pin it on the test command — and when a test asserts an env-derived value,
pin it inside the test (`monkeypatch.setenv`) so the suite does not depend on the shell.

## Python and file I/O

- Invoke `python3` on macOS/Linux unless a project-managed interpreter is
  explicitly selected.
- Specify encodings for text I/O. For external APIs, read bytes and decode
  with an explicit, evidence-based policy; `text=True` silently inherits a
  locale.
- Preserve newline and binary semantics for files you did not originate.
- Do not round-trip a formatted JSON/YAML file through load→dump to change a
  few values: the serializer reformats everything (measured 2026-08-24: 3
  intended values → an 18,288-line diff on a 21K-line registry; yaml.safe_dump
  has corrupted long quoted strings the same way). Use anchored text
  replacement with occurrence-count asserts (`assert text.count(old) == 1`),
  then prove validity by parsing the result.
- Do not name scratch modules after standard-library or installed packages.
- Never hand-roll a `urllib` Microsoft Graph probe. Import the shared helper:
  `from msgraph_helper import graph_get, odata_quote` (`bin/msgraph_helper.py`,
  app-only GCC High auth via Keychain, no `az login`). A raw space in
  `$filter=<k> eq '<v>'` makes Python 3.14's `http.client` raise
  `InvalidURL: URL can't contain control characters` BEFORE the request leaves the
  client, and the message never mentions OData or `$filter`. Calling `quote()` is
  NOT sufficient protection: a space left inside its `safe=` set reproduces the
  identical crash, so a guard that only looks for an *unencoded* filter misses that
  shape entirely — `safe` must never contain a space. 60+ occurrences across 27+
  sessions; the fix has lived in the incidents file since 2026-07-05, which loads
  ONLY on demand, so restating it here is a delivery fix, not a duplicate.
  Full: incidents#2026-07-05-6th-recurrence-each-new-hand-rolled-urllib-graph
- Use unique temporary directories rather than predictable shared filenames.
- Keep imports portable for modules collected by cross-platform CI.

## Dependencies and builds

- Do not upgrade all packages at once. Change the smallest dependency set,
  review the lock diff, and run import/runtime verification.
- Hash-pinned locks are platform artifacts unless built for every target — and
  INTERPRETER-VERSION artifacts too. A dependency with a version-conditional
  marker changes the resolved set per Python: `anyio` declares
  `typing_extensions>=4.5; python_version < "3.13"`, so a lock compiled on 3.14
  correctly OMITS it and then hard-fails on 3.12. Compile against the declared
  floor and verify the lock installs under every interpreter that consumes it —
  CI's and the Dockerfile's are frequently different. Note pip enables
  `--require-hashes` IMPLICITLY for a whole file when ANY entry carries a hash,
  so an unflagged `pip install -r requirements.txt` fails on one unpinned
  transitive: `ERROR: In --require-hashes mode, all requirements must have
  their versions pinned with ==`.
  PROMOTED here 2026-08-25 on recurrence. The identical finding — same package,
  same missing dep, same 3.14-vs-3.12 split, same remedy — was already recorded
  2026-08-13 in `knowledge-base/plans/2026-08-12-private-ai-inkling-model-swap-flaws.md`.
  It did not prevent the recurrence because a `plans/` flaw log never loads at
  decision time. A durable lesson written to a non-loading surface is not
  persisted; route dependency-resolution lessons here or to
  `agent-memory/topics/python.md`.
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
  stale tree and silently REVERTS whatever merged since — the checkout reports success
  either way, and every file the new branch does not touch carries pre-merge bytes.
  `git-hygiene` STEP_4 already says to verify the base; it was skipped TWICE in one
  session (2026-08-26), each time reverting a PR merged minutes earlier, and both were
  caught only by an incidental "file changed on disk" notice. Fetch in the SAME command:
  `git fetch origin main && git checkout -B <b> origin/main`.
  Staged gate: `hooks/staged/branch-base-freshness-guard.spec.md`.
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
commit did NOT happen. This is a DIFFERENT facet from the
pipe-masks-exit-status family below — there was no `&&`/`||` here and no gate;
the filter simply showed the wrong END of the output, and `tail` is normally
where errors live. Measured 2026-08-26: `git commit -F msg | tail -6` displayed
six green hook lines and read as success; `git log` still pointed at the base
commit, and the suppressed HEAD of the output was `canonical knowledge-base
check … Failed` with two real errors. For any state-changing command, redirect
to a file and read that, capture `$?`, and assert the intended STATE afterwards
(`git log --oneline -1`, `git status --short`) rather than believing whichever
end of the output the filter chose to show.

- ECHO A RESOLVED ID AND STOP IF IT IS EMPTY. An empty shell capture
  interpolated into an AWS `--ids`-family argument does not error — it returns
  a DIFFERENT resource's data, which reads as a successful answer. Measured
  2026-08-29: `SG=$(... --query 'Groups[0].GroupId' ...)` came back empty
  because the task had STOPPED and its ENI was already deleted, so
  `describe-security-groups --group-ids ""` returned some other group, and its
  egress rules were one step from being published as a release runner's
  security posture. The shell printed `runner SG: ` with nothing after it and
  the plausible JSON below it carried the read. Gate on the capture (`[ -n
  "$ID" ] || exit 1`), and prefer IaC/source over an ephemeral runtime object
  for a configuration claim — the runtime object disappears when the task does.


Detailed platform incidents and command-specific mechanisms are retained in
`rules/incidents/platform-constraints.md`; host-specific active overlays are
under `platform-rules/` and load only on the matching host.
