# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Use GitHub's private vulnerability reporting on this repository
(**Security -> Report a vulnerability**). That channel is private to the
maintainers and does not require an email address.

Please include what you did, what happened, what you expected, and the impact
you think it has.

## Scope

This repository is configuration for a coding agent: hooks, rules, skills, and
agent definitions. The interesting attack surface is:

- **Hooks** (`hooks/`) — Python that runs on every tool call. A hook that fails
  open, crashes, or can be induced to pass a command it should block is a real
  finding.
- **Prompt-injection paths** — anything that reads untrusted content (web
  fetches, tool results, file contents) and lets it influence a decision.
- **Command construction** — shell strings assembled from variable input.

## Security model

The design assumes **the agent is a privileged but untrusted actor**: it holds
tools that can do damage, so safety is enforced *mechanically* by hooks that run
regardless of what the model decides, rather than by asking the model to
remember a rule. `hooks/bash-security-guard.py` is the clearest example.

This is a deliberate trade: publishing the enforcement logic also publishes its
shape to anyone probing it. We think a mechanism that only works while secret
is not a mechanism worth relying on, and the design is more useful shared. If
you find a bypass, the reporting channel above is the right place for it.
