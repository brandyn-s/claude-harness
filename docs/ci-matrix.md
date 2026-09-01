# On-demand platform compatibility

> The filename is retained for existing links. The automatic operating-system
> matrix was deprecated in August 2026.

`.github/workflows/tests.yml (this export ships gitleaks.yml, plugins.yml, tests.yml; the upstream tests.yml is not part of it)` validates the Claude Code architecture, not
an end-user application distributed with a Windows, macOS, or Ubuntu support
contract. Automatic CI therefore runs the complete architecture suite once on
`ubuntu-24.04`. That runner is execution infrastructure; it is not a claim
that Ubuntu is the sole supported platform.

Windows, macOS, and Ubuntu compatibility remain available as operator-invoked
diagnostics. They are not scheduled and do not gate ordinary pull requests or
merge-queue entries.

## Current policy

| Event | Validation behavior |
|---|---|
| `pull_request` | Architecture suite once on `ubuntu-24.04` |
| `merge_group` | Architecture suite once on `ubuntu-24.04` |
| `push` to `main` | Architecture suite once on `ubuntu-24.04` |
| `workflow_dispatch` | Architecture suite on one operator-selected runner |
| Scheduled run | None |

The branch ruleset still requires the status check literally named
`validate`. That stable aggregate job succeeds only when the architecture job
succeeds; it does not aggregate an operating-system matrix.

## Run a compatibility diagnostic

In GitHub Actions, open **Validate Config**, select **Run workflow**, and pick
one runner:

- `ubuntu-24.04`
- `windows-2022`
- `macos-14`

The equivalent CLI command is:

```bash
gh workflow run tests.yml -f runner=windows-2022
```

Run the diagnostic when a change touches path handling, encoding, shell
behavior, permissions, native tooling, or another known platform boundary;
when investigating a platform-specific report; or when a release needs an
explicit compatibility claim. Choose only the runner relevant to the question
instead of paying for all three by default.

## What changed, and what did not

The automatic three-runner matrix and nightly backstop were removed because
they duplicated the same architecture suite, materially delayed merge-queue
completion, and provided limited marginal signal for this configuration
repository. The test coverage itself was not reduced: schema, manifest,
marketplace, architecture-drift, hook, script, skill, and historical
platform-regression tests still run in automatic CI.

Platform-aware implementation practices also remain in force. For example,
workflow scratch data uses `${{ runner.temp }}`, Python text behavior is fixed
to UTF-8, and test fixtures account for `HOME` and `USERPROFILE`. See
`rules/platform-constraints.md` and `rules/incidents/platform-constraints.md`
for the known failure modes.

## Claim discipline

A manual diagnostic supports only the platform and commit that actually ran.
Record that scope in PR or release evidence, for example:

> Verification: architecture validation passed on `windows-2022` at `<sha>`.

Do not infer Windows or macOS compatibility from the automatic Ubuntu-hosted
run, and do not imply that an on-demand diagnostic is a standing merge gate.
