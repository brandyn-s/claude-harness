# Project Instructions — macOS template

<!--
SETUP (one time, on the MacBook):
1. Start a Claude Code session from your home directory so the project dir
   exists, then find its encoded name:
     ls ~/.claude/projects/   # e.g. Users-you
   (encoding rules: skills/_shared/project-dir.md)
2. Copy this file to ~/.claude/projects/<encoded-name>/CLAUDE.md
3. Replace the "Platform & Shell Execution" section below if anything differs
   on your machine, then copy the platform-NEUTRAL sections from the Windows
   project file (projects/C--Users-you/CLAUDE.md) — everything from
   "Knowledge Base Recall" onward applies unchanged on macOS. Keeping those
   sections in one place (the Windows file) until the Windows laptop is
   retired avoids divergence; if you fork them, note it in both files.
4. Commit the new projects/<encoded-name>/CLAUDE.md — session data in that
   dir is gitignored, the CLAUDE.md is tracked config.
-->

## Platform & Shell Execution
- macOS (Apple Silicon MacBook Pro). Default interactive shell is zsh; the
  Bash tool runs bash. Stock `/bin/bash` is 3.2 — write inline bash to that
  baseline (no `mapfile`, no associative arrays, no `${var,,}`) unless
  Homebrew bash 5.x is confirmed with `bash --version`.
- `python3` must resolve to Homebrew Python (`/opt/homebrew/bin/python3`),
  not the Xcode CLT stub at `/usr/bin/python3`. Verify with
  `command -v python3` before registering MCP servers or installing packages.
  Install packages with `python3 -m pip install <pkg>`.
- Never run complex commands inline — always write to a file and execute it:
  - **Python**: Write tool creates a `.py` file, then `python3 script.py`.
    Never `python3 -c "..."` beyond a one-liner.
  - **Complex bash**: nested quotes, variable expansion, or multi-line logic
    goes in a `.sh` file first.
- BSD userland, not GNU: `sed -i ''` (not `sed -i`), no `grep -P` (use `-E`
  or `rg`), no `date -d` (use `date -j -f`), `stat -f%z` (not `stat -c%s`).
  Prefer `rg`/Python over stretching BSD tool flags.
- UTF-8 is the default everywhere — the Windows cp1252 rules
  (`encoding='utf-8'` in every `open()`, `sys.stdout.reconfigure`) are not
  needed on macOS, but keeping `encoding='utf-8'` explicit costs nothing and
  keeps scripts portable back to the Windows laptop.
- Paths are `/Users/<name>/...` — forward slashes native, no drive letters,
  no MSYS translation issues. Quote paths containing spaces.
- TCC privacy: `~/Documents`, `~/Desktop`, `~/Downloads` need a per-app
  grant for the terminal; denials surface as silent EACCES in hooks. Keep
  working repos outside those dirs where possible (see
  `rules/platform-constraints.md` ON macos_file_access_*).
- Downloaded non-brew binaries are Gatekeeper-quarantined: install via brew
  or `xattr -d com.apple.quarantine <file>`.
- Long-running background jobs (indexing, gathers): wrap with `caffeinate -i`
  so the laptop doesn't sleep mid-run.

<!-- Sections from here on: copy from projects/C--Users-you/CLAUDE.md
     (Knowledge Base Recall, Security Tool Guardrails, Output Generation,
     Large File Handling, Search Reliability, Delegation Rules, External API
     Integration, Adaptive Execution, Git & CI Discipline, General). -->
