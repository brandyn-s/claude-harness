---
name: manifest-gen
description: "Generate or refresh manifest.yaml files for skills, hooks, rules, KB topics, and more."
when_to_use: 'Generate or refresh manifest.yaml files for skills, hooks, rules, KB topics, session transcripts, MCP tools, Terraform modules, and product platform releases. Runs scaffold generators for mechanical extraction, then fills judgment-required fields by reading source. Use when adding new components, onboarding a new machine, refreshing manifests after changes, extending manifests to new domains, or generating a platform manifest from a ExampleOne release. Trigger phrases: "generate manifests", "scaffold manifests", "manifest gen", "refresh manifests", "onboard manifests", "product manifest", "platform manifest". Do NOT use for editing one manifest field by hand (just edit the file), validating an existing manifest (use /validate-changes), or initial skill scaffolding (use /init).'
argument-hint: "[--all | --skills | --hooks | --rules | --sessions | --mcp | --terraform | [--path [release-dir] --product [name]] | [component-name]]"
allowed-tools: Bash Read Write Edit Grep Glob AskUserQuestion
metadata:
  author: example-security-engineering
  version: "1.0"
effort: medium
---

# Manifest Gen — Generate and Refine Component Manifests

Generate structured YAML manifests for architecture components across three
scaffold generators covering 8 domains.

## Domains and Scaffolds

Paths under the claude-config repo root are written as `skills/...`. Paths
outside the repo root (KB, sessions, MCP, Terraform) are absolute — they
resolve from `$HOME` via `scaffold_extended.py` and are NOT located inside
the claude-config checkout. If you can't find a manifest at the listed
path, confirm the relevant source tree exists at the absolute location.

| Domain | Scaffold | Location | Auto-populated fields |
|--------|----------|----------|---------------------|
| Skills | `scaffold.py` | `<repo>/skills/*/manifest.yaml` | tools, topics, rules, skills, category, description |
| Hooks | `scaffold.py` | `<repo>/hooks/manifests/*.yaml` | event, matcher, action_type, description |
| Rules | `scaffold.py` | `<repo>/rules/manifests/*.yaml` | description, incident count |
| KB Topics | *retired* — the knowledge base compiles `topics/*.md` itself: run `python3 ~/Documents/knowledge-base/tools/kb.py build` (then `check`) | `~/Documents/knowledge-base/generated/*.json` | id, title, tags, stage, entries, links, word count |
| Sessions | `scaffold_extended.py` (manual draft only) | `~/.claude/manifests/sessions/*.yaml` | Partial transcript scan; duration, tokens, repos, and PR fields remain TODO |
| MCP Tools | `scaffold_extended.py` | `~/Documents/GitHub/mcp-servers/manifests/*.yaml` | tool name, operation type, parameters |
| Terraform | `scaffold_extended.py` | `~/Documents/GitHub/mcp-infra/manifests/*.yaml` | resources, variables |
| Product | `scaffold_product.py` | stdout, or `<release>/manifest.yaml` via `--output <path>` | services, NixOS configs, components, IAM, security groups, KMS, secrets, EBS, backup, ALB routing, VPN topology |

## When to Use

- New skill/hook/rule added without a manifest
- Onboarding a fresh machine (clone repo -> generate all manifests)
- Periodic refresh after architecture changes
- An explicit manifest coverage check reports a missing component
- Extending manifests to KB topics, MCP tools, or Terraform modules

## Phase 1: Scaffold

Run the appropriate scaffold generator. The scaffold scripts live under
`<repo-root>/manifests/` in the claude-config checkout, not under
`~/.claude/` (the `~/.claude/manifests/` path was a deployment assumption
that broke for any user who installed the repo elsewhere). Resolve the
path once at the top of your shell session and reuse it:

```bash
# Portable resolution — honors CLAUDE_MANIFESTS_DIR override, otherwise
# walks up to the claude-config repo root. Set CLAUDE_MANIFESTS_DIR
# explicitly if you have a non-standard layout (e.g., monorepo, vendored
# install).
MANIFESTS_DIR="${CLAUDE_MANIFESTS_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)/manifests}"
test -f "$MANIFESTS_DIR/scaffold.py" \
  || { echo "scaffold.py not found at $MANIFESTS_DIR; set CLAUDE_MANIFESTS_DIR" >&2; exit 1; }
```

### Claude-config components (skills, hooks, rules)

```bash
# All unmanifested components
python3 "$MANIFESTS_DIR/scaffold.py"

# Specific types
python3 "$MANIFESTS_DIR/scaffold.py" --skills
python3 "$MANIFESTS_DIR/scaffold.py" --hooks
python3 "$MANIFESTS_DIR/scaffold.py" --rules

# Single component
python3 "$MANIFESTS_DIR/scaffold.py" --component {name}

# Preview without writing
python3 "$MANIFESTS_DIR/scaffold.py" --dry-run
```

Bad flags fail loudly: `python3 "$MANIFESTS_DIR/scaffold.py" --nonexistent`
exits non-zero with a usage line. If you see exit 0 on a typo, the
deployed copy is stale — re-pull the repo.

### Extended domains (KB, sessions, MCP, Terraform)

```bash
# All extended domains
python3 "$MANIFESTS_DIR/scaffold_extended.py" --all

# Specific domains
python3 "$MANIFESTS_DIR/scaffold_extended.py" --sessions --days 30
python3 "$MANIFESTS_DIR/scaffold_extended.py" --mcp
python3 "$MANIFESTS_DIR/scaffold_extended.py" --terraform

# Preview
python3 "$MANIFESTS_DIR/scaffold_extended.py" --dry-run --sessions
```

KB topics are NOT a domain here. The knowledge base compiles `topics/*.md`
itself; `--kb` was retired and is rejected with a usage error:

```bash
python3 ~/Documents/knowledge-base/tools/kb.py build
python3 ~/Documents/knowledge-base/tools/kb.py check
```

### Product platform manifests

```bash
# Generate manifest for a release
python3 "$MANIFESTS_DIR/scaffold_product.py" --path /path/to/release --name ExampleOne --version 0.22.1

# Preview without writing
python3 "$MANIFESTS_DIR/scaffold_product.py" --path /path/to/release --dry-run

# Write to file
python3 "$MANIFESTS_DIR/scaffold_product.py" --path /path/to/release --output /path/to/output.yaml
```

### What each scaffold extracts mechanically

**Skills**: MCP tool references (`mcp__*` patterns), topic file mentions,
rule references, skill cross-references, frontmatter fields, category guess.

**Hooks**: docstring description, event/matcher from settings.json,
action type detection (guard/fixer/injector/logger).

**Rules**: heading as description, incident reference count.

**KB Topics**: frontmatter (stage, tags, created, updated), entry count,
word count, cross-topic links (wiki-links, backtick refs, markdown links,
title-based references), staleness computation.

**Sessions**: `scaffold_extended.py --sessions` creates review-required drafts
from the legacy `~/.claude/session-transcripts/` directory. It does not prove
duration, tokens, repositories, pull requests, or completion state, and it does
not cover the primary `~/.claude/projects/**.jsonl` corpus. Treat raw
transcripts plus explicit `/retro` evidence as authoritative; never use a draft
session manifest as proof that work completed.

**MCP Tools**: `@tool()` decorated functions from Python source, or
structured entries from `mcp-catalog.json`. Operation type (read/write/delete)
from tool name patterns.

**Terraform**: `resource` block types from HCL, variable references.
Sensitivity marked as TODO (auto-classification from resource types gets
composite modules wrong).

**Product**: Two source trees walked in parallel:
- *From Terraform* (`example-one-terraform/`): service modules from
  `modules/services/*/main.tf` (instance types, EBS, IAM, secrets, DLM,
  ALB routing, submodules), environment from `modules/environment/` (VPC,
  ALB, KMS, flow logs, S3), security groups from `modules/security/`,
  platform config from `providers.tf` + `variables.tf` (region, state
  backend, cross-account roles, feature flags, auth defaults).
- *From NixOS* (`nix/hardware/cloud/*/`): `example.services.*` enabled
  components, system services (postgresql, nginx), VPN node class, firewall
  ports, NixOS configuration names, monitoring, hostname.

## Phase 2: Refine

For each scaffolded manifest with TODO markers, read the source file
and fill in what requires understanding:

### For skills — read the SKILL.md body:

1. **requires_auth**: Does the skill call `mcp__remote-*` tools? If yes,
   which providers and is it main_thread_only?
2. **input_contract.parameters**: What arguments does the skill accept?
3. **output_contract.produces**: What does the skill generate?
4. **side_effects**: Write files? Create PRs? Send messages? Modify memory?
5. **execution_context**: Dispatch agents (parallel_workers)? Single worker?
   Or inline (main_thread)?
6. **threat_model**: read_only, writes_local, writes_remote, destructive.
7. **preconditions**: What must be true before the skill runs?
8. **guardrails**: Which hooks fire during this skill's execution?
9. **estimated_turns**: Estimate from step count and complexity.

### For hooks — read the Python source:

1. **enforces**: Which rules does this hook mechanically enforce?
2. **blocks_patterns**: What specific patterns does it block?
3. **injects**: What context does it add?
4. **depends_on_files**: Config files it reads (e.g., protected-repos.json).
5. **depends_on_env**: Environment variables needed.

### For rules — read the markdown body:

1. **applies_to**: What files, tools, or actions does this rule cover?
2. **trigger_conditions**: When is the rule relevant?
3. **required_actions / prohibited_actions**: What must/must not the agent do?
4. **enforcement_coverage**: none, partial, or full. `enforced_by` is omitted
   from rule source manifests; `compile.py` derives it from wired hook manifests.
5. **incidents**: Extract date + summary from incident references.

### For MCP tools — read the Python source:

1. **auth_provider**: Which auth system (crowdstrike_falcon, entra_oauth, api_key).
2. **opa_policy**: OPA policy name if write-gated.
3. **rate_limit**: From server docs or configuration.
4. **response_size**: From testing or documentation.
5. **gov_cloud**: True if uses .us, laggar.gcw, or FedRAMP endpoints.

### For Terraform — read the HCL:

1. **sensitivity**: low/medium/high/critical based on actual resource config
   (not just type name — an IAM execution role != an admin role).
2. **depends_on_modules**: Which other .tf files does this reference?
3. **consumers**: Which MCP servers use these resources?
4. **change_impact**: What breaks if this module is modified?

### For product manifests -- read the TF + NixOS source:

1. **description**: Write a human-readable role description for each service
2. **components**: Expand example.services names into component descriptions with roles
3. **secrets**: Describe what each secret contains and who has access
4. **known_gaps**: Compare against IL5/compliance requirements and document gaps
5. **cross_account**: Document all cross-account access paths and persistence
6. **network**: Add ALB auth mode (authenticate-oidc, allow, none) from listener rules

### For KB topics -- usually no refinement needed:

The KB scaffold populates all fields from frontmatter + structural analysis.
Only check if orphan status (linked_from empty) seems wrong — the title-based
link detection catches most cross-references but may miss unusual phrasings.

## Phase 3: Validate

After refining, compile and validate:

```bash
# Claude-config components (structural + semantic validation).
# compile.py and query_engine.py intelligently detect the claude-config
# checkout containing this script, or fall back to ~/.claude for legacy
# deployments. Explicitly passing --root is optional but recommended to
# ensure the intended root is used.
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
python3 "$MANIFESTS_DIR/compile.py" --root "$REPO_ROOT"

# Extended domains don't have a compiler yet — validate by inspection
python3 "$MANIFESTS_DIR/scaffold_extended.py" --dry-run --sessions  # should show 0 to create
```

The compiler checks:
- **Structural**: no dangling references (every requires_rules,
  requires_skills points to an existing manifest). Counts toward exit code.
- **Routing**: hooks/skill-rules.json points at real skills. Counts toward
  exit code.
- **Semantic**: split into two buckets — `MISSING_SOURCE` (manifest exists
  but its SKILL.md/rule.md is gone — hard error, gates exit code) and
  `DRIFT` (manifest `requires_tools` and SKILL.md prose disagree — soft
  warning, does NOT gate exit code; intentional when prose is aspirational).
  Read both blocks; only `MISSING_SOURCE` and structural/routing issues
  cause `compile.py` to exit non-zero.

## Phase 4: Commit

Ship manifests following the growth convention:

- New components: manifest.yaml in the same commit as the source file
- Batch generation (onboarding): one commit with all manifests
- Refresh: one commit per batch of updated manifests
- KB topic manifests: ship to `claude-knowledge-base` repo
- MCP tool manifests: ship to `mcp-servers` repo
- Terraform manifests: ship to `mcp-infra` repo

```bash
# compile.py intelligently detects the claude-config checkout containing this
# script. Passing --root explicitly is optional. compile.py returns non-zero
# when issues exist even though graph.json IS written, so do NOT use && to
# gate the commit:
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
python3 "$MANIFESTS_DIR/compile.py" --root "$REPO_ROOT"
exit_code=$?
# graph.json was still written. Inspect any reported issues, then commit:
# git add manifests/graph.json <new/changed manifests>
# If exit_code != 0, decide whether the issues are blocking before committing.
```

## Do NOT Auto-Generate Without Review

The scaffold produces drafts with TODO markers. Do not ship manifests
with TODO markers — every field must be filled in by reading the source.
Historically observed: machine inference from prose gets dependencies
wrong often enough that a human read pass is required before shipping
(the originally-cited 12% figure was from an internal experiment whose
artifact is not preserved; treat the rate as "non-negligible" rather than
exact). Scaffold -> read -> fill -> validate -> ship.

**Exception**: KB topic manifests are fully auto-populated from frontmatter
and can be shipped without manual review. Session-manifest drafts always need
review and remain non-authoritative while their TODO fields are unresolved.

## Examples

**Example 1: Onboarding — scaffold everything**
User says: `/manifest-gen --all`
Actions: Run `scaffold.py` (or `scaffold.py --all`) for skills + hooks + rules, then `scaffold_extended.py --all` for KB + sessions + MCP + Terraform. (Product manifests are generated per-release via `scaffold_product.py` and are NOT covered by `--all`.) Refine TODO markers for each domain by reading source. Validate with `compile.py --root "$(git rev-parse --show-toplevel)"`.
Result: All 7 of the recurring domains have manifests; `query_engine.py --root "$REPO_ROOT" coverage` reports the claude-config slice (skills + hooks + rules).

**Example 2: After adding one new skill**
User says: `/manifest-gen my-new-skill`
Actions: Run `scaffold.py --component my-new-skill`. Read the SKILL.md body and fill in `requires_auth`, `input_contract`, `side_effects`, `execution_context`, `threat_model`. Run `compile.py`.
Result: `skills/my-new-skill/manifest.yaml` committed alongside SKILL.md in same PR.

## Success Criteria

- `python3 compile.py --check` passes with 0 structural,
  0 routing, and 0 `MISSING_SOURCE` semantic issues. (`DRIFT` warnings are
  allowed — they're soft, don't gate the exit code, and can be intentional.)
  The script automatically detects the claude-config checkout; `--root` can
  override if needed.
- `python3 query_engine.py --root "$REPO_ROOT" coverage` shows manifest
  coverage for every skill, hook, and rule you added or touched in this
  change. 100% across the whole tree is aspirational — some upstream
  components are intentionally unmanifested.
- No TODO markers remain in shipped manifests (except Terraform sensitivity)
- Each manifest has been validated against its source file
