# Configuration profiles

Profiles are settings overlays for rebuilding this harness on a new machine
without copying host-materialized paths or stale permission decisions.

`fresh-laptop/settings.json` is the balanced personal default. It uses
`acceptEdits` for fast local iteration, lets Bash commands contained by the
native sandbox run without prompts, denies common credential paths, and
refuses automatic project MCP activation. It grants no `permissions.allow`
entries: read-only tools never prompt, so an allow entry for them is a no-op. A command that cannot run in the
sandbox falls back to normal permission review because the profile deliberately
does not grant blanket `Bash` permission.

`brandyn-operator/settings.json` is an owner-specific overlay. It activates the
`delivery` Bash policy pack and restores explicit review for high-consequence
Terraform, AWS, Git-history, and externally mutating MCP operations. The
installer layers it after `fresh-laptop`; it is not a replacement for the
sandbox profile.

The overlay enables no plugins and adds no marketplaces. Organisation-specific
capability belongs in a separate plugin marketplace; add it to an overlay only
once that plugin exists and resolves, because Claude Code reports a missing
plugin at every startup. Claude Harness remains the runtime owner either way.

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

Profile objects merge recursively. The permission rule lists (`allow`, `deny`,
`ask`) append in profile order and deduplicate, so a user's own decisions
survive the merge; other profile-owned lists replace the existing value. Before
this, applying the fresh profile over a curated `settings.json` silently cut a
34-entry allow list to 3.

Every file the installer copies (starter kit, rules, skills, hooks, agents,
agent-memory, ARCHITECTURE.md) is recorded with its sha256 in
`~/.claude/.harness-install-state.json`, so a re-run upgrades copies you never
touched, keeps the ones you edited (reported as `MODIFIED-BY-USER`), and on a
conflict keeps yours and writes the new version beside it as
`<name>.harness-new`. The same classification is available per path --
`python3 scripts/install-profile.py --target ~/.claude/settings.json --install
rules/operator-discipline.md --apply`; a directory installs every file beneath
it -- and `--force` overwrites regardless.

A Python target under `hooks/` (or `bin/`, `scripts/`) brings its local
dependencies along, transitively: every sibling module or package the file
imports (found by parsing it, module level or nested) and every checkout file
its `hooks/manifests/<name>.yaml` lists under `depends_on_files`. Each addition
is printed once -- `also installing hooks/_environment_catalog.py (imported by
hooks/bash-security-guard.py)` -- in preview and `--apply` alike, and is
classified and recorded exactly like an explicit target. A name with no sibling
file is stdlib or third-party and is ignored. Before this (2026-09-04),
`--install hooks/bash-security-guard.py --apply` upgraded the guard without the
`_environment_catalog` module it had started importing; the installed guard
crashed on import and the fail-closed Bash dispatcher blocked every command
until the module was copied in by hand. `bin/fresh_laptop_doctor.py` now also
checks, statically, that every installed hook imports only what is installed
beside it or resolvable by the interpreter.
