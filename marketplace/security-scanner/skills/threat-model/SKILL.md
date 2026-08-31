---
name: threat-model
description: "Build a structured threat model — assets, trust boundaries, attacker stories, severity."
when_to_use: 'Use when analyzing attack surfaces or security risks. Trigger phrases: "threat model", "create a threat model", "analyze attack surface", "security analysis", "identify security risks". Do NOT use for vulnerability scanning (use /semgrep or /codeql), code review (use /differential-review), or false-positive verification on an existing finding (use /fp-check). Produces structured threat model: assets, trust boundaries, attacker stories, calibrated severity.'
argument-hint: "[optional scope: directory, module, or focus area]"
effort: max
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: Glob Grep Read Write Bash mcp__codebase-memory-mcp__get_architecture mcp__codebase-memory-mcp__search_graph
---
> **Compaction continuity:** Claude Code reattaches only the first 5,000
> tokens of an invoked skill after compaction, within a 25,000-token shared
> newest-first budget. If compaction occurs, re-invoke this skill before
> continuing; if model invocation is disabled, stop and ask the user to invoke
> it. Do not rely on tail instructions until the full body is restored.


# Threat Model

> Selectively cloned from tobihagemann/turbo `/create-threat-model`. Adapted
> for Example tooling (code-graph, Semgrep, CodeQL), DoD threat landscape
> awareness, and knowledge-base integration.

Analyze the current codebase and produce a structured threat model. The output
describes the current state: what it protects, where trust boundaries are, how
it can be attacked, what defenses exist, and how severe each risk is.
Descriptive, not prescriptive — no remediation recommendations in the model
itself.

Optional: `$ARGUMENTS` may specify scope (directories, modules, or focus
areas). When scope is provided, limit reconnaissance and code discovery to
the specified area. Still produce all four sections, but title the overview
to reflect the narrowed scope and note what is excluded.

---


> **Runtime policy:** Resolve the effective model and preserve refusal/fallback provenance per `../_shared/model-runtime-policy.md`.

## Step 0: Scope Detection

Before starting, check if the user's request is actually in-scope:

- **Vulnerability scanning** (keywords: "scan for vulns", "run semgrep", "find bugs") → Redirect to `/semgrep` or `/codeql` and stop.
- **Fix a vulnerability** (keywords: "fix this vuln", "patch", "remediate") → This skill is descriptive, not prescriptive. Tell the user to fix directly or use `/fp-check` to verify first.
- **CI/CD audit** (keywords: "GitHub Actions", "workflow security") → Redirect to `/agentic-actions-auditor` and stop.
- **False positive check** → Redirect to `/fp-check` and stop.

If the request is genuinely "analyze threats" or "threat model," proceed.
(Pattern source: tartinerlabs/skills scope-detection routing — Context7 registry evaluation 2026-04-05)

## Step 1: Reconnaissance

Build a mental model of the system before analyzing threats.

1. Read the project README, CLAUDE.md, and any architecture or security
   documentation (SECURITY.md, audit reports, existing threat models).
2. Examine top-level directory structure, build files, and dependency
   manifests to identify modules, languages, frameworks, and deployment model.
3. **Classify the application type**: library, CLI tool, web service, MCP
   server, desktop app, embedded/firmware, IaC module, or hybrid. This
   determines which threat categories and trust boundary patterns apply.
4. Identify security-critical dependencies (crypto libraries, auth providers,
   network stacks, native/FFI libraries). Note what this codebase delegates
   versus what it owns.
5. Read any existing security documentation: SECURITY.md, prior threat models,
   changelog entries mentioning CVEs, STIG findings if the repo has been
   assessed.

### Tooling integration (if available)

Check for existing analysis artifacts that inform the threat model:

- **code-graph**: If indexed (probe with `mcp__codebase-memory-mcp__get_architecture`
  — empty/error response means not indexed), use `search_graph` for entry
  points (label: "Function", relationship: "EXPORTS") and `get_architecture`
  for module dependency overview.
- **Semgrep/CodeQL results**: Check for `.sarif` files or recent scan output
  in CI artifacts. Prior findings identify known weak spots.
- **STIG assessments**: If `example-compliance-repo` or similar compliance work exists
  for this repo, note which controls have findings — they map to trust
  boundary weaknesses.

Do NOT run scans as part of this skill. Use existing results only.

## Step 2: Security-Relevant Code Discovery

Search the codebase for code that handles security-sensitive operations. Use
targeted searches, not exhaustive file reads.

**Categories to search for:**

- Authentication and authorization (login, OAuth, tokens, sessions, RBAC, API keys)
- Cryptographic operations (encryption, signing, hashing, key generation, key derivation)
- Secret and credential storage (keychains, vaults, env vars, config files with secrets)
- Network communication (HTTP clients, TLS configuration, certificate handling, WebSocket, gRPC)
- Untrusted input processing (file parsing, deserialization, XML/JSON/YAML from external sources)
- IPC and process boundaries (sockets, pipes, CLI subprocesses, shared memory, MCP stdio transport)
- Plugin and extension loading (dynamic imports, MCP tool registration, middleware chains)
- Update and distribution mechanisms (auto-update, download verification, signature checking)
- Implicit network behavior (link previews, auto-fetches, webhook callbacks triggered by remote data)
- Native code / FFI boundaries (C interop, unsafe blocks, ctypes, WASM)
- **OPA/policy enforcement** (authorization decisions, policy bypass paths, fail-open defaults)
- **Container and deployment boundaries** (Dockerfile USER directives, ECS task roles, network policies)

For each flow found, note the relevant files and trace data from input to
processing to output.

### Search strategy

Use `Grep` with targeted patterns per category. For projects indexed in
code-graph, also use `search_graph(label="Function", name_pattern="auth|login|verify|sign|encrypt|hash|token")` to find security-relevant functions structurally.

For broad semantic searches ("find all credential handling", "locate encryption config"),
use `/code-explore`'s multi-phrasing pipeline (Step 1.5) which generates natural language +
hypothetical code + framework idiom phrasings and merges results with confidence tiers.
This catches 40-60% more files than natural language alone on Nix and Rust codebases
(see `code-explore/references/search-strategies.md` for quantitative evidence).

## Step 3: Write the Threat Model

Write to `threat-model.md` at the project root (or `docs/threat-model.md` if
a `docs/` directory exists). The document has exactly four sections. Adapt
depth to the codebase: a small CLI tool needs less detail than a multi-component
crypto system or MCP server.

## Section 1: Overview

Write 1-2 paragraphs covering:

- What the software is, its deployment model, and high-level architecture
  with key components (reference source paths)
- Security-sensitive flows as a bulleted list (3-5 items, one sentence each)
- What this repo owns versus what it delegates, and where the largest risks
  concentrate

For codebases with unique security properties (zero-knowledge design,
client-side crypto, MCP tool authorization, OPA policy enforcement), call
them out explicitly.

## Section 2: Trust Boundaries and Assumptions

**Assets**: What has value to an attacker. Be specific: name data types, key
material, tokens, metadata. Group naturally (user data, secrets, integrity
artifacts).

**Trust boundaries**: Where trust levels change. Each boundary gets a **bold
name**, a colon, 1-2 sentences explaining what crosses it, and a
parenthetical code reference. Typical boundaries: untrusted storage/network,
local OS/filesystem, IPC, admin configuration, identity provider, database,
MCP client-server boundary, container-host boundary, OPA policy decision point.

**Inputs by control tier:**

- **Attacker-controlled**: Data from untrusted sources that the software
  parses. For libraries, include data passed through the API from untrusted
  origins. For MCP servers, include tool arguments from potentially
  compromised clients. Reference specific entry points.
- **Operator-controlled**: Configuration, credentials, deployment parameters.
  Trusted but can be misconfigured.
- **Developer-controlled**: Build scripts, dependency versions, test fixtures,
  debug-only behavior. The supply chain boundary.

**Assumptions**: Explicit statements about what must be true for the security
model to hold. Include environmental assumptions (OS isolation, network
segmentation), dependency assumptions (crypto library correctness), and
operational assumptions (caller protects passwords, OPA sidecar is reachable).
2-4 bullets.

## Section 3: Attack Surface, Mitigations, and Attacker Stories

Organize into subsections by attack surface area (not by STRIDE category or
component). Each subsection follows this structure:

```markdown
### [3.N] [Surface Name]

**Surface**: What is exposed and where (1-2 sentences with file references).

**Mitigations**
- What the code already does to defend this surface (observations, not recommendations).

**Attacker stories**
- Concrete scenario: "[Attacker type] does [action] to [goal]: [consequence and severity context]."
```

**Decomposition heuristic**: One surface per distinct trust boundary crossing
or distinct attacker capability. If two areas share the same entry points AND
mitigations, merge them. If a single surface needs more than 3-4 unrelated
risk/mitigation pairs, split it. Typical range: 4-9 surfaces.

**For each surface, document:**

- 1-2 sentence surface description with file references
- 2-4 mitigation bullets describing existing defenses (what the code does,
  not what it should do)
- 2-3 attacker stories: one sentence each, naming attacker type, action, and
  consequence

**DoD context** (when applicable): If the codebase operates in a DoD or
FedRAMP environment, include attacker types relevant to that threat landscape
(nation-state, insider threat with privileged access, supply chain
compromise). Only when the repo's deployment context warrants it — do not
inject DoD framing into general-purpose open source tools.

**End Section 3 with**: A brief note on vulnerability classes that are less
relevant for this application type, explaining why.

## Section 4: Criticality Calibration

Group findings into four tiers. Each tier has 2-4 items, each a single
sentence describing the **impact** (not the attack vector).

- **Critical**: Remote exploitation compromising crown jewels or achieving
  code execution. Auth bypass, key/credential theft, RCE, cryptographic bypass.
- **High**: Significant compromise requiring specific preconditions. Privilege
  escalation, targeted data theft, bypassing a major security control,
  integration compromise.
- **Medium**: Real but limited impact or unlikely preconditions. Metadata
  leaks, DoS, policy bypass without data compromise, local data exposure.
- **Low**: Theoretical, requires pre-compromised environment, or minimal
  impact. Verbose error messages, UI-only issues, log noise, debug-only risks.

Close with a calibration paragraph explaining how the application's deployment
model and trust boundaries influence severity.

## Deterministic verification (harness)

Before presenting the model, run the oracle. Optional but recommended:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/threat-model/scripts/verify_claims.py threat-model.md --root . --ndjson run.ndjson \
  [--claims claims.json --project <indexed-project>] --strict
python3 ${CLAUDE_PLUGIN_ROOT}/skills/threat-model/scripts/model_history.py append run.ndjson --repo "<repo>"
```

The Tier-1 oracle gates structure (4 sections), file references
(everything resolves), and surface attribution (Mitigations + Attacker
stories per surface). The Tier-2 oracle now grounds each cross-boundary
claim DETERMINISTICALLY against source: a claimed edge's endpoint symbols
must be present in the code (GROUNDED — a *necessary* condition, not proof
of the specific A→B edge), else the claim is UNSUBSTANTIATED and `--strict`
fails the run; patterns too ambiguous to search are MANUAL (human-required),
never silently passed. A Cypher intent is still emitted per claim so an
orchestrator with `mcp__codebase-memory-mcp__query_graph` can run the stronger graph
query and append `calls_edge_verdict` records — but the deterministic
grounding is the gate now, not the always-true emitter it replaced.
`model_history.py` captures grounded vs unsubstantiated ratios. See
[references/harness-pattern.md](references/harness-pattern.md) for the
eight-component map.

## Step 4: Review

Before presenting the output, validate:

1. **Codebase-specific**: Every claim references actual files, modules, or
   architectural patterns. No generic filler.
2. **Complete coverage**: All security-sensitive flows from Step 2 appear in
   at least one attack surface.
3. **Balanced mitigations**: Each surface lists existing defenses. If none
   exist, state that explicitly.
4. **Concrete stories**: Each attacker story names a specific attacker, action,
   and consequence. No abstract "an attacker could exploit a vulnerability."
5. **Consistent severity**: Calibration in Section 4 is consistent with
   severity context in Section 3 stories.
6. **Appropriate scope**: Dependencies are acknowledged with assumptions, not
   audited internally. Integration boundaries are analyzed.
7. **Out-of-scope declared**: Irrelevant vulnerability classes are named and
   dismissed with reasons.

Fix any gaps, then present the threat model to the user.

## Step 5: Cross-Reference with Existing Tooling

After the model is written, suggest next steps based on what the model found:

- Surfaces with no mitigations → suggest `/semgrep` or `/codeql` scan scoped
  to those files
- Input processing surfaces → suggest `/insecure-defaults` check
- API/web surfaces → suggest `/sharp-edges` review
- CI/deployment surfaces → suggest `/agentic-actions-auditor`
- If the repo is part of an ATO pipeline → note which STIG controls map to
  the identified surfaces

These are suggestions, not automatic invocations. The threat model is the
deliverable.

---

## Rules

- Ground every claim in code. Reference specific functions, files, or paths.
  Do not speculate about code you have not read.
- When a mitigation is absent, say so explicitly. Do not invent mitigations.
- Do not audit the internals of external dependencies. Analyze the integration
  boundary only.
- Adapt depth to the project. A 500-line CLI tool does not need the same depth
  as a cryptographic library or MCP server handling untrusted tool arguments.
- The threat model is the only output. Do not create code, fix vulnerabilities,
  or modify the codebase (except writing the threat model file itself).
- Use `##` for the four top-level sections (numbered 1-4), `###` for attack
  surface subsections, and `**bold**` for sub-headings within subsections.
- If the codebase has no meaningful security surface (no crypto, no auth, no
  network, no untrusted input), produce a brief threat model stating this
  with rationale, covering only dependency and supply-chain risks.

## Success Criteria

- [ ] Application type classified (library, CLI, web service, MCP server, etc.)
- [ ] All security-sensitive code flows identified with file references
- [ ] 4-section threat model written with code-grounded claims
- [ ] Every attack surface has mitigations documented (or explicit "none")
- [ ] Every attacker story names attacker type, action, and consequence
- [ ] Criticality calibration consistent with attack surface analysis
- [ ] Out-of-scope vulnerability classes declared with rationale
- [ ] Cross-reference suggestions provided for follow-up scanning

## Examples

**Example 1: MCP server**
```
/threat-model
```
Produces threat model for the current repo, auto-detecting it as an MCP server.
Focuses on: tool argument injection, OPA policy bypass, credential exposure,
container escape, client trust boundary.

**Example 2: Scoped analysis**
```
/threat-model src/auth/
```
Produces threat model scoped to the auth module. Notes what's excluded.
Focuses on: authentication flows, session management, token handling.

**Example 3: Embedded/firmware**
```
/threat-model firmware/
```
Adapts to embedded context: physical access threats, firmware update integrity,
debug interface exposure, supply chain for embedded dependencies.
