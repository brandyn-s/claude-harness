# Known high-value repos

These repos consistently produce transferable patterns across 3+ runs.
Deep-dive their NEW skills (not previously read) before exploring unknown
repos.

**Schema note (2026-05-17, F-S2 fix from roundtable):** the prior "Skills
adopted" counter incremented only on SKILL.md diffs, making non-skill
destinations (rules / topics / memory / KB) invisible and incentivizing
every technique to be routed to SKILL.md regardless of fit. Going forward,
the "Patterns adopted" column annotates the destination in parentheses
next to the count, e.g. `5 (3 SKILL.md, 1 rule, 1 topic)`. Existing rows
below predate the schema change and default to SKILL.md unless
reclassified. Treat a rule/topic/memory adoption as worth the same as a
SKILL.md addition — the counter should not bias routing.

| Repo | Patterns adopted | Domain strength |
|------|---------------|----------------|
| `jwilger/eventcore` | 5 (DOMAIN phase, walking skeleton, commit gate, outside-in TDD, phase boundaries) | TDD, domain modeling |
| `wshobson/agents` | 6 (evidence tiers, dedup protocol, symptom routing, finding dedup merge rules, hypothesis generation categories, double-retry + blocking-async warnings) | Security, SRE, debugging |
| `mattpocock/skills` | 3 (vertical TDD, durable issues, out-of-scope KB) | Testing, QA, triage |
| `voxpelli/claude-beads` | 3 (project tempo, changelog cross-ref, upstream tracking concepts) | Maintenance, cross-project |
| `goldziher/html-to-markdown` | 2 (log levels, cardinality) | Observability, Rust |
| `johnlindquist/claude` | 1 (council multi-persona debate) | Creative, workflow |
| `citypaul/dotfiles` (a.k.a. `citypaul/.dotfiles`) | 5 (mutation testing brainstorm, characterisation-test naming conventions, suspicious-behavior marker, placeholder-driven algorithm, when-to-stop characterising heuristic) | Testing, QA |
| `chriswiles/claude-code-showcase` | 1 (prevention checklist) | Debugging |
| `affaan-m/everything-claude-code` | 1 (FAIL/PASS blocks) + context-budget-audit backlog entry | Security, context mgmt |
| `samber/cc-skills-golang` | 1 (single handling rule) | Error handling, Go |
| `tartinerlabs/skills` | 1 (scope-detection routing) | Security, testing |
| `getsentry/sentry-mcp` + `getsentry/skills` | 2 (4xx/5xx discrimination, pre-conclusion audit for code review) | Observability, security review |
| `ag-grid/ag-charts` | 1 (estimation + ambiguity clarification) | Planning, estimation |
| `n8n-io/n8n` | 1 (linear-issue analysis concept) | Linear, workflow |
| `obra/superpowers` | 1 (plan execution critical review gate) | Planning, execution |
| `microsoft/skills` | 1 (Staff Engineer Guide architecture review) | Documentation, review |
| `bitflight-devops/hallucination-detector` | 1 (evidence-grounded option evaluation) | Planning, research |
| `trailofbits/skills` | 5 (property-based testing catalog, defaults fast-path pattern, fuzzing harness construction methodology → KB topic, cargo-fuzz Rust workflow → KB topic, fuzzing dictionary construction → KB topic) | Security, testing, fuzzing |
| `microsoft/fluidframework` | 2 (mock decision gate functions, root-cause-tracing backward trace technique) | Testing, TDD, debugging |
| `yeachan-heo/oh-my-codex` | 1 (question classification for planning) | Planning, workflow |
| `factory-ai/factory-plugins` | 1 (exploitability rating scale) | Security, validation |
| `alexanderop/workoutTracker` | 1 (mutation testing execution workflow — backlog reference upgrade) | Testing, QA |
| `florianbruniaux/claude-code-ultimate-guide` | 0 (issue-triage backlog entry) | Triage, GitHub |
| `donchitos/claude-code-game-studios` | 1 (scope drift detection thresholds) | Planning, scope |
| `tanstack/intent` | 0 (skill-staleness-check backlog entry) | Meta-tooling, maintenance |
| `thebushidocollective/han` | 1 (legacy code characterization testing / RGR workflow) | Testing, legacy code |
| `openshift/lightspeed-operator` | 1 (complexity + duplication classification tables) | Code quality, Go |
| `lee-to/ai-factory` | 1 (leftover artifact scan gates for verification) | Quality, verification |
| `rshankras/claude-code-apple-skills` | 1 (behavior classification table for characterization tests) | Testing, legacy code |
| `jeffallan/claude-skills` | 1 (steady-state-gated blast-radius-controlled chaos experiment methodology → KB topic) | SRE, resilience, chaos engineering |
| `davila7/claude-code-templates` | 1 (IOC-database multi-ecosystem supply-chain audit pattern → /vendor-breach references) + capa-officer dropped as domain mismatch | Supply chain, security, regulated industry |
| `phylaxsystems/agent-skills` | 0 (PCL protocol-invariant mapping technique substantive but dropped — domain mismatch, Example doesn't write smart contracts) | Smart contracts, blockchain |

(Last updated: 2026-05-17 v1.4 — added Hook bucket and Domain Insight (Harness) sub-classification.)

## How many to deep-dive

- **8-12 repos** is the sweet spot
- First 3-4: unread skills from known high-value repos (highest yield)
- Next 4-8: novel repos from search results (discovery)
- Above 15: diminishing returns, context bloat

## After shipping: update this table

For each repo that produced at least 1 adopted pattern this session:
1. If already in the table: increment the count and append new pattern names
2. If not in the table: add a new row
3. Update the "(Last updated: ...)" line with today's date

Skip if the session produced 0 adoptions.
