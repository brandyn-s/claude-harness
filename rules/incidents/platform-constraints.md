---
paths:
  - "**/rules/platform-constraints.md"
  - "**/rules/incidents/platform-constraints.md"
---

# platform-constraints incidents (T2)

T2 incident detail extracted from `rules/platform-constraints.md` per the
T1/T2 split pattern: strongwording (INVARIANT/FORBIDDEN/GUARD/PROCEDURE) stays
ambient; verbose INCIDENT narratives live here and are read on demand when
the rule's pointer surfaces a relevant slug.

Each section anchor matches the slug used in the parent rule's `INCIDENT
<date>:` pointer line. To find the parent reference: grep
`rules/platform-constraints.md` for the anchor slug.

---

## wide-process-listing-secret-leaks

### 2026-05-10 roundtable-debug

Wide process listing filtering on `*roundtable*harness*` surfaced 9 bash
launcher processes with inlined env including a real CONFLUENCE_API_TOKEN.
The token value landed in the session transcript; token rotation was the
only mitigation. Per /distill 2026-05-10.

### 2026-05-19 example-app-prod-deploy

`pgrep -af "terraform"` and `ps aux | grep terraform` used twice during a
WSL terraform debug session to check if init/plan was still running. Each
invocation matched the bash launcher process whose CommandLine inlined the
parent's AWS_SESSION_TOKEN — the full token landed in the transcript.
Same root cause as 2026-05-10; the Linux/WSL analog of the pwsh
Get-CimInstance pattern. The `pgrep -a` flag prints CommandLine; the
`-a` is what makes it dangerous, not pgrep itself.

USE for "is it still running?" checks: `pgrep -f PATTERN` (PIDs only,
no CommandLine), or `pgrep -l -f PATTERN` (PID + process name only).
AVOID `pgrep -a` / `pgrep -af` / `ps aux` / `ps -ef` entirely when
the launcher env has any inlined secrets (AWS_*, GH_TOKEN, *_API_KEY).
USE when you need a specific PID's args: `ps -p <pid> -o command=`
AFTER you have already confirmed the PID is your target binary via
the safe forms above.

### pwsh-side guidance (extracted from the parent FORBIDDEN, 2026-06-10 descope)

USE for PID lookup by process name only:
  `Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
   Select ProcessId, Name`
  — narrow the SELECT to columns that don't include CommandLine.
USE for command-line pattern matching when secrets may be present in
the launcher env: narrow with the WHERE filter to a specific Name
FIRST, then Select only ProcessId. Only inspect a specific PID's
CommandLine after confirming the matched process is your target
binary (e.g. the python.exe running your script), not a bash launcher
carrying the inlined env block.
FORBIDDEN: `Where-Object {$_.CommandLine -like '*<pattern>*'} |
  Select ProcessId, CommandLine | Format-List` — every bash launcher
  process whose command line matches the pattern will dump its inlined
  env block (Confluence/AWS/Tenable/etc. tokens) into the transcript.

### 2026-06-11 pgrep -f substring false-positives (claude-hud diagnosis)

`pgrep -f brew` (probing for an in-flight brew upgrade) returned 5 PIDs —
all python3.14 MCP servers and `npm exec` processes whose argv contained
/opt/homebrew/... paths; ZERO were brew. On a Homebrew host, `-f` matching
the full argv means short generic patterns ("brew", "node", "python")
match nearly every developer-tool process. The prescribed per-PID
verification (`ps -p <pid> -o comm=`) caught it before a wrong "brew is
mid-run" conclusion shaped the diagnosis. The existence-vs-runnability
lesson generalizes: a pgrep match proves a string appears in some argv,
not that the named program is running.

---

## claude-p-batch-unreliability

### 2026-04-29 Exp 1/4 invalidation

40% (Exp 4) and 60% (Exp 1) `claude -p` subprocess error rates invalidated
both experiments. ~$25 API spend wasted before the methodology was caught.
Cosine-baseline finding from Exp 7 only survived because its error rates
were uniform across treatments (rank ordering preserved). Lesson distilled
to this rule on the same date.

### Extracted guidance (from the parent FORBIDDEN, 2026-06-10 descope)

`claude -p` (headless mode) is for interactive/one-off invocations.
Sequential batch use (>20 calls) hits 40-60% error rates from
accumulated subprocess startup costs, MCP-server connection latency,
and 180s timeout sensitivity on long traces.
USE: anthropic SDK directly via Python (`pip install anthropic`,
`Anthropic().messages.create(...)`) for batch ≥20 calls. The SDK
bypasses Claude Code's subprocess machinery entirely and is reliable
at 1000+ calls.
USE claude -p ONLY for: spot probes, single-task validation,
experiments testing Claude Code-specific features (ToolSearch,
--allowedTools, agent dispatch).

---

## piping-long-running-script-to-tail

### 2026-03-16 code-graph index

Go slog output never appeared because of pipe buffering; documented in
knowledge-base/topics/code-knowledge-graph-architecture.md but only as a
topic-page entry, not an ambient rule.

### 2026-05-02 code-search PSM-full eval

838-query run piped to `| tail -80`, showed 0 lines for ~5 min before
re-spawning monitoring; same root cause, second session. Promoted to T1
rule on second recurrence per check-before-change.

### 2026-07-30 the background NOTIFICATION reports the trailing command — redirecting does NOT fix it

A distinct facet of the same mechanism, and the reason "just redirect instead of
piping" is insufficient. Hit TWICE in one session on the SAME PR (#1785).

**First:** `python3 ~/.claude/bin/pr-merge-verified.py 1785 --repo … 2>&1 | tail -20`
under `run_in_background`. The task-completion notification said
`completed (exit code 0)`. I read that as the script's contract — which is
specifically *exit 0 ONLY on `state == MERGED`* — and reported the PR merged. The
script had actually exited **2 (20-minute timeout)**; `gh pr view 1785 --json state`
showed `OPEN`. The pipe handed the notification `tail`'s status.

**Second, after "fixing" it:** re-ran as `… > /tmp/claude/pr1785_merge_v2.log 2>&1; echo $?`.
That made the true exit code visible **in the log** — and the notification STILL
reported exit 0, because the last command in the invocation was now the `echo`.
The redirect fixed observability and not the notification, which is the thing that
actually wakes you up and the thing I had acted on the first time.

**Why this is worse than the plain pipe case.** A masked exit code on an
interactive call is one bad turn. Here the masked code belonged to a script whose
ENTIRE purpose is to collapse a multi-state merge outcome (MERGED / DIRTY /
timeout / CLOSED) into one trustworthy integer. Masking it destroys the only
signal the tool exists to produce, and the failure is silent and plausible.

**The structural fix:** the script is the FINAL command in the invocation, nothing
after it — no filter, no `echo $?`, no `&& gh pr view`. Then read the verdict from
the STATUS FILE or the log body, never from the notification's summary line. For a
merge specifically, `pr-merge-verified.py --status-file` + `gh pr view <N> --json state`
is authoritative; `/retro` Step 5 already prescribes exactly this ("that file,
never a piped exit code, is the merge verdict") — the guidance existed and the
invocation shape defeated it.

Fourth-and-fifth observed instances of the pipe-masks-exit-status class; see
`#pipe-masks-exit-code-for-chaining` for the `&&` and `||` directions.

### Mechanism (extracted from the parent FORBIDDEN, 2026-06-10 descope)

Bash invocation `cmd 2>&1 | tail -N` (no `-f`) reads ALL of cmd's
stdout into a buffer and only prints the last N lines after cmd
exits. For a 60-90 minute script with progress prints, the result is
an empty output file the entire time, then a sudden flush at the end.
Symptoms: monitoring tail shows 0 lines, you assume the script hung,
you spawn a process query, you find the script IS running fine.
~5 min of unnecessary investigation per recurrence. The same applies
to chaining `| grep PATTERN`, `| head -N`, or any
non-`--line-buffered` filter onto a long-running script whose output
you want to monitor progressively. Use `tail -f <log-file>`
separately to monitor — the `-f` is required for follow; bare
`tail -N` is read-and-exit.

---

## inner-ampersand-in-background-bash

### 2026-05-12 code-graph corpus clone

Launched `bash clone_corpus.sh > /tmp/clone-corpus.log 2>&1 &` +
`echo "Launched..."` under `run_in_background: true`. Outer shell returned
in <1s; the harness reported exit_code=0 + "completed"; the clone script
had started 2 git clones (lua, kotlin) and orphaned. Disk showed 1
directory (`rust` from a prior run). Recovered by relaunching with the
bare `bash clone_corpus.sh` form. ~3 min wasted.

### Mechanism (extracted from the parent FORBIDDEN, 2026-06-10 descope)

When using `run_in_background: true`, the outer Bash tool harness
already runs the command in the background. Adding `cmd > /tmp/log
2>&1 &` then `echo ok` makes the OUTER shell return immediately,
which means the inner background process is orphaned the moment the
outer shell exits. On Windows Git Bash, the orphan is often killed by
the process-tree reaper before its work completes — the harness
reports `exit_code=0` and "completed" but the actual work ran for 2
commands and stopped. The command itself is what runs in the
background: write it directly (`bash my_script.sh > /tmp/log 2>&1`,
no inner `&`); the tool-level `run_in_background: true` handles the
rest, and output lands in the harness-managed output file (query
later with `tail` on that file). For shell scripts, redirect inside
the script if you need a custom log path — the script as a whole runs
in the harness's background; the script body is foreground from its
own perspective.

---

## subprocess-args-32k-limit

### 2026-04-29 Exp 6 attempt 1

51K-char trace + MAST prompt exceeded the Windows CreateProcess 32K argv
limit. Self-corrected by switching to stdin; lesson distilled to prevent
re-discovery.

### Mechanism (extracted from the parent FORBIDDEN, 2026-06-10 descope)

Windows CreateProcess has a 32K argv limit. Passing a long prompt via
`subprocess.run([...prompt])` raises FileNotFoundError [WinError 206]
"filename or extension is too long" — misleading, not a missing file.
Pass via stdin instead: `subprocess.run([cmd],
input=prompt.encode("utf-8"), capture_output=True)`. The subprocess
module routes stdin correctly; the binary reads from stdin instead of
argv, no limit.

---

## str-format-on-json-prompt-template

### 2026-05-18 strategic_synthesis hook

The SYNTHESIS_PROMPT included a JSON example with keys like `"goal"`,
`"outcome"`, etc. `prompt = SYNTHESIS_PROMPT.format(transcript_slice=...)`
raised `KeyError: '\n  "goal"'` because `.format()` treated `{\n  "goal":
...}` as a placeholder. Caught only by the live integration test — the
unit tests didn't exercise the real prompt-build path. Fixed by switching
to `SYNTHESIS_PROMPT_TEMPLATE.replace("__SLICE__", transcript_slice)`.

Lesson: live-test prompt templates that contain structured-data examples
before treating `.format()` as safe.

### Extracted guidance (from the parent FORBIDDEN, 2026-06-10 descope)

When building an LLM prompt template that includes a JSON schema
example, code snippet, or any other text with literal `{` / `}`,
`str.format(slot=value)` interprets every brace as a format
placeholder and raises KeyError on the JSON keys. Use
`.replace("__SLOT__", value)` (or another unambiguous placeholder
token); the `Template` class with `$slot` also works.
ALTERNATIVE: escape every brace as `{{` / `}}` — works but is
error-prone when the example is large or copy-pasted from real JSON.
The placeholder-replace approach is more maintainable.

---

## awk-multiline-on-macos

### 2026-05-20 jamf install.sh

Passed AWS_CONFIG_SNIPPET and SHELL_WRAPPER (both multi-line heredoc-built
strings) via `awk -v payload="${payload}" ...`. Shipped through PRs #933,
#935, #937 — each verified only with `bash -n` (syntax check, doesn't
touch awk semantics). First end-to-end macOS deployment via
`sudo jamf policy` produced three identical "awk: newline in string ;
BEGIN claude-gov m... at source line 1" errors (one per
`update_managed_block` invocation), exit code 2. Fixed in PR #938 via
temp file + getline pattern. Cost: 1 follow-up PR, Jamf log flush, and
re-run on test Mac.

The broader lesson — cross-platform shell scripts need outcome
verification on every target platform, not just plumbing checks on the
author's box — is already covered by verify-effectiveness.md
`two_part_validation_is_mandatory`.

### Temp-file + getline pattern (extracted from the parent FORBIDDEN, 2026-06-10 descope)

```
payload_file="$(mktemp)"
printf '%s\n' "$payload" > "$payload_file"
awk -v file="$payload_file" '
  $0 == marker {
    while ((getline line < file) > 0) print line
    close(file)
    next
  }
  { print }
' "$input" > "$output"
rm -f "$payload_file"
```

Enforcement scope: applies to any shell script that may execute on
macOS — cross-platform Jamf payloads, brew tap scripts, mobile CI
shims, any *-init.sh you ship to a Mac. GNU awk (gawk) on Linux
accepts the same value silently, so this is a portability landmine:
scripts authored on Linux work in development and break on first
macOS deployment.

### bsd-awk-failure-mode (companion FAILURE entry)

SYMPTOM: shell script using `awk -v var="${multi_line_payload}" ...` works
on every Linux test but emits "awk: newline in string ... at source line
1" on first run under macOS, often via Jamf Pro, LaunchDaemon, or other
MDM-pushed execution path. The "source line 1" cite is misleading — defect
is in the -v value, not the awk script.

CAUSE: macOS ships BSD awk (one-true-awk); `-v var=value` rejects raw
newlines in the value. gawk accepts them.

RECOVERY: stage the value to a temp file via mktemp + printf, then pass
the file path via -v and read with `getline line < file` inside the
matching awk block. Same approach unifies the create/replace/append code
paths (cp file, awk-getline file, cat file).

DETECTED: 2026-05-20 in templates/cui-bedrock-govcloud/jamf/install.sh
after three PRs (#933, #935, #937) shipped without a Mac test run. Cost:
one follow-up PR (#938), Jamf log flush, and re-execution on the test Mac
before the wrapper deployed successfully.

---

## pwsh-smart-quote-lexer

### 2026-05-20 PowerShell_profile.ps1

Mojibake `â€"` on line 49 (UTF-8 bytes `c3 a2 e2 82 ac e2 80 9d` — a chain
ending in U+201D) closed a Write-Host string. Parser reported error on
line 141 (`Set-Item "env:$k" -Value $saved[$k]`) where it finally bailed.
Real fix: replace `â€"` with `-` on line 49. Time wasted before
diagnosing: ~3 turns inspecting line 141 and surrounding code.

### Mechanism + diagnostic (extracted from the parent rule, 2026-06-10 descope)

PowerShell 7's lexer treats Unicode "smart quotes" (U+2018 / U+2019 /
U+201C / U+201D) as STRING DELIMITERS equivalent to ASCII ' and ".
Any smart quote silently closes the surrounding string; "missing
terminator" is reported on a line FAR from the real defect.
REQUIRED diagnostic: scan the file for non-ASCII bytes BEFORE the
cited line (`python -c "data=open(p,'rb').read(); ..."`); replace
smart quotes with ASCII `"` / `'` / `-`.
COROLLARY: paste-as-plain-text into .ps1 sources, OR run a
smart-quote scrub before saving. Word, Slack, and browser UI
auto-convert straight quotes silently.

---

## s3-presigned-url-kms

### 2026-05-19 ExampleApp admin upload

User reported `S3 PUT failed 400` with the KMS SigV4 error body. boto3
client was bare `boto3.client("s3")` and us-east-1, fell back to SigV2 for
presigned URLs. Bucket had KMS default encryption (likely from an AWS
account-level Config rule, not explicit in Terraform). Fixed via
`Config(signature_version="s3v4", addressing_style="virtual")` in
api/admin/handler.py.

### Mechanism (extracted from the parent rule, 2026-06-10 descope)

S3 buckets with SSE-KMS default encryption (or org-level SCP/Config
rules that force KMS) reject SigV2-signed PUT requests with HTTP 400:
`InvalidArgument: Requests specifying server side encryption with AWS
KMS managed keys require AWS Signature Version 4`. boto3's default s3
client in us-east-1 can fall back to legacy SigV2 for presigned URLs
when no signature_version is configured. The bucket's PutObject works
fine when boto3 calls it directly (SigV4 by default for api calls),
but generate_presigned_url() can emit SigV2 URLs that later fail when
the frontend XHR PUTs against them. The default behavior is silent;
the failure surfaces in the frontend (browser XHR) hours/days later
when someone uploads a file, with a 400 from S3 that doesn't
immediately point at SigV2 vs V4. The fix is one Config kwarg; the
cost of being wrong is debug hours.

---

## pip-upgrade-namespace-package

### 2026-05-17 fastmcp 3.2.4 → 3.3.1

`pip install --upgrade fastmcp==3.3.1` across 3 production venvs left
`fastmcp/server/` missing because `fastmcp-slim-3.3.1` (a new transitive
dep of 3.3.1) installed only `client/`, `utilities/`, `_install_hints.py`
into the package dir. 7 stdio MCP servers disconnected mid-session with
`ImportError: cannot import name 'FastMCP' from 'fastmcp' (unknown
location)`. An isolated venv that did `pip install fastmcp==3.3.1` from a
fresh `python -m venv` installed cleanly — the regression was specific to
the `--upgrade` install path on production venvs that previously had
3.2.4. Resolution: `pip uninstall fastmcp fastmcp-slim`, then fresh
`pip install --no-cache-dir fastmcp==3.3.1`.

COROLLARY for verification: compat tests that import the new version in
a FRESH venv prove nothing about the `--upgrade` install path. See
`rules/verify-effectiveness.md` FAILURE
`compat_test_used_fresh_install_not_upgrade_path`.

### Symptom signature (extracted from the parent FAILURE, 2026-06-10 descope)

SYMPTOM: `ImportError: cannot import name 'X' from '<pkg>' (unknown
location)`; `<pkg>.__file__ is None`; `<pkg>.__path__` is
`_NamespacePath`; listing `site-packages/<pkg>/` shows only a subset
of expected subdirs.
The safe uninstall+install sequence is REQUIRED whenever the new
version's description, changelog, or PyPI page mentions "namespace
package", "split into", "now requires", or a sibling package with the
same prefix (e.g., fastmcp + fastmcp-slim).

---

## git-worktree-bash-path-mangle

### 2026-04-22 + 2026-04-24 code-graph + sbom-rs-baseline

Detected 2026-04-22 in code-graph main worktree setup; RECURRED 2026-04-24
using `$HOME/tmp/sbom-rs-baseline` (same failure mode — `$HOME` expands to
`/c/Users/...`, which git passes verbatim). The earlier rule version
recommended `$HOME/...` as a workaround; that turned out wrong. Explicit
`C:/...` is the only reliable path.

### Mechanism (extracted from the parent rule, 2026-06-10 descope)

Git Bash does not translate paths before passing to git on Windows.
`git worktree add ~/tmp/foo` and `git worktree add $HOME/tmp/foo`
BOTH create the worktree at `C:/c/Users/you/tmp/foo` (a
literal "c" directory under drive C), not at the intended Windows
location. Silent — git reports success; `git worktree list` shows the
mangled path. Recovery: `git worktree remove "C:/c/Users/..."
--force` then retry with an explicit `C:/...` path.

---

## msys-path-to-native-windows-binary

### 2026-04-24 sbomgen --repo

Running `sbomgen ship --repo /c/Users/.../example-monorepo`
produced `Cargo.lock not found at
/c/Users/you/Documents/GitHub/example-monorepo\Cargo.lock`.
Same target worked with `--repo
"$HOME/Documents/GitHub/example-monorepo"`.

### Mechanism + CORRECTION 2026-05-31 (extracted from the parent rule, 2026-06-10 descope)

MSYS-style paths (e.g. `/c/Users/...`) are a Git Bash convention, not
a Windows filesystem convention. Native Windows binaries invoked from
Git Bash — including any Rust binary in `target/release/*.exe`,
sbomgen itself, any downloaded .exe tool — do NOT translate them. The
binary sees the literal string `/c/Users/...` and interprets it as a
relative path from CWD, usually producing a confusing error like
`file not found at /c/Users/foo\Cargo.lock` (mixed slashes).

CORRECTION 2026-05-31: an earlier version of the parent section
claimed "Git and gh tools DO translate via MSYS_ARG_CONV_EXCL
internals, which is why `git -C /c/Users/...` works." That premise is
FALSE in this environment. `git` is itself a native Windows binary
and MSYS arg-conversion is NOT applied to its path argument here:

```
git -C /c/Users/you/.claude status
  -> fatal: cannot change to '/c/Users/you/.claude':
     No such file or directory   (exit 128)
git -C C:/Users/you/.claude status   -> works (exit 0)
```

Treat git's filesystem-path arguments (`-C`, `--git-dir`,
`--work-tree`) exactly like any other native binary's: they need
Windows-form paths. gh is affected ONLY when handed a filesystem
path; `gh --repo org/repo` and `gh api repos/...` take no fs path and
are unaffected by this. When the path derives from `$HOME` inside a
bash script, convert it FIRST: `HOME_WIN="$(cygpath -m "$HOME")"`,
then build `"$HOME_WIN/sub/dir"`. `cygpath -m "$HOME"` yields
C:/Users/... .

### 2026-05-31 pr-fix dirty-scan

/pr-fix + /retrospective discovery loops built repo paths from $HOME
(MSYS /c/Users/...) and ran `git -C "$repo"` over them; EVERY call
failed exit 128 and — stderr swallowed by 2>/dev/null — the scan
silently reported every repo clean (~/.claude shown clean while 12
files dirty). Fixed by cygpath -m'ing $HOME first (claude-config PR
#1108). This is what disproved the "git -C /c/... works" claim
corrected above.

---

## rust-debug-stack-overflow-windows

### 2026-04-21 sbom-rs schema_validate

The debug binary overflowed before clap finished parsing `--version`.
Symptom: spawned binary exits with -1073741571 (STATUS_STACK_OVERFLOW,
0xC00000FD) immediately on `--version` or any clap parse; release build of
the same binary works fine.

Cause: Windows default thread stack is 1 MiB. Rust debug builds of crates
with heavy proc-macro expansion (clap derive + large `include_str!` assets
like jsonschema's vendored CDX 1.7 schema) exceed it; the optimizer in
release shrinks frames enough to fit.

Recovery: do not spawn the binary from `tests/*.rs` integration tests on
Windows. Put tests as `#[cfg(test)] mod tests` inside the module under
test and call the pure function directly. This is better test design
anyway (no subprocess, faster, deterministic). If a binary-spawning test
is unavoidable, run under release (`cargo test --release`).

---

## pwsh-standalone-secret-read

### 2026-04-26 NVD_API_KEY

Standalone `pwsh -Command "[Environment]::GetEnvironmentVariable('SECRET', 'User')"`
prints the value to stdout, which lands in the Bash tool result and
session transcript. A pwsh standalone read printed the NVD API key to
a Bash tool result; the value persisted in the transcript. Required
key rotation as the only mitigation.

USE for verification:
`pwsh -Command "[Environment]::GetEnvironmentVariable('SECRET','User').Length"`
USE for consumption:
`SECRET=$(pwsh -NoProfile -NonInteractive -Command "[Environment]::GetEnvironmentVariable('SECRET','User')") downstream-tool ...`
The command-substitution form keeps the value in the env passed to
the downstream process; the shell never echoes it. Never run a
standalone "is the key set?" verification call against a secret. The
bash equivalent is covered by the parent's
`secret_env_var_expansion_in_diagnostics`; the pwsh case has the same
effect and is the natural way to read Windows User-scope env vars not
visible to the current bash session.

---

## curl-verbose-auth-header

### 2026-05-01 OPENAI_API_KEY

`curl -v` / `--verbose` / `--trace*` echoes the full request,
INCLUDING request headers, to stdout/stderr. When combined with
`-H "Authorization: Bearer $KEY"` / `"X-API-Key: $KEY"` / similar,
the rendered header lands in the Bash tool result and persists in the
conversation transcript. Incident: `curl -v -H "Authorization: Bearer
$OPENAI_API_KEY" https://api.openai.com/v1/models` printed the full
key to a Bash tool result. Required key rotation as the only
mitigation.

USE for connectivity diagnosis: `curl -sIL` (head only), or `curl -v`
on a public endpoint without -H, or redirect verbose to a sandboxed
file outside the transcript: `curl -v ... 2>~/tmp/curl-trace.log`
(then read it with Read, NOT cat).
USE for authenticated probes: `curl -sS --fail` + check exit code, or
`curl -sS -i` (response headers only — request headers stay private).
ENFORCEMENT: bash-security-guard.py CURL_VERBOSE_WITH_AUTH regex
blocks this combination at PreToolUse. The rule remains documented so
the discipline survives if the hook is ever disabled or bypassed.

---

## wmic-silent-empty-output

### 2026-05-02 SQLite WAL lock-holder search

wmic is deprecated on Windows 11 and returns SILENT EMPTY output (no
error, no rows, exit code 0). Searching for the lock-holder of a
SQLite WAL file used wmic — got no output, mistakenly concluded no
matching processes existed, killed the wrong PIDs (active MCP server
pair) instead of the actual culprit (a stale python.exe subprocess
holding the lock). pwsh Get-CimInstance returned the correct rows on
the first try.

---

## powershell-acl-write-mask

### 2026-05-29 REM051 Claude managed-settings

TESTING: validate the logic against a REAL file round-tripped through
Set-Acl/Get-Acl (mktemp-style temp file) — NEVER an in-memory
`New-Object System.Security.AccessControl.FileSecurity`. An unbound
FileSecurity returns an EMPTY `.Access` after AddAccessRule, so a
loop over `.Access` finds zero ACEs and reports COMPLIANT for EVERY
case, including should-fail ones. A green result with no ACEs
evaluated is a false pass (the verify-effectiveness "harness silently
returns empty set" mode).

WRITE-MASK: `[FileSystemRights]"Write,Modify,FullControl"`
OR-collapses to FullControl (0x1F01FF), whose bitfield INCLUDES the
read bits (ReadData/ReadEA/ReadAttributes/ReadPermissions).
`Read -band FullControl` is therefore nonzero, so the check falsely
flags a legitimate Read ACE as writable.

INCIDENT: a FullControl-collapsed write mask falsely flagged
Users:Read, so the Intune detection rejected its own correct
remediation — non-converging, fired hourly forever. The first
fix-validation harness used in-memory FileSecurity and reported
all-COMPLIANT (empty .Access), nearly shipping a false-negative
detector.

---

## bash-tmp-read-tool-divergence

### 2026-06-05 gather-claude

The Bash tool's `/tmp` and the Read/Write/Edit tools' path resolution
DIVERGE on Windows. A file the Bash tool writes to `/tmp/foo` is NOT
found by `Read("/tmp/foo")`: the Read tool resolves `/tmp/foo`
against the Windows session CWD (e.g.
`C:\Users\you\tmp\foo`, which doesn't exist), while the
Bash tool's `/tmp` is the Git-Bash/MSYS mount (observed: `C:/tmp`).
Read fails with "File does not exist. Note: your current working
directory is C:\Users\...". Bash-internal consumers
(sed/grep/cat/tail on the same `/tmp/foo`) work fine — only the
Read/Write/Edit tools miss it.

INCIDENT: fetched CHANGELOG.md to /tmp/cc-changelog.md via Bash, then
`Read /tmp/cc-changelog.md` failed (resolved to the Windows CWD);
`sed -n ... /tmp/cc-changelog.md` in Bash worked. Recovered by
extracting the section with sed. One-turn detour; the fix is to write
where both tools agree, or read it within Bash. `/tmp` remains fine
for Bash-only redirection + `tail -f` monitoring — the constraint is
specifically the Bash-`/tmp` → Read-tool handoff, not `/tmp` itself.

---

## subprocess-signal-rc-convention

### Platform split detail (PR #991 oracle contract)

Python's `subprocess.CompletedProcess.returncode` uses two different
conventions for signal kills depending on platform. Linux/macOS:
returncode is NEGATIVE (rc = -N for signal N, e.g. -9 for SIGKILL).
Git Bash on Windows: returncode is the shell convention (rc = 128 +
N, e.g. 137 for SIGKILL). Code that only checks one form will be
wrong on the other platform — a `SIGKILL`ed process whose rc was
supposed to map to ERROR / instrument-failure gets misclassified as a
normal predicate result.

RECOVERY: check BOTH forms — `if rc < 0 or rc >= 128:` for
signal-killed; `if rc in (126, 127):` for not-executable /
command-not-found. The oracle's bash reproducer contract (PR #991) is
the canonical example.
PREVENTION: any code that distinguishes signal-killed from predicate
results must handle the platform split. Cross-platform CI (Linux +
macOS + Windows matrix) catches the mismatch at PR time.

## pipe-masks-exit-code-for-chaining

INCIDENT 2026-06-11 mac-port→main convergence (live ~/.claude):
ran `git checkout main 2>&1 | tail -2 && git rebase origin/main 2>&1 | tail -1`
to switch the live config to main after PR #1171 merged. The checkout
FAILED — `fatal: 'main' is already used by worktree at .../claude-config-convergence`
(the post-merge-sync hook had silently re-checked-out main in that
worktree after a `gh pr merge` call). But the pipeline's exit status was
`tail`'s (0), so `&&` proceeded: the rebase ran against the branch that
was actually checked out — `mac-port` — and stopped mid-conflict
("Could not apply 242ba0f5... Port Windows config to macOS"), leaving
the LIVE config repo in rebase-in-progress with 15 conflicted files.
Recovery: `git rebase --abort` restored mac-port cleanly; the worktree
was switched off main; the checkout was re-run bare and verified before
any dependent step.

MECHANISM: in the Bash tool's shell (zsh here; bash elsewhere),
`pipefail` is unset by default — a pipeline's exit status is the LAST
command's. Piping any command to `tail`/`grep`/`head` for display
discards its failure signal, so `&&`/`||` chains gate on the filter,
not the command. This composes badly with the display habit the
tail-buffering guard already pushes against: the guard blocks
`long-cmd | tail` for buffering reasons, but SHORT gating commands
piped to filters pass the guard and still mask failures.

RECOVERY: split gating commands into their own tool call (no filter
pipe) and check the result before the dependent step; or capture rc
explicitly (`cmd; rc=$?; ...`). Do not rely on `set -o pipefail` being
present.

PREVENTION: the FORBIDDEN `chaining_&&_after_a_piped_gating_command`
block in platform-constraints.md. Related: the post-merge-sync hook's
CWD-checkout behavior that set up the failed checkout is documented in
project memory (claude-config-mac-deploy.md); a hook-side fix (no-op
when CWD is a linked worktree on an unrelated branch) is the open
root-cause item.

---

## ipv6-windows-tiers

### Extracted from the parent ON block (2026-06-11, size guard)

macOS test detail (2026-06-10, Tailscale UP):
`getaddrinfo('sts.us-east-2.amazonaws.com')` returns IPv4 only (the AAAA
query yields an IPv4-mapped `::ffff:` address, not a routable AAAA), TCP
connect 0.1s, `boto3 sts.get_caller_identity` succeeded in 2.4s. macOS
Tailscale uses the OS network extension (utun), not the Windows
split-DNS-with-AAAA path that hung boto3/urllib3.

[WINDOWS-ONLY] prior-host protection tiers (Tailscale split DNS handed
back AAAA records, boto3/urllib3 tried IPv6 first and hung):
  1. usercustomize.py (Python 3.12 + 3.13 user site-packages)
  2. urllib3.util.connection.HAS_IPV6 = False
  3. inline socket.getaddrinfo patch (runtimes usercustomize missed)
  4. PYTHONPATH → ipv4-site/ (uv tool install MCPs)
NOT covered by usercustomize: uv-managed Python, AWS CLI bundled
runtime, Python 3.14.

---

## homebrew-partial-upgrade-dyld-skew

### 2026-06-11 node/llhttp blank statusline

A brew upgrade batch at 20:39 (rust 1.96.0, libgit2 1.9.4, golangci-lint,
govulncheck, rust-analyzer, llvm, sqlite — a dev-toolchain refresh) pulled
llhttp 9.4.1 as an upgraded dependency of rust/libgit2 and repointed
`/opt/homebrew/opt/llhttp`. node 25.9.0_2 (Apr 13 bottle, install name
`libllhttp.9.3.dylib`) was NOT in the batch — `brew outdated` still listed
it — so every fresh node spawn died at dyld load: SIGABRT, exit 134, empty
stdout. The statusline launcher's `command -v node` gate passed (the binary
exists) and exec'd into the abort → blank claude-hud. Fixed by
`brew upgrade node` (→ 26.3.0); the launcher was hardened to a runnability
probe in claude-config PR #1184 (`node -e '' </dev/null` — a broken node
now degrades to statusline.py instead of a blank bar).

DIAGNOSIS RECIPE:
  1. Run the failing binary bare — dyld stderr names the missing dylib AND
     the referencing keg path.
  2. `ls -ldt /opt/homebrew/Cellar/*/* | head` dates the skew batch (which
     kegs changed together).
  3. `brew outdated` lists the stale dependents still to be upgraded.
  4. `brew uses --installed <lib>` shows every dependent of the moved
     library; INSTALL_RECEIPT.json in the new keg records what pulled it.

KEY MECHANICS: dyld resolves install names at SPAWN — already-running
processes keep the old library image mapped and work fine (the node-based
tavily/exa MCP servers ran through the entire outage; only fresh spawns
aborted — so do NOT restart long-running processes or Claude Code before
the fix). The old keg may still exist in the Cellar, but nothing points
dyld at it once the `opt/` symlink moves. `brew reinstall <dependent>`
does NOT fix the skew — it re-pours the same bottle with the same install
names; only `brew upgrade` to a bottle built against the new lib works.

RELATED but distinct: `local-mcp-spawn-debugging.md` (KB) covers
parent-context PATH/load-path divergence (same "Library not loaded" error,
different cause — the lib exists but the spawn parent can't see it). The
faiss/torch duplicate-libomp abort (agent-memory/topics/code-search-dev.md)
is also exit 134 but at RUNTIME, not dyld load. The dyld "Library not
loaded" stderr line is the discriminator for THIS mode.

---

## keychain-read-prompts

### Extracted from the parent `ON keychain_read_for_secret` block (2026-06-12, size guard)

PATTERN (shipped 2026-06-11): MCP servers needing API keys use a launcher
script (`~/.local/bin/codebase-memory-mcp-launch`) that reads Keychain at
spawn time and execs the binary — keys never land in `~/.claude.json` or the
broad shell env.

INCIDENT 2026-06-11 code-graph setup: 3 empty reads (wrong assumed service
names, then access-prompt race) cost ~3 turns + one user interruption before
the dump-keychain metadata grep + the user clicking Allow resolved both
shapes.

UPSTREAM ROOT CAUSE for recurring prompts on Claude Code's OWN item
(anthropics/claude-code #67315, confirmed open 2026-06-11): Claude Code
writes `Claude Code-credentials` via Security.framework (`teamid:` partition
only) but reads it by spawning `/usr/bin/security`, which needs the
`apple-tool:` partition — every OAuth token refresh rewrites the item and
RESETS the partition list, so "Always Allow" never persists for that item.
Our own launcher-read items (e.g. codebase-memory-mcp keys) are written BY
the `security` CLI so they keep `apple-tool:` and stay quiet after one
Allow. If endless prompts recur for "Claude Code-credentials", it's #67315 —
don't debug our launchers for it.

---

## hash-pinned-lock-cross-platform

### 2026-06-18 Proteus Polar containerization (PR #64)

While making Proteus Polar (a FastAPI app) deployable to GovCloud ECS Fargate,
the `requirements.txt` was a `--require-hashes` lock compiled on the macOS dev
host (arm64 wheels). The GitHub Actions Python Test step ran on a Linux runner,
where `pip install -r requirements.txt` selected linux/amd64 wheels whose hashes
did NOT match the macOS-authored lock. Because `--require-hashes` is
all-or-nothing, pip refused the ENTIRE install and installed nothing — but the
failure surfaced one step later as import errors in the test run, pointing
nowhere near the lock. The same class of mismatch bites a Docker build whose
`python:3.x-slim` base differs from the authoring host.

TWO bugs compounded across the fix attempts:

1. **First recompile drifted versions.** A bare `pip-compile` on the Linux
   target re-resolved every transitive dependency to that day's newest —
   cryptography 46→48, plus pydantic and starlette — turning what should have
   been a hash/platform-only recompile into a silent version bump. Fixed by
   re-running with `--constraint=requirements.txt` (the existing lock) so only
   the hashes changed, versions held.

2. **kaleido was in the lock but unused.** The Linux recompile was also the
   moment to drop it (Plotly static-image export was not a shipped feature);
   it was removed from the lock and from CLAUDE.md's approved-deps list in the
   same PR.

RESOLUTION: recompile the lock inside an environment matching the deploy target
(Linux/amd64 for ECS Fargate), pin versions with `--constraint`, install in a
clean venv, and import the top-level packages to confirm the lock actually
installs before trusting it. CI went green on the real runner (#64) after the
Linux recompile, which also eliminated the force-merge tax the red baseline had
been imposing.

GENERALIZATION: any `--require-hashes` lock is bound to the platform that
generated its wheel hashes. Authoring on macOS/Windows and deploying to Linux
(Docker, CI, Fargate) is the common trigger. The signature is a "successful"
install that installed nothing, surfacing later as ModuleNotFoundError —
distinct from a loud hash-mismatch error, because pip's all-or-nothing refusal
can read as a no-op rather than a failure depending on how the step's exit code
is checked. Pairs with `ON docker_image_build_for_ecs_fargate_from_apple_silicon`
(the arm64-image-on-amd64-Fargate sibling) — both are "authored on Apple Silicon,
deployed to amd64 Linux" footguns.

## bash-tool-grep-is-ugrep

### 2026-07-09 compliance-key sweep phantom-zero

A repo-wide discovery grep for compliance-key references returned ZERO hits with
`2>/dev/null` attached — including on a launcher file known to contain the pattern.
Cause: the pattern used an empty alternation (`COMPLIANCE_(ACCESS_|API_|)KEY`), and
the Bash tool's `grep` is not BSD/GNU grep: Claude Code injects a zsh function that
re-execs the `claude` binary as an embedded **ugrep 7.5** (`ARGV0=ugrep`, flags
`-G --ignore-files --hidden -I --exclude-dir=.git ...`). ugrep rejects empty
alternations with `error ... empty (sub)expression`; the silenced stderr turned the
hard error into an apparent no-match. Caught by the 0-hits-on-plausible-phenomenon
discipline (verify-before-assuming); rewriting as `(ACCESS_|API_)?` found 23 files.

Consequences beyond the regex dialect:

- `--ignore-files` means **gitignored files are invisible** to `grep -r` in this
  shell — a coverage gotcha for credential/census sweeps. `command grep` bypasses
  the function and runs real BSD grep for a raw scan.
- Basic-regex `-G` is the default (the function passes `-G`), so `-E`/`-P` behave
  per ugrep's dialects, not BSD's.
- The function is harness-injected (has msys/zsh branches) — this is true on every
  Claude Code host, not just macOS.

### Mechanism check

`which grep` errors (function, not a file); `grep --version` prints
`ugrep 7.5.0 aarch64-apple-macosx`; `type grep` shows the function body with
`ARGV0=ugrep "$_cc_bin"`.

### pipe-masks-exit-code-for-chaining — RECURRENCE 2026-07-09

`git merge --ff-only origin/main 2>&1 | tail -1 && git log --oneline -1` during a
post-merge sync of the contended ~/.claude checkout: the merge REFUSED (another
session's dirty in-flight files would be overwritten), but tail exited 0, the `&&`
chain proceeded, and the output ("Updating a..b" + a log line) read as success while
HEAD never moved. Third instance of the class; detected because the log line showed
the OLD commit. The correct shape remains: run the gating command bare (or redirect
to a file), check its exit, THEN run dependents in a separate call.

### pipe-masks-exit-code — the `||` FALLBACK variant (RECURRENCE 2026-07-29, 5th)

A new direction of the same mechanism. Every prior instance was `&&`-after-pipe, where
the filter's exit 0 lets a dependent step run that should have been SKIPPED. The `||`
form inverts it: the filter's exit 0 **suppresses a fallback that should have fired**.

```bash
# WRONG — emits an EMPTY value, never "0"
printf 'METRIC hook_name_distinct=%s\n' "$(python3 athena.py m3.sql | tail -1 || echo 0)"
```

`hook_name` did not exist in gold yet, so the query errored — but the pipeline's status
is `tail`'s (0), so `|| echo 0` never ran and the metric printed as
`hook_name_distinct=` with nothing after it. A plan's own baseline metric block emitted
a blank where it claimed a number; a reader would see an empty string, not a zero, and
an automated comparison against a threshold would compare against `""`.

```bash
# RIGHT — capture, then default on the captured value
HN="$(python3 athena.py m3.sql 2>/dev/null | tail -1)"
case "$HN" in ''|*[!0-9]*) HN=0 ;; esac
printf 'METRIC hook_name_distinct=%s\n' "$HN"
```

Generalisation for the rule: **any** `cmd | filter <op> fallback` is broken, not just
`&&`. `||`, `;`-chained recovery, and `$( … || default )` all read the filter's status.
The safe shape is always capture-then-branch on the captured value.

Note the enforcement state: `hooks/staged/tail-guard-preserve-exit-status.spec.md`
(staged 2026-07-25) and `hooks/staged/git-gating-pipe-guard.spec.md` (2026-07-22) both
address this class and are **still staged, not installed** — so the 5th recurrence
happened with the fix written and sitting on the shelf. That is the actionable item
here, not more prose: install via `/ship-hook`.

**RESOLVED 2026-07-31 for the `;`-chained trailing-command direction.** The
`trailing-command-swallows-verdict-exit` spec is INSTALLED as
`check_trailing_status_swallow()` in `bash-tail-buffering-guard.py` (v8), together
with `tail-guard-wrapper-producer-detection`. It BLOCKS a verdict command whose
status is overwritten by a trailing `;`-chained command — measured 607 fires over
49,542 historical Bash commands (1.225%), mutation-verified, 9 permanent tests.
Two instances the same day it was installed (#1818, #1819) had made the count 5,
one of them a false merge confirmation reported to the user; that specific shape
is now enforced rather than documented. The `&&`/`||`-after-pipe directions above
remain prose-only — the named specs for those are separate and their state is
unchanged by this install.

## urllib-odata-filter-encoding

### 2026-07-16 grant_write_scopes recurrence — 6th+ instance, new call site

Writing an M365-connector write-scope grant script (`grant_write_scopes_v1.py`, a
hand-rolled `req()` wrapper around `urllib.request` against `graph.microsoft.us`),
the OData `$filter` GET hit:

```
http.client.InvalidURL: URL can't contain control characters.
"/v1.0/oauth2PermissionGrants?$filter=clientId eq '59ea9cad-...'"
(found at least ' ')
```

Root cause and fix are already fully documented — `agent-memory/topics/msgraph.md`
"Python 3.14 urllib mishandles a Graph API `$filter` query param" entry, RESOLVED
2026-07-11 after ~5 prior recurrences in one PIM-build session. `urllib.request`
does not percent-encode the request path the way `requests`/`httpx` do; any literal
space in a `$filter=<key> eq '<value>'` string raises this exact error, and the
message never mentions OData or `$filter` — it reads as a generic malformed-URL
bug. Fix applied here: `urllib.parse.quote(path, safe="/?$=&'()")` on the whole
path before constructing the `Request` (equivalent to the topic file's
value-only-quote fix; either form works).

Why this is now a rule and not just a topic-file note: this is the 6th+ documented
recurrence, and every one was a DIFFERENT script/call-site hitting the identical
root cause — the topic file's writeup is accurate and complete, but a well-written
topic entry does not get consulted before someone writes a new raw-`urllib` Graph
script from scratch. The fix (`urllib.parse.quote` before building the `Request`)
is cheap enough to just always apply on sight of `$filter=` + string concatenation
into a URL, rather than re-deriving it from the error message each time.

---

## aws-config-sso-profile-access

### 2026-07-20 secplat profile creation (Bedrock GovCloud enablement)

Needed a new SSO profile targeting Security-Platform (123456789012) with the
AdministratorAccess permission set (the SCP-exempt principal for
`aws-marketplace:Subscribe`). Three friction points, ~5 turns:

1. **Both read paths to ~/.aws are hook-blocked now.** `cat ~/.aws/config`
   and an inline Python `open()` on `~/.aws/sso/cache/*.json` were BLOCKED by
   credential-guard; the Read tool is permission-denied on `~/.aws/`. The
   parent rule's old "Python open() + json.load() on the cache" workaround is
   stale — it predates the credential-guard coverage. Working paths:
   `aws configure get profile.<name>.<key>` (reads one key, no secret
   exposure), `aws configure set` (writes), `aws configure list-profiles`.

2. **SSO token cache is keyed by sso_session name, not start URL.** A new
   profile built with `sso_start_url`/`sso_region` keys errored
   "Error loading SSO Token: Token for <url> does not exist" despite a live
   login, because existing profiles use `sso_session = example` (modern
   format; token cached under the session name). Fix:
   `aws configure set profile.<new>.sso_session example` + account id +
   role name + region — the existing login covers any profile referencing
   the same session.

3. **`aws configure set` cannot delete keys.** Setting the stale
   `sso_start_url` to an empty string left an empty key that conflicted:
   "The value for sso_start_url is inconsistent between profile () and
   sso-session". Recovery: abandon the broken profile section and create a
   fresh profile with only the correct keys (secplatform-admin → secplat).

Result: `secplat` profile = SSO AdministratorAccess on 123456789012
(assignment self-granted via `aws sso-admin create-account-assignment` from
the management account; left standing per only-grant-do-not-revoke).


## background-job-stdin-from-devnull

### 2026-07-26 run-hook trap: deferred trap, then lost stdin (claude-config #1714)

Adding a SIGTERM trap to `hooks/run-hook` so timed-out hook fires stop being
invisible to telemetry took THREE shapes to get right. Both wrong shapes were
found by measurement, not reasoning — and the second would have silently broken
every hook in the fleet.

**Shape 1 — trap around a FOREGROUND child (measurably worse than no trap).**

```bash
trap _log_killed TERM INT HUP
run() { "$@" && code=0 || code=$?; _log_fire "$code"; exit "$code"; }
```

Bash **defers a trap handler until the current foreground child returns**, so a
SIGTERM to the wrapper is queued while `python3` is still running. Measured: the
wrapper HUNG past 8s and logged nothing, versus dying immediately (child
reparented) with no trap at all. A trap around a foreground child is strictly
worse than none.

**Shape 2 — backgrounded child (fixes the trap, silently loses stdin).**

```bash
run() { "$@" & _child=$!; wait "$_child" && code=0 || code=$?; ... }
```

`wait` IS interruptible, so the trap now fires in 0.14s and logs `exit=-1`. But
**bash points a background job's stdin at `/dev/null` when the wrapper's own
stdin is a PIPE** — which is exactly how Claude Code delivers every hook payload.
Every hook would have read empty input and failed to parse its JSON.

**The false green that nearly shipped it.** A shell diagnostic comparing three
shapes with a HEREDOC input showed all three printing the payload — so
backgrounding looked innocent. A heredoc is a **seekable temp file**, not a pipe,
and passes even in the broken shape. Only re-testing with `subprocess.run(input=...)`
(a real pipe) exposed it: `json.load(sys.stdin)` raised `JSONDecodeError`.

**Shape 3 — correct.** Duplicate stdin onto fd 3 before backgrounding:

```bash
exec 3<&0
run() { "$@" <&3 & _child=$!; wait "$_child" && code=0 || code=$?; ... }
```

Verified across the whole wrapper contract (stdin delivery over a pipe, exit-2
block passthrough, exit-0 stdout, crash forwarding, prompt SIGTERM exit,
`exit=-1` telemetry, child reaped) and mutation-verified: dropping `<&3`,
moving the hook back to the foreground, and laundering exit codes to 0 are each
caught by the test written for them.

SIGKILL remains uncatchable by design, so a KILL-ed fire is still unlogged.

**Lesson beyond the specific bug:** when a verification's input TYPE differs from
production's (heredoc vs pipe, file vs stream, stub vs socket), the verification
can pass while production fails. Test with the same input shape the platform
actually delivers.


### pipe-masks incident narratives (extracted 2026-07-26, size guard)

INCIDENT 2026-06-11 convergence: `git checkout main 2>&1 | tail -2 && git rebase
origin/main` — checkout FAILED (branch held by a worktree), tail exited 0,
rebase ran on the WRONG branch and stopped mid-conflict on the live
~/.claude. Full: #pipe-masks-exit-code-for-chaining
RECURRENCE 2026-07-09 (3rd): `git merge --ff-only … | tail -1 && git log` masked
a dirty-tree merge REFUSAL — HEAD unmoved, output looked clean. Full: incidents.
ALSO un-piped: `grep -c X file` exits 1 when the count is 0, and grep/test/cmp
exit non-zero on no-match/false. Chaining `&& <dependent>` after them SKIPS
the dependent step — AND earlier side-effects in the chain that ran before
it leave partial state. Use `grep -c ... || true`, or split into separate
tool calls and check the count. INCIDENT 2026-06-14 ExampleApp: a
`grep -c 'style="'` returning 0 broke two stage/verify chains, and once
left a screenshot "after" dir ungenerated → a false "all 26 shots differ"
alarm (the cmp ran against missing files).
ALSO (INSIDE a script with `set -o pipefail`): `producer | grep -q PAT` —
grep -q exits on the FIRST match and SIGPIPEs the producer (exit 141);
pipefail then surfaces that 141 as the pipeline status, so a SUCCESSFUL
match reads as FAILURE and a guard SILENTLY INVERTS. Use `grep -c` (reads
to EOF → producer exits 0): `[ "$(producer | grep -cF PAT)" -gt 0 ]`.
INCIDENT 2026-06-16 iterm-config install.sh: an iterm2_running guard
(`ps -Axo comm | grep -qF '<bundle path>'`) reported "not running" for a
RUNNING iTerm2 and wrote prefs a live app then clobbered; caught by a unit
test of the guard before ship.

### claude -p measurement history (extracted 2026-07-26, size guard)

PERFORMANCE (both platforms): for batch ≥20 calls prefer the anthropic SDK
(`pip install anthropic`, `Anthropic().messages.create(...)`). It bypasses
Claude Code's subprocess machinery and is faster/cheaper at scale — on
macOS each `claude -p` call still costs ~10s of subprocess + session-start
overhead (measured avg 9.7s/call, 2026-06-10), so the SDK wins on speed
for large batches even though reliability is fine.
RELIABILITY: the 40-60% error rate was WINDOWS-ONLY. macOS quick repro
2026-06-10: 12/12 sequential `claude -p` calls succeeded, 0% error, 0
timeouts. NOT a hard FORBIDDEN on macOS — `claude -p` batches run
reliably here. (Caveats: n=12, trivial prompt/fast model so the
long-trace 180s-timeout dimension was not exercised; and that n=12 host
had NO MCP servers configured, so the Windows "MCP-server connection
latency" error contributor was absent.)
MCP-FLEET-WEDGE CONFIRMED (2026-07-21, macOS, full MCP fleet loaded): the
caveat's unmeasured case bit. A `claude -p` that did a REAL Read + reply
(not a trivial prompt) with the full stdio MCP fleet loaded WEDGED — pid
alive at 0.0% CPU, no output, needed a kill (matches upstream #68375: full
fleet + `-p` hangs; `--strict-mcp-config --mcp-config <minimal>` is the
restore). So on macOS `claude -p` is reliable for TRIVIAL/fast probes but
NOT for a real-tool-call run under the full fleet — for that, pass
`--strict-mcp-config` with a minimal `--mcp-config`, or don't use `-p`
(drive the task in-session / via the SDK). Verify a `-p` launch actually
PROGRESSED (output growth, not just pid-alive) before trusting it.
USE claude -p freely for: spot probes, single-task validation, Claude
Code-specific features (ToolSearch, --allowedTools, agent dispatch),
and small/medium batches. Reach for the SDK at scale for speed.
INCIDENT 2026-04-29 [WINDOWS] Exp 1/4 invalidation: 40% (Exp 4) and 60%
(Exp 1) claude -p subprocess error rates invalidated both experiments.
~$25 API spend wasted. This was the Windows host; see macOS repro above.

## 2026-06-11-bash-launcher-inlines-env-into-command-line-comm
<a id="2026-06-11-bash-launcher-inlines-env-into-command-line-comm"></a>

  # WHY: bash launcher inlines env into its command line; CommandLine dumps
  #      (Get-CimInstance/wmic/ps aux/ps -ef/pgrep -a) echo the secrets.
  #      USE pgrep -f (PIDs only) + `ps -p <pid> -o comm=` for the name;
  #      Select ProcessId, Name only.
  #      macOS CORRECTION (2026-06-11): BSD pgrep `-l` combined with `-f`
  #      prints the FULL argument list, not just the name — `pgrep -l -f`
  #      is the SAME leak as `pgrep -af` here. Prior guidance recommending
  #      it was wrong; confirmed live (launcher cmdline echoed). Never
  #      combine -l with -f on macOS.
  #      ALSO (2026-06-11): -f matches FULL argv — generic substrings
  #      ("brew", "node") false-positive on every /opt/homebrew/-pathed
  #      process (`pgrep -f brew` → 5 python/npm PIDs, zero brew).
  #      Confirm `ps -p <pid> -o comm=` BEFORE concluding it runs.
  #      macOS (2026-06-20, 3rd RECURRENCE — same CONFLUENCE_API_TOKEN as 2026-05-10): `ps -p <pid> -o args=`
  #      / `-o command=` dumps the FULL command line = the SAME leak as `ps aux` when a launcher inlines env.
  #      `-o comm=` is the ONLY safe field. NEVER `args=`/`command=`/`-o args`, NOT EVEN combined with
  #      etime=/pid= "just for the surface" — the argv carries the inlined secrets. The old "command= is OK
  #      after you confirm the PID is your target binary" caveat is the loophole that enabled this recurrence:
  #      a LAUNCHER process is never a "target binary", and you rarely actually need argv — drop it.
  # INCIDENTS 2026-05-10, 2026-05-19, 2026-06-20. Full: #wide-process-listing-secret-leaks
  # ENFORCEMENT (2026-06-21): now hook-enforced — bash-security-guard.py check_process_listing_secret_leak
  #      BLOCKS args=/command=/`ps aux`/`ps -ef`/`pgrep -a*f`/WMI CommandLine at PreToolUse (strips
  #      heredoc/quote bodies first so a script merely CONTAINING the pattern isn't blocked). The rule
  #      stays documented so the discipline survives if the hook is disabled. Surfaced by mega-distill
  #      corpus-mode: ruled-but-unenforced patterns on 3rd recurrence escalate rule→hook.

## 2026-07-23-write-file-first-then-execute-quoting-escape-bug
<a id="2026-07-23-write-file-first-then-execute-quoting-escape-bug"></a>

  # Write to file first, then execute. Quoting/escape bugs multiply inline.
  # AND prefer the WRITE TOOL over a bash heredoc (`cat <<'EOF' >f.py`) to CREATE the
  # script: the heredoc bash-write is ITSELF subject to the inline-python-guard AND the
  # auto-mode classifier — when either blocks the bash call, the file is NEVER created and
  # the next `python3 f.py` fails with a misleading FileNotFoundError (looks like a missing
  # file, is actually a blocked write). The Write tool bypasses the bash-command guards
  # entirely. Recurred 4+× in one session 2026-07-23 (report-build scripts + a classifier
  # outage that blocked a heredoc → "No such file"). Distinct from git-hygiene's "BLOCKED
  # compound ran NOTHING, re-run earlier segments" — that's for compounds; this is: don't
  # write the script via bash in the first place when a guard/classifier is in play.

## 2026-06-20-foreground-sleep-120-poll-loop-watch-background
<a id="2026-06-20-foreground-sleep-120-poll-loop-watch-background"></a>

  # WHY: a foreground `sleep 120`/poll loop to watch a background run hits the Bash tool's
  #      120s default timeout, which SIGTERMs the SLEEP (exit 143) — NOT the background run
  #      (it keeps going untouched). The timeout reads as a scary error but is harmless to the
  #      run; still, it wastes a turn and tells you nothing. Hit 4+ times in one session
  #      (2026-06-20) monitoring a multi-hour oracle run.
  #      USE run_in_background:true for the monitor (it polls + re-invokes you on exit/stall, no
  #      foreground turn burned), or a SINGLE short status check (<90s) per turn, never a long
  #      foreground sleep. A good bg monitor distinguishes COMPLETE / worker-DEAD / HANG (CPU-delta:
  #      a wedged worker is alive at ~0 CPU — a process-liveness check alone reads it healthy).

## 2026-06-22-nohup-cmd-runs-id-launch-log-2-1-shell-opens-red
<a id="2026-06-22-nohup-cmd-runs-id-launch-log-2-1-shell-opens-red"></a>

  # WHY: `nohup CMD >> runs/<id>/launch.log 2>&1 &` — the SHELL opens the `>>` redirect target
  #      BEFORE exec'ing CMD. If CMD is what mkdir's `runs/<id>/` (RUNDIR.mkdir inside main()), the
  #      dir does not exist yet → the redirect fails → the WHOLE command aborts before CMD ever runs.
  #      The `&` still returns exit 0 and prints a pid, so under run_in_background the failure is
  #      MASKED — you see "launched pid N" but nothing is running and both logs are empty.
  #      USE: `mkdir -p runs/<id>/` in the SAME shell BEFORE the nohup line. Never rely on the
  #      launched process to create its own redirect-target dir.
  #      VERIFY launch: after nohup, `pgrep -f <script>` (PID) + read the durable log — a detached
  #      launcher's exit 0 is NOT evidence the process started. (2026-06-22 F4 launch silently
  #      no-op'd: `(eval): no such file or directory: runs/f4-full-2026-06-22/launch.log`.)

## 2026-03-16-tail-n-no-f-grep-head-buffer-all-output-flush-on
<a id="2026-03-16-tail-n-no-f-grep-head-buffer-all-output-flush-on"></a>

  # WHY: `| tail -N` (no -f) / `| grep` / `| head` buffer ALL output, flush only at exit.
  #      USE `cmd > /tmp/run.log 2>&1`, no filter pipe; monitor with tail -f.
  #      ALSO nothing after the script: the notification reports the LAST command's
  #      status (redirecting fixes the LOG, not it).
  # INCIDENTS 2026-03-16, 2026-05-02, 2026-07-30(2x). Full: #piping-long-running-script-to-tail

## 2026-06-27-bsd-sed-s-pat-repl-breaks-repl-contains-delimite
<a id="2026-06-27-bsd-sed-s-pat-repl-breaks-repl-contains-delimite"></a>

  # WHY: BSD sed `s|PAT|REPL|` breaks when REPL contains the delimiter char, `&` (which
  #      means "the matched text", not a literal &), or an unescaped `\`. A wiki-link
  #      replacement `[[slug|Title]]` carries a `|` that collides with an `s|...|...|`
  #      delimiter → `bad flag in substitute command: '<char>'`; a title with `&` silently
  #      inserts the match instead of an ampersand. There is no "safe delimiter" when the
  #      REPLACEMENT (not just the pattern) holds arbitrary content. USE the Edit tool or
  #      Python `str.replace()` for content edits with special chars — NOT `sed -i ''`.
  #      (GNU sed is more lenient → Linux passes, macOS fails — same portability landmine
  #      as the awk entry above.)
  # INCIDENT 2026-06-27 garden bare-link fix: 5 `sed -i '' 's|[[x]]|[[x|Title]]|g'`
  #      conversions failed on the `|` inside the replacement; pivoted to Python str.replace.

## 2026-06-21-python3-tmp-claude-inspect-py-puts-tmp-claude-sy
<a id="2026-06-21-python3-tmp-claude-inspect-py-puts-tmp-claude-sy"></a>

  # WHY: `python3 /tmp/claude/inspect.py` puts /tmp/claude on sys.path[0], so a scratch
  #      file named after a stdlib module (inspect.py / types.py / json.py / tokenize.py /
  #      code.py / queue.py / ...) SHADOWS the stdlib — and a STRAY one left by a PRIOR
  #      session breaks the NEXT unrelated script that imports it transitively (e.g.
  #      `dataclasses` imports `inspect`). Silent + misleading: an ImportError/AttributeError
  #      that points INSIDE the stdlib, nowhere near your code.
  #      USE a unique non-stdlib name (probe_<topic>.py, verify_<thing>.py); moving the
  #      script's CWD does NOT help (sys.path[0] is the script's OWN dir, not cwd) — rename
  #      it, delete the stray, or run with `python3 -P` (3.11+, drops sys.path[0]).
  # INCIDENT 2026-06-21 sec-automations render-verify: a leftover /tmp/claude/inspect.py
  #      shadowed stdlib `inspect`, broke a verify script's `dataclasses` import — ~2 dead-end
  #      turns chasing a phantom stdlib error before spotting the stray scratch file.

## 2026-07-05-6th-recurrence-each-new-hand-rolled-urllib-graph
<a id="2026-07-05-6th-recurrence-each-new-hand-rolled-urllib-graph"></a>

  # 6th+ recurrence, each a NEW hand-rolled urllib Graph script. Python 3.14's
  # http.client rejects the raw SPACE in `$filter=<k> eq '<v>'` with a generic
  # "URL can't contain control characters" (never mentions OData). STOP writing
  # raw urllib Graph probes: `from msgraph_helper import graph_get, odata_quote`
  # (bin/ is importable; GCC High app-only auth via Keychain, no az login).
  # WHY: `fcntl` (also `termios`, `grp`, `pwd`, `posix`) is Unix-only. A top-level
  #      `import fcntl` compiles fine everywhere (py_compile does not execute imports)
  #      and runs fine on the macOS host — but the moment a pytest test IMPORTS the
  #      module, the Windows CI matrix (tests.yml) ImportErrors at COLLECTION and the
  #      whole `validate` job goes red. The bug hides until a test first imports the
  #      module, which can be long after the import shipped.
  #      USE the guarded form when a module may be imported on Windows CI:
  #        try:\n    import fcntl\n except ImportError:\n    fcntl = None
  #      then gate every use (`if fcntl: fcntl.flock(...)`). For REAL cross-platform
  #      locking (not a macOS-host-only tool) use the msvcrt fallback — canonical
  #      pattern in skills/supergoal/scripts/state_io.py. `os.replace` is atomic on
  #      Windows too, so a temp-write+rename stays correct without the lock.
  # COVERAGE GAP: audit-skill's C1 lint flags unguarded fcntl imports but scans
  #      skills/ ONLY — bin/ and hooks/ scripts are NOT covered, so a hand-written
  #      bin/ module gets no authoring-time guardrail; this rule is the ambient backstop.
  # INCIDENT 2026-07-05 guardrail toolchain: bin/guardrail_corpus.py + the capture hook
  #      added `import fcntl` for a rescan lock; the new bin/test_guardrail.py imported
  #      them and the windows-2022 matrix leg failed collection (macOS + ubuntu passed).
  #      One fix-forward commit (guard the import) on the still-open PR.

## 2026-06-10-macos-does-reproduce-tested-tailscale-up-ipv4-on
<a id="2026-06-10-macos-does-reproduce-tested-tailscale-up-ipv4-on"></a>

  # macOS does NOT reproduce (tested 2026-06-10, Tailscale UP: IPv4-only
  # getaddrinfo, boto3 STS OK in 2.4s) — macOS Tailscale uses the utun
  # network extension, not the Windows split-DNS-with-AAAA path; the
  # protection tiers were intentionally not ported. Windows tier list
  # (usercustomize, HAS_IPV6, getaddrinfo patch, ipv4-site) + macOS test
  # detail: incidents#ipv6-windows-tiers. (Extracted 2026-06-11, size guard.)

## 2026-06-15-env-var-creds-aws-access-key-id-secret-session-t
<a id="2026-06-15-env-var-creds-aws-access-key-id-secret-session-t"></a>

  # WHY: env-var creds (AWS_ACCESS_KEY_ID/SECRET/SESSION_TOKEN from a sts assume-role)
  #      carry NO region, and many SSO profiles set none — so the CLI/SDK resolves the
  #      DEFAULT (commercial) endpoint. A GovCloud or global-service (route53) call then
  #      fails OPAQUELY: empty "ERROR" / EndpointConnectionError, NOT a clear AccessDenied.
  #      Same class bit lab-deploy/amplify_setup.py (region-less STS Session → Amplify
  #      EndpointConnectionError) and the 2026-06-15 GovCloud route53 sweep (all 17 member
  #      accounts errored empty until --region us-gov-west-1 was added; --profile worked
  #      because the profile carried the region, env creds did not).

## 2026-07-05-alternative-migrate-task-def-fargate-arm64-cheap
<a id="2026-07-05-alternative-migrate-task-def-fargate-arm64-cheap"></a>

  # Alternative: migrate the task def to Fargate ARM64 (cheaper) — but that is
  # an mcp-infra change, coordinate it; never "fix" by switching architectures ad hoc.
  # BUILDX-PLUGIN-ABSENT fallback (2026-07-05, colima on this host): the REQUIRED
  #   `docker buildx build --platform ...` above assumes the buildx PLUGIN is installed —
  #   on colima it may NOT be. Symptom chain: `docker buildx build --platform linux/amd64`
  #   → "unknown flag: --platform" (docker doesn't recognize `buildx` as a subcommand);
  #   then `DOCKER_BUILDKIT=1 docker build --platform linux/amd64` → "BuildKit is enabled
  #   but the buildx component is missing or broken". WORKING fallback:
  #     DOCKER_BUILDKIT=0 docker build --platform linux/amd64 -t <img> .
  #   The LEGACY (pre-BuildKit) builder honors `--platform` and cross-builds amd64 via
  #   QEMU/binfmt on the arm64 colima VM. It prints a "requested image's platform
  #   (linux/amd64) does not match the detected host platform" WARNING — EXPECTED, not an
  #   error. VERIFY before pushing: `docker image inspect <img> --format '{{.Architecture}}'`
  #   MUST print `amd64` (a silently-arm64 image dies at Fargate deploy with the "exec
  #   format error" this whole block guards). Install buildx (`brew install docker-buildx`
  #   + wire `~/.docker/cli-plugins`) to use the REQUIRED path; until then this is correct.

## 2026-06-19-cross-arch-note-docker-run-platform-linux-amd64
<a id="2026-06-19-cross-arch-note-docker-run-platform-linux-amd64"></a>

  # Cross-arch note: `docker run --platform linux/amd64` DOES yield a genuine
  #   x86_64 container on an arm64 colima VM via QEMU/binfmt (verified: container
  #   arch x86_64) — so an arm64 colima is fine for recompiling a linux/amd64
  #   hashed lock; the mount boundary, not the arch, is the gotcha.
  # `colima start --arch x86_64` is a NO-OP when a VM is already running (attaches
  #   to the existing arm64 VM); use the --platform emulation above instead of
  #   assuming the flag switched the VM.
  # INCIDENT 2026-06-19 Proteus dep-lock rebuild: ~4 dead-end docker runs (empty
  #   /work, "No such file or directory") before diagnosing the /tmp/claude mount
  #   gap; pivoted to ~/worktrees + ~/<scratch>. Pairs with
  #   ON hash_pinned_lock_built_on_one_platform_used_on_another (the reason the
  #   amd64 container build exists at all).

## 2019-06-01-documents-knowledge-base-topics-azure-gov-cloud
<a id="2019-06-01-documents-knowledge-base-topics-azure-gov-cloud"></a>

# ~/Documents/knowledge-base/topics/azure-gov-cloud-automation-platform.md — GCC High SDK
#   config, AzureCliCredential timeout, Automation wheels, runbook, 2019-06-01 bypass
# ~/Documents/knowledge-base/topics/wsl2-ubuntu-platform.md — wsl.exe paths, PATH,
#   CARGO_TARGET_DIR ext4, terraform rsync to ext4, wslInheritsWindowsSettings

## 2026-06-10-macos-no-hard-refusal-claude-p-batches-run-relia
<a id="2026-06-10-macos-no-hard-refusal-claude-p-batches-run-relia"></a>

  # [macOS] No hard refusal — claude -p batches run reliably here (0% error at
  #   n=12, 2026-06-10). For LARGE batches prefer the anthropic SDK on SPEED
  #   grounds (~10s/call subprocess overhead on macOS), not reliability.
  # [WINDOWS] REFUSE for batch ≥20 calls: subprocess error rates compounded to
  #   40-60%. Use the anthropic SDK directly there. If a Windows experiment
  #   specifically requires Claude Code features (ToolSearch, --allowedTools,
  #   agent dispatch), accept ~10-20% error floor and add retry logic.


<!-- extracted 2026-08-01: ambient-context reduction -->

## cmd-tail-grep-head-exits-with-the-filter-s

```
WHY: `cmd | tail/grep/head` exits with the FILTER's status (pipefail is unset in
     the Bash tool shell) — `&&` proceeds even when cmd FAILED. Never pipe a
     command whose success gates the next step; run it bare, or split into
     separate tool calls and check the result before the dependent operation.
Three shapes, all recurred: (1) a piped gating command (`cmd | tail && next`)
     ran the dependent step after the command FAILED; (2) `grep -c` returning 0
     exits 1, so `&& <dependent>` SKIPS it while earlier side-effects leave partial
     state — use `grep -c ... || true`; (3) inside `set -o pipefail`,
     `producer | grep -q PAT` SIGPIPEs the producer (141) so a SUCCESSFUL match
     reads as FAILURE and a guard silently INVERTS — use `grep -cF` (reads to EOF).
     Full: incidents#pipe-masks-exit-code-for-chaining
```

## the-bash-tool-shadows-grep-with-a-function-exec

```
WHY: the Bash tool shadows `grep` with a function exec'ing the claude binary as
     embedded ugrep 7.5 (-G, --ignore-files --hidden --exclude-dir=.git).
     (1) empty alternation `(a|b|)` HARD-ERRORS (BSD/GNU accept) — use `(a|b)?`;
     silenced stderr turns that into phantom 0-hits (2026-07-09); (2) gitignored
     files are SKIPPED in sweeps (raw scan: `command grep`); (3) never
     `2>/dev/null` a discovery grep. Full: incidents#bash-tool-grep-is-ugrep
```

## var-is-a-zsh-syntax-error-eval-n-bad

```
WHY: `${!var}` is a zsh SYNTAX ERROR — `(eval):N: bad substitution`. zsh uses the
     `(P)` parameter flag: `${(P)var}`. It bites env-presence probe LOOPS that iterate
     a var-NAME list (`for v in A B C; do ... ${!v} ...`) — which is precisely the
     shape of a "which of these credentials is set?" check. The whole command aborts,
     so it reads as a broken probe rather than a dialect problem.
     Also reserved in zsh: `status` (aliases `$?` — `status=$(...)` aborts the script),
     `pipestatus`, `ERRNO`. Use `rc`/`st` as scratch names.
STATED HERE BECAUSE IT LOADS HERE. The full zsh-expansion family lives in
     `platform-rules/macos/platform-constraints.md`, which is injected PREVIEW-ONLY.
     MEASURED 2026-08-01: that SessionStart hook emitted 30,032 bytes and ~2KB reached
     context — ~93% of the macOS constraints never load. Same precedent as
     `search-efficiency.md`'s glob-metachar block, which was relocated for this reason.
RECURRENCE: documented 2026-07-15 ("an env-var presence probe died on `${!v}` first
     try; `${(P)v}` worked") and hit AGAIN 2026-08-01 in the identical shape. A
     documented constraint prevents nothing from a file that does not load — treat a
     repeat of a macos-only-documented gotcha as a DELIVERY gap, not a knowledge gap.
```

## bash-defers-a-trap-until-the-current-foreground-child

```
WHY: bash DEFERS a trap until the current foreground child returns, so a SIGTERM
  arriving mid-child is QUEUED — the wrapper hangs for the child's full duration
  and the handler never runs (measured: >8s hang + nothing logged, vs dying
  immediately with NO trap). Strictly WORSE than no trap. REQUIRED: background the
  child and `wait` on it (`wait` IS interruptible — 0.14s), then read the next
  FORBIDDEN, which backgrounding breaks. SIGKILL is uncatchable either way.
```

## bash-points-a-background-job-s-stdin-at-dev

```
WHY: bash points a BACKGROUND job's stdin at /dev/null when the parent's stdin is a
  PIPE, so `cmd &` silently starves any child reading stdin — for a hook wrapper
  that is EVERY hook (each parses its JSON payload from stdin). REQUIRED:
  `exec 3<&0` once, then `"$@" <&3 &`. TEST WITH A PIPE, NOT A HEREDOC — a heredoc
  is a SEEKABLE TEMP FILE and passes even in the broken shape (a heredoc probe
  cleared all three candidate shapes; only `subprocess.run(input=...)` caught it).
  When a verification's input TYPE differs from production's, it can pass while
  production fails. Full: incidents#background-job-stdin-from-devnull
```

## promoted-t4-t1-2026-07-31-documented-since-2026

```
WHY PROMOTED T4->T1 (2026-07-31): documented since 2026-06-12 in
agent-memory/topics/ci-cd.md WITH the exact fix, and re-derived from scratch
anyway — topic files load on worker dispatch, but `terraform init` is run
from the MAIN thread, where that file never loads. Recurred ~5 times in one
NavArch session (init -> dirty lock -> revert -> repeat), then a 6th time as
"Required plugins are not installed" mid-apply after a revert. Ambient is the
correct tier for a constraint hit from the main thread. Fixed at source in
NavArch-Apps-Infra PR #20 (1 -> 4 hashes per provider).
```

## colima-s-lima-vm-auto-mounts-only-home-and

```
WHY: colima's Lima VM auto-mounts ONLY $HOME (and /tmp/colima) into the VM —
     the macOS /tmp (/private/tmp, where the Bash tool's /tmp/claude lives) is
     NOT in the VM mount set. `docker run -v /tmp/claude/x:/work ...` therefore
     mounts an EMPTY /work inside the container: `ls /work` returns nothing,
     `bash /work/script.sh` → "No such file or directory" — even though the
     file plainly exists on the host. Silent: docker exits 0, the mount just
     has no contents.
```

## the-harness-writes-the-currently-executing-bash-call-s

```
WHY: the harness writes the CURRENTLY-EXECUTING Bash call's own stdout into the
     SAME `tasks/` dir that holds prior background-task output. So
     `for f in .../tasks/*.output; do cat "$f"; done` (equally `cat tasks/*.output`,
     `grep . tasks/*`, `wc -c tasks/*`) READS THE FILE IT IS WRITING — a
     self-amplifying loop that grows unbounded until the harness kills the call
     ("output file exceeded 5GB", exit 137). Silent until the kill, and it DESTROYS
     whatever real output that same call had already produced.
```

## 2026-07-31-retro-a-completed-5-source-distill

```
INCIDENT 2026-07-31 /retro: a COMPLETED 5-source distill dedup sweep was destroyed
     by a `for f in tasks/*.output; do cat "$f"; done` appended to the same call —
     5GB written, exit 137, sweep re-run from scratch. What the call actually wanted
     was one detached merge run's status file, addressable by id all along.
```

## aws-glue-get-table-output-text-emits-tab-separated

```
WHY: `aws glue get-table --output text` emits TAB-separated fields, not space-separated.
     A `case " $COLS " in *"$col"*)` style match against it silently never matches, so
     the check reports every target column ABSENT — a well-formed negative, not an error.
     2026-07-31: this nearly killed a real ~7,000x scan-reduction migration ("gold lacks
     the columns, repoint impossible") over one line of shell quoting. Re-checked with
     --output json: all 11 needed columns were present.
```

## an-if-intended-to-gate-a-push-on-tests

```
WHY: an `if` intended to gate a push on "tests pass" instead checked the target PR's
     merge STATE. A commit with a genuinely failing test was pushed; auto-merge only
     held because the CI check happened to be red — luck, not the gate design.
```

## shared-tmp-claude-scratch-name-collision

### 2026-08-04 /retro — Write refused a file that belonged to another session

Writing a small marker-inspection script to `/tmp/claude/marker.py`, the Write
tool refused: *"File has not been read yet. Read it first before writing to it."*
Reading it showed a **different session's** distill script — 7 lessons about
PR-review approval gates, a GovCloud GHES-only OIDC finding, SCP readability from
a member account, and single-platform ECR pushes, with its own metrics block
(38 turns, 305 tool calls). None of it was mine.

**Why the collision is structural, not bad luck.** `/tmp/claude/` is shared by
every concurrent Claude Code session on the host and is not purged between them.
Measured the same session:

- **1,451** `*.py` files present, oldest 4 days old.
- Six generically-named artifacts colliding by construction:
  `marker.py`, `entry1.md`, `entry2.md`, `check.py`(class), `probe.txt`,
  `verify.txt`, `budget.txt`.
- Two of those (`entry1.md`, `entry2.md`) were written by THIS session minutes
  earlier, with exactly the same collision-prone shape — so the hazard was being
  actively re-created while being diagnosed.

**The Write tool is the only thing that catches it.** Its refusal is not really
about stale content here; it forced a Read that revealed the file was someone
else's. A bash heredoc or `>` redirect has no equivalent guard and would have
destroyed the other session's work silently — no error, no diff, no recovery
(the file is untracked, outside any repo, so nothing would ever report it lost).

**The fix already existed one surface over.** `skills/capture/SKILL.md` carries
this exact rule for WORKTREE paths, added after a 2026-07-28 collision:

> **Include the session-id prefix in the name.** A date-only name collides with
> any concurrent session doing the same thing... The date alone is not unique;
> sessions are.

It was never extended to scratch FILES in the same shared directory. Same
mechanism, same remedy, different surface — the third instance this session of a
fix that exists for one surface and never propagated to its sibling (the others
being `bash-tail-buffering-guard`'s v3 anchoring not reaching its v8 matcher, and
the merge-verification guidance present in three channels but absent from the
ambient one).

**Rule:** name scratch files `<topic>-<session-id-prefix>.<ext>`. Prefer the Write
tool over a bash redirect for scratch, and when it demands a Read, actually read
the file before concluding it is yours.

## Detector-authoring seed index

These machine-readable identifiers were moved out of the ambient
`rules/platform-constraints.md` during the 2026-08-06 context-budget reduction.
They remain here so `audit-rules` can seed focused detectors without spending
ambient context on the full incident catalog.

FORBIDDEN: secret_env_var_expansion_in_diagnostics
FORBIDDEN: curl_verbose_with_auth_or_secret_header
FORBIDDEN: wide_process_listing_with_commandline_when_bash_launcher_inlines_secrets
FORBIDDEN: inline_complex_python_powershell_bash
FORBIDDEN: foreground_sleep_or_poll_loop_longer_than_the_bash_timeout
FORBIDDEN: nohup_redirect_to_a_dir_the_launched_process_creates_itself
FORBIDDEN: pip_install_upgrade_all_outdated
FORBIDDEN: subprocess_run_text_true_for_external_apis
FORBIDDEN: write_text_for_files_originated_with_lf_endings
FORBIDDEN: sqlite_on_nfs_or_efs
FORBIDDEN: piping_long_running_background_script_to_filtering_tail
FORBIDDEN: inner_ampersand_inside_run_in_background_bash_invocation
FORBIDDEN: subprocess_args_over_32k_chars_on_windows
FORBIDDEN: str_format_on_prompt_templates_containing_json_or_braces
FORBIDDEN: awk_dash_v_with_multiline_value_on_macos
FORBIDDEN: glob_and_cat_the_background_task_output_directory
FORBIDDEN: space_delimited_shell_match_against_aws_output_text
FORBIDDEN: gating_a_push_on_an_unrelated_resources_state_instead_of_the_test_exit_code
