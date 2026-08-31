# macOS session-start digest

This is the compact, load-bearing macOS contract injected at SessionStart. The
full incident catalog remains at
`~/.claude/platform-rules/macos/platform-constraints.md`; read it explicitly
when a symptom below occurs. Do not expand this digest past the 10,000-character
hook-output ceiling.

## Shell and command construction

- Claude Code's Bash tool runs zsh. Unquoted variables do not word-split; use
  arrays, explicit arguments, `${=value}` only when intentional, or a
  delimiter-based `while IFS= read` loop.
- Unquoted `*`, `?`, and `[` do glob-expand, and a no-match aborts the command.
  Quote URL query strings and patterns such as `'*.py'` and `'*.tf'`.
- Brace a variable before a colon: `${ref}:path`, never `$ref:path`. zsh treats
  `:a`, `:c`, `:e`, and similar sequences as history modifiers and can silently
  corrupt Git object paths and image tags.
- Do not assign to zsh read-only names such as `status`, `pipestatus`, or
  `ERRNO`; use `rc` or `st`. Bash `${!name}` indirection is invalid in zsh;
  use `${(P)name}` when unavoidable.
- Quote words beginning with `=`. In zsh, an unquoted `=word` requests command
  path expansion and can abort a whole compound command.
- `/bin/bash` is 3.2. Avoid `mapfile`, associative arrays, `${value,,}`, and
  other Bash 4+ syntax unless a newer Homebrew Bash was explicitly selected.
- macOS ships BSD tools: use `sed -i ''`, `grep -E`/`rg`, `date -j -f`, and
  `stat -f%z`; do not assume GNU flags.
- In paste-ready blocks for the user's interactive zsh, include runnable lines
  only. Do not put `#` instruction lines or unresolved `<placeholders>` inside
  the block; interactive comments may be disabled.

## Sandbox and subprocess boundaries

- A sandboxed script, loop, or tool can fail to resolve a child binary even
  when the same binary works at top level. Never suppress the probe's stderr
  and interpret empty output as absence. Use an absolute binary path or an
  explicitly authorized unsandboxed run when the nested child is required.
- Homebrew installs and casks need an unsandboxed run; sandbox failures can
  masquerade as unsupported-platform or missing-bottle errors.
- Go builds/module downloads need network plus writable GOPATH/GOMODCACHE/
  GOCACHE. Run unsandboxed or place all three in a verified writable temp or
  repository path.
- Nested/scripted `gh` POST operations can fail TLS verification under the
  sandbox even when REST GETs work. Prefer a top-level `gh` invocation or an
  explicitly authorized unsandboxed call. A successful list/GET is not proof
  that clone, GraphQL, issue creation, or PR creation will work.
- Before checkout/merge/rebase in the Claude configuration repository, protect
  dirty work and use the appropriate unsandboxed Git path. A sandbox denial can
  partially move HEAD or reset writable files before failing; verify against a
  pre-operation snapshot, not merely against HEAD.
- When a Python script launches pytest, ruff, mypy, or another Python tool, use
  `sys.executable` and a `cwd` argument. A login shell can resolve a different
  Python and turn an import failure into a misleading zero-test result.

## Secrets, filesystem access, and long work

- Store hook/MCP secrets in macOS Keychain, never plaintext shell startup
  files. Seed secrets from the user's own terminal with an interactive hidden
  prompt. Verify only presence or length; never print a value.
- A blank Keychain read for a known item can be an unanswered ACL dialog.
  Ask the user to approve it and retry before concluding the item is absent.
- Documents, Desktop, and Downloads are governed by macOS TCC. A child process
  can receive a silent access denial even when the parent can read the path.
  Treat this as an authorization boundary and do not route around it.
- Use `caffeinate -i <command>` for authorized long-running local work that
  must survive laptop idle sleep. Keep ordinary hook and polling work bounded.
- The default open-file limit can be too low for large indexes or MCP fleets;
  inspect and deliberately raise it for the launching process before blaming
  the indexed tool.

When a failure matches one of these classes, read the full macOS catalog before
choosing a workaround. The digest is a trigger surface, not the incident log.
