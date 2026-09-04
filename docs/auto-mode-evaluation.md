# Auto mode for the operator overlay (evaluated 2026-09-03)

## Question
Can the operator overlay run `permissions.defaultMode: "auto"` while keeping the fresh core's deny list and native sandbox, and retire its `ask` list?

## Evidence
- The installed Claude Code 2.1.260 binary carries the auto-mode classifier and a first-class `/auto-mode-setup` flow that writes `autoMode.{environment, allow, soft_deny, hard_deny}` into the user settings file (hash-bound apply, `removeFromPermissionsAllow`); `autoMode` appears 91 times and `soft_deny` 44 times in the binary. The settings documentation page does not describe the block yet, so treat the schema as shipped-but-undocumented and re-verify on upgrades with `bin/test_hook_output_contract.py`'s binary check pattern.
- Public configurations already run it: fcakyon/claude-codex-settings ships `defaultMode: "auto"` with an `autoMode` block whose `environment` and `allow` lists start with `"$defaults"` (include the built-in rules) followed by prose entries; the classifier reads prose, not `Tool(pattern)` rules.
- Permission rules keep precedence over the classifier: `deny` still hard-blocks, `ask` still prompts. So an `ask` list under auto mode is pure prompt friction, while `autoMode.soft_deny` expresses the same categories as intent-judged blocks that yield to an explicit request.
- Observed on this machine (session of 2026-09-03, auto mode active): the classifier allowed every ordinary edit, test run and push, and blocked exactly one action, a bulk `git rm` of tracked files, until the user asked for it explicitly. That is the intended shape: no prompts, one intent-gated block.

## Decision
- `profiles/brandyn-operator/settings.json`: `defaultMode: "auto"`; the 27 former `ask` entries (terraform mutation, IAM and secrets, irreversible git, production security controls through MCP) become four `autoMode.soft_deny` prose entries; `environment` describes the workstation and names the env vars the guard reads; `allow` is `["$defaults"]`.
- The fresh-laptop core stays on `acceptEdits`: a first install should not depend on a classifier the doctor cannot verify offline.
- `scripts/install-profile.py` union-merges the `autoMode` lists like the permission lists, so a user's own entries survive re-installs.
- `bin/fresh_laptop_doctor.py` accepts `auto` or `acceptEdits` and defines the operator layer by the soft-deny categories rather than by `ask` rules.

## Caveats
- Auto mode is also selectable per session (`--permission-mode auto`); the setting only changes the default.
- `hard_deny` is intentionally unused: hard blocks stay in `permissions.deny` and in `bash-security-guard`, which run before the classifier and are tested.
- If a future version documents the block differently, the operator-profile test and the doctor will fail loudly rather than silently degrade.
