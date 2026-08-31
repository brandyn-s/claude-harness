# Staged spec: Bash guards are blind to script FILES — scan written script content

**Target:** a new `PreToolUse:Write|Edit` check, OR an added check inside
`hooks/bash-security-guard.py` that resolves an executed script path and scans its
bytes. Prefer the Write-time variant (see "Why Write-time" below).
**Tier:** T0-hook (a control that exists and is bypassable by following documented guidance).
**Staged:** 2026-08-12. Install via `/ship-hook`.

## The measured incident

`bash-security-guard.py` already contains `check_env_var_diagnostic()`:

> `"""Block the ${VAR:+set}${VAR:-NOT SET} secret-leaking diagnostic pattern."""`
> `... leaks the variable's VALUE to stdout when it is set (the :+ branch emits a`
> `marker AND the :- branch emits the value). USE the safe form:`
> `[ -n "$VAR" ] && echo SET`

On 2026-08-12 that exact shape leaked **two live API keys** (`XAI_API_KEY` and a
USPTO ODP key) into a session transcript:

```zsh
echo "xai key: ${XK:+present (${#XK})}${XK:-ABSENT}"
```

**The guard did not fire, and it is not a regex gap.** The pattern was written to
`/tmp/claude/verify_probes.sh` with the Write tool and executed as
`zsh /tmp/claude/verify_probes.sh`. `PreToolUse:Bash` inspects the COMMAND STRING;
it saw a path, not the body. Every command-string check in
`bash-security-guard.py` (credential reads, exfiltration, dangerous commands,
inline-python) has the same blind spot.

## Why this is worse than an ordinary coverage gap

Two pieces of standing guidance push work INTO the blind spot:

1. `bash-security-guard.py`'s own `SEC_REMEDY` — emitted on every block —
   says *"Cheapest fix: write the code to a .py FILE and run it, and split any
   credential read away from any network call."*
2. The project CLAUDE.md says *"For anything beyond a simple command, write it to
   a file and execute it rather than running a complex inline string."*

Both are good advice for correctness (they prevent quoting bugs). Both silently
disable the security guard. An agent that follows instructions ends up
**less** guarded than one that does not — so the failure rate rises with
compliance, which is the inverse of what a control should do.

`inline-python-guard` shows the same asymmetry from the other side: it blocks
`python3 -c` over 300 chars and tells you to use a file, at which point nothing
inspects the file.

## Required behaviour

On `Write` / `Edit` whose `file_path` ends in `.sh`, `.zsh`, `.bash`, `.py`, or
whose content begins with a shell/python shebang, scan the CONTENT with the
existing command-string checks and block on a match.

Reuse, do not reimplement:

- import `ENV_VAR_DIAGNOSTIC` / `check_env_var_diagnostic` and the credential-read
  and exfiltration predicates from `bash-security-guard.py`
- a COPY of those regexes is two-source drift; the guard and this check must fail
  together or not at all

Message must name the file, the matched shape, and the safe form — the same text
the Bash-path block emits, so the two paths are indistinguishable to the reader.

## Why Write-time rather than resolve-on-execute

Resolving the script at execution time is strictly worse:
- the file may be assembled by several Edits, so only the last one is inspectable
- a heredoc-generated script has no Write event at all
- **the leak has already been authored** by then; Write-time is the earliest point
  where refusing costs nothing

Execution-time resolution is a reasonable SECOND layer, not the first.

## Measurement gate before install

Per `verify-effectiveness`, measure before wiring:

1. Replay the historical Write/Edit corpus for `.sh`/`.py` bodies matching
   `ENV_VAR_DIAGNOSTIC`. Report the fire rate against the >10%-is-too-broad gate.
2. Known-positive: this session's `verify_probes.sh` body MUST block.
3. Known-negative: a `.py` that merely mentions `os.environ.get("X", "default")`
   in a comment or docstring MUST NOT block (strip comments first — see
   `tdd-mutation-testing` items 19/32 for the self-matching failure this repo has
   hit twice).
4. Mutation-verify: un-wire the check and confirm the known-positive passes.

## Falsifier

If the historical replay shows this pattern was never written to a file before
2026-08-12, this is an n=1 incident and an advisory `systemMessage` is the correct
strength, not a block. Record the measured count either way — do not install a
blocking check on an unmeasured predicate.
