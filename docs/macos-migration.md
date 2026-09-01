# Fresh macOS laptop setup

The repository is installation source, not the live `~/.claude` directory.
Keeping those paths separate prevents caches, transcripts, credentials, and
other runtime state from becoming accidental repository content.

## 1. Install the host toolchain

Install Homebrew, clone this repository, then install its declared packages:

```bash
git clone https://github.com/brandyn-s/claude-harness
cd claude-harness
brew bundle
python3 --version
git --version
claude --version
```

Python 3.10 or later is required. macOS provides the Seatbelt sandbox Claude
Code uses, so Linux-only `bubblewrap` and `socat` are not needed.

## 2. Install the fresh-laptop core

```bash
bash install.sh
python3 bin/fresh_laptop_doctor.py
```

Accept the fresh-laptop profile, the Brandyn operator overlay, and the
recommended core, then stop. This gives you the portable sandbox kernel plus
the compact operator rule, delivery policy, high-consequence review boundary,
non-progress detector, and prompt/output secret controls. The installer creates
backups before replacing collisions and the doctor reports the operator layer
as a separate readback.

Run `/sandbox` in the first Claude Code session to inspect the effective
boundary. A command that cannot run in the sandbox returns to normal permission
review; it is not blanket-approved.

## 3. Add integrations one at a time

MCP registrations live outside this repository. Add only servers you use and
verify each before adding the next:

```bash
claude mcp list
```

Keep secrets in the macOS Keychain or the integration's supported credential
store, never in tracked settings. Project `.mcp.json` files remain untrusted
until explicitly enabled.

## 4. Opt into more author-workstation components only when earned

Re-run `install.sh` when a concrete workflow needs a rule, hook, skill, agent,
or platform integration from the full mirror. A component joins the daily core
only when it protects a measured failure that native permissions, sandboxing,
or an on-demand skill cannot cover, and it has bounded cost plus a direct test.

The full author settings are host-materialized reference state. Do not copy
`settings.json` wholesale onto the new laptop and do not run the repository as
`~/.claude`.

## 5. Machine-specific considerations

- TCC can restrict `~/Documents`; grant the terminal appropriate access or keep
  working repositories elsewhere.
- Do not put active Git repositories in iCloud Desktop/Documents sync.
- The portable status line works without `claude-hud`; add that integration only
  if you want it.
- PDF image fallback needs Poppler (`brew install poppler`).
- Windows-specific hooks and incident records are historical source, not part of
  the fresh macOS core.

The completion gate is one successful doctor run followed by a normal session
where a sandbox-contained edit/test loop works. A green doctor does not claim
that optional MCP servers or private integrations are configured.
