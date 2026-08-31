# macOS Migration Guide (Windows laptop → MacBook Pro)

This repo is the live `~/.claude` directory, and the hook layer is fully
cross-platform (every Windows-specific code path is guarded behind
`sys.platform == "win32"` with working POSIX fallbacks — verified by the
2026-06-10 migration audit and continuously by the `macos-14` CI runner).
The hook code is cross-platform, but `settings.json` is deliberately
**host-materialized runtime state**. Migration therefore includes one explicit
path-reconciliation step in addition to recreating untracked per-machine state.

## One-time setup on the Mac

1. **Homebrew + toolchain**
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
   Then from the repo root: `brew bundle` (see [Brewfile](../Brewfile)).
   Verify `command -v python3` → `/opt/homebrew/bin/python3`, not
   `/usr/bin/python3` (Xcode CLT stub).

2. **Clone the repo as `~/.claude`**
   ```bash
   git clone git@github.com:brandyn-s/claude-harness.git ~/.claude
   ```
   Line endings and exec bits are enforced by `.gitattributes` / the index;
   `hooks/run-hook` and `bin/statusline-launcher` are runnable on checkout.

   Before the first Claude launch, materialize all registered commands for this
   Mac and refuse any missing hook file:

   ```bash
   python3 ~/.claude/scripts/wire_hooks.py --reconcile-existing ~/.claude/settings.json
   ```

3. **Recreate gitignored per-machine state**
   - `~/.claude/.credentials.json`
   - `~/.claude/settings.local.json` (if used)
   - API keys consumed by `hooks/session_start_modules/env_loader.py` — seed
     them into the Keychain with `bin/keychain-seed NAME [NAME ...]`
     (preferred; see `rules/platform-constraints.md` ON macos_secret_storage).
     Non-secret config exports go in `~/.zshenv` (NOT `~/.zshrc`; see
     ON macos_env_vars_for_hooks_and_mcps).

4. **Re-register local MCP servers** (`~/.claude.json` lives outside this
   repo). The Windows registrations point at `Python314/pythonw.exe`; on the
   Mac, register each local server against Homebrew `python3` or `uv`. This
   is the single biggest migration item — do them one at a time and verify
   each connects before the next (`claude mcp list`).

5. **Statusline** — `settings.json` dispatches through
   `bin/statusline-launcher`: it uses claude-hud when
   `~/Documents/GitHub/claude-hud/dist/index.js` exists (clone + `npm install
   && npm run build` it natively on arm64), else falls back to the portable
   `statusline.py`. Set `CLAUDE_HUD=<path>` if claude-hud lives elsewhere.

6. **Project memory** — Claude Code keys project dirs by CWD path, so the
   Windows namespace (`projects/C--Users-you/`) is not read on the
   Mac. Create the macOS counterpart from
   [templates/macos-project-CLAUDE.md](../templates/macos-project-CLAUDE.md)
   (instructions inside) and commit it. Both namespaces coexist in git
   without colliding.

7. **TCC / iCloud** — either grant the terminal app Full Disk Access
   (System Settings → Privacy & Security), or keep working repos and the
   knowledge-base outside `~/Documents`. Do NOT enable iCloud "Desktop &
   Documents Folders" sync on dirs containing git repos.

8. **Smoke test** — run `python3 bin/claude-release-qualification.py --config-root
   ~/.claude`, then start a fresh Claude Code session. Verify `/status`,
   `/hooks`, SessionStart, SessionEnd, and one harmless allow/block hook probe.
   Investigate any warning before normal work.

9. **Optional: scheduled maintenance** — LaunchAgent templates for nightly
   `/garden`, weekly `/gather-intel`, and the weekly hook fire-rate report
   live in [templates/launchd/](../templates/launchd/README.md) (install,
   operate, and caveats documented there).

## What deliberately did NOT change

- The Windows incident archive (`rules/incidents/`, the old project
  CLAUDE.md, `sessions-index.json`) stays as-is — it is history, and binds
  again the moment a session runs on the Windows laptop.
- Windows-scoped hook code (pwsh zombie detection, MSYS path auto-fixes,
  taskkill guards) stays — same repo serves both laptops; the guards select
  the right branch at runtime.

## Known macOS deltas to keep in mind

All encoded in `rules/platform-constraints.md` (DOMAIN: macOS): stock bash
3.2, BSD userland flags, Gatekeeper quarantine on non-brew binaries,
`ulimit -n 256` default, Homebrew-vs-CLT `python3` resolution, TCC silent
EACCES. The Windows-only rules (cp1252, 32K argv, MSYS path mangling) do
not bind on macOS — don't apply them there.

## Untested-on-Mac list (verify before relying on)

- The IPv6/Tailscale mitigation stack (`usercustomize.py`, ipv4-site
  PYTHONPATH) was built for Windows split-DNS hangs. **Test boto3/AWS plainly
  first**; only port the workaround if the hang reproduces
  (diagnose-before-fix).
- `pdf-to-text` image fallback wants `pdftoppm` (`brew install poppler`).
- Hook latency telemetry (`run-hook` ms field) needs bash ≥ 5
  (`brew install bash`); on stock bash 3.2 it logs `null` — harmless.
