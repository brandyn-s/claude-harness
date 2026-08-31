# Claude Code runtime qualification

This directory contains deterministic, local qualification for release-sensitive
Claude Code behavior. The native runner is opt-in. It binds an ephemeral server
only on `127.0.0.1`, supplies a non-secret example API key, disables telemetry,
uses empty temporary configuration, and directs the Anthropic base URL to that
loopback server.

Run the settings contract on every change:

```zsh
python3 scripts/runtime-qualification/validate_cross_session_settings.py
```

Run the installed native release explicitly:

```zsh
python3 scripts/runtime-qualification/qualify_claude_release.py \
  --run-native \
  --claude "$(command -v claude)" \
  --expected-version 2.1.226
```

The native run creates a disposable Git repository with no remote and executes
eight scenarios:

- `schema-settings`: starts 2.1.226 with `crossSessionInbound: refuse`,
  `dialogExpiry: 5m`, and `isolatePeerMachines: true`.
- `if-push-nonmatch`: proves a benign nonmatching Bash command executes without
  starting the `Bash(git push*)` hook.
- `if-push-block`: proves `git push --dry-run` receives hook exit 2 and a
  permission-rule non-execution result.
- `if-commit-block`: proves `git commit --dry-run` receives the same blocking
  contract for `Bash(git commit*)`.
- `worker-local-bash`: proves a worker-shaped agent exposes Bash and runs `pwd`
  inside its linked worktree.
- `worker-cross-checkout-fence`: proves the worktree boundary refuses read-only
  `git -C <shared-checkout> status --short` redirection.
- `fork-skill-rendered-arguments`: loads a temporary `context: fork` skill and
  invokes it through the `Skill` tool with a multiword `args` value, then proves
  the value is rendered into `$ARGUMENTS` in the skill block sent to the
  loopback endpoint.
- `fork-skill-appended-arguments`: loads a second forked skill without the
  placeholder through the same tool path and proves Claude Code appends
  `ARGUMENTS: <value>` to that same skill block.

The push and commit forms cannot change repository state: the blocking oracle
requires proof that Bash did not execute; if that protection regresses, both use
`--dry-run` in the disposable repository. The cross-checkout command is read-only.
The skill fixtures contain no tools and their argument assertions inspect the
request captured by the loopback endpoint, before any model interpretation.

The opt-in pytest boundary invokes the identical command path:

```zsh
RUN_CLAUDE_NATIVE_QUALIFICATION=1 \
CLAUDE_EXPECTED_VERSION=2.1.226 \
PYTHONDONTWRITEBYTECODE=1 \
python3 -m pytest -p no:cacheprovider -q \
  scripts/runtime-qualification/test_qualify_claude_release.py
```
