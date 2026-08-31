# Research Evaluation Framework

Every finding from Phase B is scored on three dimensions. The composite determines whether it's presented and how prominently.

## Dimension 1: Research Rigor

| Tier | Source type | Examples | Trust level |
|------|-----------|----------|-------------|
| **R1 - Peer-reviewed** | Published at top venues (NeurIPS, ICML, ICLR, ACL, EMNLP, AAAI, CHI) or in peer-reviewed journals | Conference proceedings, journal articles with formal review process | Highest. Vetted by domain experts. Claims are scrutinized. |
| **R2 - Institutional preprint** | arXiv papers from established labs (Anthropic, Google DeepMind, Meta FAIR, Microsoft Research, OpenAI, Stanford, Berkeley, CMU, MIT) | arXiv preprints with institutional affiliation, technical reports from major labs | High. Not peer-reviewed but from credible institutions with reputational stakes. |
| **R3 - Industry research blog** | Engineering/research blogs from major AI companies with technical depth, methodology, and reproducible details | Anthropic research blog, Google AI Blog, Meta AI Blog, Microsoft Research Blog, OpenAI blog (technical posts) | High. Curated technical communication, often precedes or accompanies paper releases. |
| **R4 - Independent preprint / framework docs** | arXiv from independent researchers, framework documentation with architecture rationale, well-documented open-source projects | Independent arXiv papers, LangChain/CrewAI/AutoGen architecture docs, technical deep-dives in project repos | Medium. Valuable but needs corroboration. Check citation count and community adoption. |
| **R5 - Conference talk / workshop** | Recorded presentations, workshop papers, tutorial materials, YouTube talks from researchers | NeurIPS workshops, ICML tutorials, PyCon/Strange Loop talks, AI engineer conference talks | Medium. Less rigorous than papers but often contains practical insights not in the paper. |
| **R6 - Opinion / commentary** | Blog posts, Twitter threads, newsletters, podcast discussions about research trends | Individual researcher blogs, AI newsletters, podcast transcripts | Low. Useful for trend detection but not for specific technical claims. Verify primary sources. |

**How to determine tier during search:**
- arXiv: check affiliations in author list. Major lab = R2. Independent = R4. If published at a venue (noted in abstract), promote to R1.
- Blog posts: check domain. `anthropic.com/research`, `ai.googleblog.com`, `ai.meta.com/blog` = R3. Personal blogs = R6.
- Conference: if proceedings are published (e.g., NeurIPS 2025 Proceedings), it's R1. Workshop papers = R5. Talks without papers = R5.
- GitHub: check if the repo accompanies a paper (look for `paper.pdf`, arXiv link in README). If yes, inherit the paper's tier. If standalone, R4.
- Multiple independent papers reaching the same conclusion = automatically promote to R1-equivalent regardless of individual tiers.

## Dimension 2: Evidence Strength

| Grade | Definition | Indicator |
|-------|-----------|-----------|
| **Empirical - Controlled** | Controlled experiments with baselines, ablations, statistical significance, reproducible methodology | "We evaluated on SWE-bench across 500 tasks with 3 runs each. Our method achieves 47.3% vs baseline 31.2% (p < 0.01)." |
| **Empirical - Benchmark** | Evaluated on established benchmarks but without full ablation study or controlled comparisons | "Our agent scores 85% on HumanEval and 72% on MBPP." |
| **Empirical - Case Study** | Real-world deployment with measured outcomes but limited generalizability | "Deployed to our 50-person engineering team for 3 months. Reduced code review time by 30%." |
| **Analytical** | Formal analysis, theoretical framework, or systematic literature review with clear methodology | "We prove that tree-structured reasoning reduces expected tool calls from O(n) to O(log n)." |
| **Observational** | Describes patterns observed in practice without controlled measurement | "We noticed that agents with explicit planning steps tend to make fewer errors." |
| **Speculative** | Extrapolation from related work, theoretical prediction without validation | "Based on scaling laws, we predict that agents with 1M context will exhibit emergent planning capabilities." |

## Dimension 3: Applicability to THIS Architecture

| Score | Definition | Indicators |
|-------|-----------|------------|
| **Direct** | Research addresses a specific component of this architecture: MCP tool integration, persistent agent memory, multi-agent delegation, hook-based routing, Windows deployment, security operations automation | Paper studies MCP-based tool use, agent memory persistence, or multi-agent task routing |
| **Adaptable** | Research uses a different framework but the core pattern transfers with moderate effort. Same structural problem, different implementation. | Paper uses LangChain agents but the orchestration pattern applies to our Task-based delegation |
| **Conceptual** | Research insight is valid but requires significant rethinking to apply. Different scale, different domain, or different abstraction level. | Paper on million-agent simulations - insight about coordination applies but at vastly different scale |
| **Tangential** | Research is in the same broad field but addresses a different problem or uses fundamentally different assumptions | Paper on training-time tool use learning - we don't control model training |
| **Irrelevant** | Different problem entirely, or conclusions don't transfer to prompt-time agent architectures | Paper on model architecture changes, hardware optimization, or pre-training data |

## Composite Priority Matrix

| Priority | Criteria | Action |
|----------|----------|--------|
| **HIGH** | R1-R2 rigor + Empirical (any) evidence + Direct applicability | Present prominently. Identify specific architecture changes. |
| **HIGH** | R3 rigor + Empirical-Controlled evidence + Direct applicability | Institutional blog with strong evidence for this exact setup. Present prominently. |
| **HIGH** | Convergence: 3+ independent papers reaching the same conclusion + Direct/Adaptable applicability | Research consensus. Present as a thread. |
| **MEDIUM** | R2-R3 rigor + Empirical evidence + Adaptable applicability | Needs adaptation but well-supported. Present with transfer path. |
| **MEDIUM** | R4-R5 rigor + Empirical evidence + Direct applicability | Less prestigious source but directly relevant and evidence-backed. Present as lead. |
| **MEDIUM** | Any rigor + Any evidence + CONTRADICTION of existing architecture choice | Contradictions are always worth presenting regardless of source quality. |
| **LOW** | R4-R6 rigor + Observational/Speculative + Adaptable/Conceptual | Interesting but not actionable yet. Research Radar section. |
| **DISCARD** | R6 + Speculative + Tangential/Irrelevant | No value for this architecture. |

## Research Bias Indicators

Flag these bias risks when evaluating research sources. Sources with bias tags are NOT automatically discarded - the bias is noted alongside the finding so the user can weigh it.

| Bias type | Indicator | How to flag |
|---|---|---|
| **Institutional promotion** | Paper/blog primarily showcases the author's lab's own model, framework, or product without independent comparison | Tag: `[self-promote]` - cap at R3 unless independently replicated by another lab |
| **Industry-funded** | Research funded by a company with commercial interest in the outcome, or authors have undisclosed industry affiliations | Tag: `[funded]` - note the funder, evaluate methodology more strictly |
| **Competitive framing** | Paper explicitly compares against a competing approach and the authors have ties to the "winning" approach | Tag: `[competitive]` - verify the comparison methodology and baseline fairness |
| **Outdated** | Paper >12 months old for fast-moving topics (agent architectures, tool use, MCP) or >24 months for established theory | Tag: `[dated: YYYY-MM]` - check for superseding work before citing |
| **Weak methodology** | Claims effectiveness without controlled experiments, ablation studies, or statistical significance testing | Tag: `[weak method]` - cap Evidence at Observational |
| **Hype-driven** | Press-release-style paper, demo without rigorous evaluation, or claims that significantly exceed what the methodology supports | Tag: `[hype]` - evaluate the methodology section independently of the abstract's claims |
| **Benchmark gaming** | Results optimized for specific benchmarks in ways that may not generalize (e.g., training on test-set-adjacent data, cherry-picked examples, leaderboard-focused ablations) | Tag: `[benchmark]` - check if evaluation includes held-out or real-world tasks beyond the target benchmark |

## Special Rules

1. **Convergence override**: If 3+ independent research groups (different institutions) reach the same conclusion, promote to HIGH regardless of individual tiers. Independent convergence is the strongest research signal.
2. **Recency bonus**: Papers from the last 6 months get a half-tier boost. The research frontier moves fast - recent work has access to current model capabilities.
3. **Anthropic priority**: Any research from Anthropic (papers, blog posts, documentation updates) about Claude, MCP, or agent architectures gets automatic R2+ classification and should be evaluated first. They define the platform we build on.
4. **Benchmark skepticism**: High benchmark scores alone don't indicate applicability. Always check methodology - was it evaluated on tasks similar to ours (security ops, multi-tool orchestration, Windows deployment)?
5. **Framework hype discount**: New framework announcements (v0.1, "alpha", "experimental") are capped at MEDIUM regardless of institutional backing. Wait for adoption evidence or second-version refinement.
6. **Replication signal**: If a finding has been replicated by independent groups, promote by one tier. If a finding has failed replication attempts, demote to LOW with a note.
7. **Contradiction escalation**: If research contradicts an existing architecture decision, present it as a `CHALLENGE` with the research's evidence alongside the architecture's rationale. Never auto-resolve - let the user decide.
8. **Transfer path required**: Every HIGH/MEDIUM finding MUST include a specific transfer path - how to adapt the research insight to this architecture. Findings without a clear transfer path are demoted to LOW (interesting but not actionable).
