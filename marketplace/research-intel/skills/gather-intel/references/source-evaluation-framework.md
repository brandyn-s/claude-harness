# Source Evaluation Framework

Every finding from Phase B is scored on three dimensions. The composite determines whether it's presented and how prominently.

## Dimension 1: Source Authority

| Tier | Source type | Examples | Trust level |
|------|-----------|----------|-------------|
| **T1 — Official** | Anthropic documentation, changelog, engineering blog | code.claude.com/docs, CHANGELOG.md, anthropic.com/engineering | Highest. These define intended behavior. |
| **T2 — Verified practitioner** | Posts >100 upvotes, known tool authors, established technical blogs with reproducible evidence | obra (superpowers author), Trail of Bits, Addy Osmani, 749pt "13 no-bs lessons" | High. Battle-tested by experienced practitioners. |
| **T3 — Community consensus** | Multiple independent reports of the same pattern, even if individual posts have lower engagement | "40% context cliff" (confirmed by 3+ posts from different authors) | High. Independent convergence is the strongest community signal. |
| **T4 — Single report** | Individual post or blog, no corroboration, but includes specific detail and evidence | "I found this hook pattern works for my 500-file Go backend" (35pts) | Medium. Useful as a lead, needs verification before adopting. |
| **T5 — Unverified** | Marketing content, AI-generated blogs, tool promotion without evidence, vague claims | "This tool changes everything!" with no specifics | Lowest. Discard unless the underlying tool is independently verifiable. |

**How to determine tier during search:**
- WebSearch results include source domain — `code.claude.com` = T1, `github.com/anthropics` = T1
- Reddit: extract upvote count from snippet. >200pts = likely T2, >100pts = T2-T3, <50pts = T4
- HN: extract point count. Same thresholds.
- Blogs: check author. Known names (Anthropic employees, tool creators) = T2. Unknown = T4.
- GitHub: check stars and recency. >100 stars + active commits = T2-T3. <20 stars = T4.
- Multiple sources reporting the same finding independently = automatically T3 regardless of individual tier.

## Dimension 2: Evidence Strength

| Grade | Definition | Indicator |
|-------|-----------|-----------|
| **Verified** | Includes code, reproduction steps, screenshots, or test results. Can be validated independently. | "Here's the hook config that works: [JSON]. Tested on v2.1.38." |
| **Observed** | Describes real-world experience with specific context (project type, scale, duration, outcomes). | "On our 100K-line codebase, this cut context usage by 40% over 3 weeks." |
| **Theoretical** | Reasonable advice based on understanding of how Claude Code works, but not explicitly tested. | "Since context degrades past 40%, you should compact earlier." |
| **Anecdotal** | Single N=1 observation without detail, or "I heard that..." | "Opus seems worse after the update" with no specifics. |

## Dimension 3: Applicability to THIS Architecture

| Score | Definition | Indicators |
|-------|-----------|------------|
| **Direct** | Addresses a specific component of this architecture: MCP-heavy, persistent-memory agents, Windows, GovCloud/FedRAMP, security ops, hooks, superpowers plugin | "For MCP servers returning >200K tokens..." / "On Windows with Git Bash..." |
| **Partial** | General Claude Code pattern that could apply but needs adaptation. Different domain but similar structural pattern. | "Hook pattern for Node.js auto-formatting" (different domain, same hook mechanism) |
| **Tangential** | General AI coding advice or different tool/platform. Would need significant rework to apply. | "How I use Cursor with GPT-5" / "React component patterns" |
| **Irrelevant** | Different model, different tool, different platform entirely. | "Gemini Code tips" / "Copilot workspace patterns" |

## Composite Priority Matrix

| Priority | Criteria | Action |
|----------|----------|--------|
| **HIGH** | T1-T2 authority + Verified/Observed evidence + Direct applicability | Present prominently. Recommend specific file changes. |
| **HIGH** | T3 (consensus) + any evidence + Direct/Partial applicability | Multiple independent reports outweigh weak individual evidence. Present prominently. |
| **MEDIUM** | T2-T3 + Theoretical evidence + Direct applicability | Worth investigating. Present with "needs verification" flag. |
| **MEDIUM** | T4 + Verified evidence + Direct applicability | Single source but strong evidence for this exact setup. Present as lead. |
| **LOW** | T4-T5 + Anecdotal/Theoretical + Partial/Tangential | Note but don't present as actionable. Include in "Noted" section for audit trail. |
| **DISCARD** | T5 + any + Tangential/Irrelevant | Do not present. |

## Source Bias Indicators

Flag these bias risks when evaluating community sources. Sources with bias tags are NOT automatically discarded — the bias is noted alongside the finding so the user can weigh it.

| Bias type | Indicator | How to flag |
|---|---|---|
| **Vendor/tool promotion** | Author is the tool's creator or maintainer, or post is from the tool's official account | Tag: `[vendor]` — cap at T3 unless independently corroborated |
| **Sponsored** | Content is sponsored, paid, or part of an affiliate program | Tag: `[sponsored]` — cap at T4 |
| **Competitive** | Source is produced by a competing tool's creator or team | Tag: `[competitor]` — note the competing interest |
| **Outdated** | Source is >3 months old for Claude Code topics (fast-moving) or >6 months for general patterns | Tag: `[dated: YYYY-MM]` — flag for version currency check |
| **No methodology** | Source makes effectiveness claims without describing how they tested | Tag: `[no method]` — cap Evidence at Theoretical |
| **Engagement farming** | Post structure optimized for engagement (listicle, "X things I wish I knew", ragebait) over technical depth | Tag: `[engagement]` — evaluate content not format, but discount T4 to T5 if substance is thin |

## Triangulation Rules

Sources are independent only if they derive from **different primary observations or experiences**. Multiple blog posts citing the same Reddit thread, changelog entry, or Anthropic announcement count as 1 source, not 3. When counting corroborating sources for T3 consensus:

1. Trace each source back to its primary observation
2. Deduplicate — different authors repackaging the same discovery = 1 source
3. Only genuinely independent practitioners who tested the pattern themselves count as separate sources

## Special Rules

1. **Consensus override**: If 3+ independent sources (different authors, different platforms, different primary observations) report the same finding, promote to T3 regardless of individual tiers. This is the strongest community signal.
2. **Recency bonus**: Findings from the last 30 days get a tier boost if they reference the current Claude Code version or a feature released in the last month.
3. **Contradiction handling**: If a finding contradicts the existing community report or ARCHITECTURE.md, flag it as `CONTRADICTION` rather than discarding. Contradictions are high-signal — either the architecture is wrong or the finding is wrong. Present both sides.
4. **"Works for me" discount**: Findings that describe a personal preference without structural reasoning (e.g., "I just like having X") are capped at MEDIUM regardless of authority tier.
5. **Known-source fast-track**: Official docs (code.claude.com), Anthropic blog, and Claude Code CHANGELOG are always T1/Verified/Direct — skip evaluation, go straight to gap analysis.
6. **Stale override**: If any finding in the community report references a Claude Code version older than the current installed version, check the CHANGELOG for whether the behavior was fixed. If fixed, mark `STALE` regardless of original priority.
7. **Self-constraint challenge**: If the skill finds a community recommendation that contradicts one of our self-imposed constraints, present it as a `CHALLENGE` with both the community's reasoning and our architecture's reasoning. Let the user decide.
8. **`tavily_research` confidence cap**: Claims sourced solely from `tavily_research` synthesis without a traceable primary URL are capped at Theoretical evidence and T4 authority. To reach Verified/Observed or T2+, the underlying primary source URL must be identified and verified via `tavily_search` or `tavily_extract`.
9. **Adversarial evidence rule**: If adversarial search (Step 7b) finds counter-evidence from a higher-authority source than the original finding, demote the original by one priority level and tag as `CONTESTED`. Always present both sides.
