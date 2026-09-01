# Configuration profiles

Profiles are settings overlays for rebuilding this harness on a new machine
without copying host-materialized paths or stale permission decisions.

`fresh-laptop/settings.json` is the balanced personal default. It uses
`acceptEdits` for fast local iteration, auto-allows read/search tools and Bash
commands contained by the native sandbox, denies common credential paths, and
refuses automatic project MCP activation. A command that cannot run in the
sandbox falls back to normal permission review because the profile deliberately
does not grant blanket `Bash` permission.

`brandyn-operator/settings.json` is an owner-specific overlay. It activates the
`delivery` Bash policy pack and restores explicit review for high-consequence
Terraform, AWS, Git-history, and externally mutating MCP operations. The
installer layers it after `fresh-laptop`; it is not a replacement for the
sandbox profile.

The overlay also references the private `brandyn-s/claude-config` marketplace
and enables its `example-operator` plugin. That plugin is deliberately tiny: it
ships the measured protected-release preflight and no ambient rules, broad Bash
guard, permission policy, or sandbox configuration. Claude Harness remains the
runtime owner; `claude-config` supplies only organization-specific capability.

Its Bash hook enables only catastrophic checks by default. Optional policy
stays in the same process and can be selected without another hook:

```json
{
  "env": {
    "CLAUDE_BASH_POLICY_PACKS": "delivery,portability,workflow"
  }
}
```

The root author-workstation settings use `all` for compatibility. Pack
definitions are directly sourced in `hooks/bash_policy_tables.py`; there is no
generated table or second dispatcher.

Preview the merge without changing anything:

```bash
python3 scripts/install-profile.py --profile fresh-laptop
```

Apply it after reviewing the preview:

```bash
python3 scripts/install-profile.py --profile fresh-laptop --apply
```

Preview the operator composition in the same order used by the installer:

```bash
python3 scripts/install-profile.py \
  --profile fresh-laptop \
  --profile brandyn-operator
```

The operator starter also installs `operator-discipline.md`, the bounded
non-progress detector, and prompt/output secret controls. `portability` remains
conditional: add it beside `delivery` on Windows/Git Bash machines. `workflow`
remains opt-in because its preferences are not universal correctness
boundaries.

Application writes a timestamped backup beside the target settings file. The
repository-root `settings.json` is the advanced author-workstation reference;
the installer materializes its command paths for the target host.

Profile objects merge recursively. Profile-owned lists replace the existing
value, except `permissions.ask`: review boundaries append in profile order and
deduplicate. This prevents the operator layer from silently deleting a local
high-consequence review rule while still letting the fresh profile own its
allow, deny, sandbox, and MCP defaults.
