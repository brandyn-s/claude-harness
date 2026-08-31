# PR8 — Native Seatbelt Sandbox Evaluation (macOS)

**Date:** 2026-06-10 · **Host:** macOS (Apple Silicon), Claude Code 2.1.170
**Decision owner:** user (this is a settings/architecture change — not shipped unilaterally)

## TL;DR recommendation

**Enable the sandbox with a tuned profile.** ~~and flip `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` from `0`→`1`~~ — **RETRACTED 2026-07-24: the scrub flip is MUTUALLY EXCLUSIVE with the `bypassPermissions` this recommendation depends on.** Any non-`0` value force-downgrades the permission mode to `default` (and now also breaks Claude Desktop's embedded Claude Code, which reads the same `~/.claude/settings.json`). Keep the scrub at `0`; take the sandbox half only. See docs/PLATFORM_NOTES.md for the full history + verification.
Rationale: this config runs `defaultMode: bypassPermissions`, so the normal
permission prompt is *off*. That makes an OS-level sandbox the primary
containment layer against prompt-injection or a runaway command reading
`~/.aws/credentials` / `~/.ssh` or exfiltrating to an arbitrary domain. The
sandbox **complements** (does not replace) the existing PreToolUse guard hooks
and Read/Edit deny-list. Cost: a few network/TLS-sensitive tools (`gh`,
`terraform`, `docker`, `gcloud`) need to be excluded or have domains
pre-allowed, or they silently fall back to unsandboxed execution.

## How the sandbox works (verified against official docs, 2.1.x)

- macOS uses **Seatbelt** (built in, no install). Filesystem + network confined
  at the OS level; all child processes inherit the boundary.
- **Filesystem default:** writes limited to cwd + session `$TMPDIR`; reads allow
  most of the FS **except** paths in `filesystem.denyRead`. Important: the
  default does **not** block `~/.aws/credentials` or `~/.ssh` — you must add them.
- **Network default:** no domains pre-allowed; a new domain triggers a prompt
  (or, with auto-allow + bypass, a fallback). Pre-allow via
  `network.allowedDomains`. The built-in proxy decides by hostname; it does
  **not** terminate TLS.
- **Permission interaction:** sandboxing and permission modes are independent
  layers. `autoAllowBashIfSandboxed: true` (default) means sandboxed Bash runs
  without a prompt but stays contained. Under `bypassPermissions`, sandboxed
  commands still respect sandbox boundaries; explicit deny rules and protected
  paths are still honored.
- **Escape hatch:** `allowUnsandboxedCommands: true` (default) lets Claude
  auto-retry a failed-in-sandbox command *outside* the sandbox. Under
  `bypassPermissions` that retry just runs — so network-needing commands quietly
  lose containment unless you pre-allow their domains or set this to `false`.
- **Hooks:** PreToolUse hooks run in the Claude process (not sandboxed) and
  still fire; the sandbox wraps the command execution itself.

## Interaction with THIS config

| Existing control | Interaction with sandbox |
|---|---|
| `defaultMode: bypassPermissions` | Sandbox becomes the main containment (prompts are off). Highest marginal value here. |
| Read/Edit deny globs (`~/.ssh`, `~/.aws`, `**/.env`, …) | Block the **tools**. A raw `cat ~/.aws/credentials` in Bash is only stopped by the bash-security-guard hook today; sandbox `filesystem.denyRead` adds OS enforcement. Complementary. |
| PreToolUse guard hooks (bash-security-guard, etc.) | Still run. Business logic + audit stay; sandbox catches what slips past Claude's judgment. Complementary, not redundant. |
| `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB: 0` | Currently secrets are inlined into subprocess env (see the wide-process-listing FORBIDDEN). Flipping to `1` + sandbox would be the strongest combined hardening **but is NOT AVAILABLE**: any non-`0` value force-downgrades `bypassPermissions` to `default` (verified 2026-07-24). Sandbox `filesystem.denyRead` is the reachable substitute for this layer. |

## Friction / breakage to expect on macOS

- **TLS-sensitive CLIs** (`gh`, `gcloud`, `terraform`, Go-based tools) often fail
  cert verification under Seatbelt's proxy → exclude them or accept unsandboxed
  fallback. `gh` is used heavily here, so it must be excluded.
- **`docker`** is incompatible → exclude.
- **Network default-deny**: AWS / GitHub / npm / PyPI / Anthropic / Tailscale /
  (future) MCP endpoints must be pre-allowed for those commands to stay
  *sandboxed* rather than falling back to unsandboxed.
- **AWS SSO / boto3**: needs the AWS domains allow-listed; otherwise boto3 calls
  fall back to unsandboxed (still work, but uncontained).

## Proposed settings block (NOT yet applied)

```jsonc
{
  "env": {
    // flip from "0" — stop inlining secrets into subprocess/hook/MCP env
    "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1"
  },
  "sandbox": {
    "enabled": true,
    "autoAllowBashIfSandboxed": true,      // no new prompts for safe sandboxed cmds
    "allowUnsandboxedCommands": true,       // start permissive; tighten to false later
    "excludedCommands": ["gh *", "terraform *", "docker *", "gcloud *"],
    "filesystem": {
      "denyRead": ["~/.aws", "~/.ssh", "~/.config/gcloud", "**/.env", "**/.env.*"],
      "allowWrite": ["/tmp"]                // cwd + $TMPDIR already writable
    },
    "network": {
      "allowedDomains": [
        "*.amazonaws.com", "*.amazonaws-us-gov.com",
        "github.com", "api.github.com", "*.githubusercontent.com",
        "registry.npmjs.org", "*.npmjs.org",
        "pypi.org", "files.pythonhosted.org",
        "api.anthropic.com", "*.anthropic.com",
        "*.tailscale.com"
      ]
    }
  }
}
```

### Phasing
1. **Phase 1 (proposed now):** block above with `allowUnsandboxedCommands: true`.
   Nothing hard-breaks; common commands run sandboxed, excluded/uncovered ones
   fall back. Flip env scrub on. Live with it for normal work.
2. **Phase 2 (later, optional):** set `allowUnsandboxedCommands: false` and
   `failIfUnavailable: true` for strict containment, after the allowed-domain /
   excluded-command list is proven against real workflows. Add MCP-server
   domains here once those servers are configured.

## Options for the decision
- **A — Enable Phase-1 sandbox + env scrub on (recommended).**
- **B — Strict from the start** (`allowUnsandboxedCommands:false`): max
  containment, more friction; expect to tune domains/exclusions for a few days.
- **C — Env scrub only, no sandbox:** lowest friction, modest hardening; keep
  relying on hooks + deny-list.
- **D — Leave as-is.**
