# Architecture Review Template (Staff Engineer Guide)

Use this template when producing deep architecture assessments of codebases —
whether for `/evaluate-repos` (community repos), `/code-explore` (internal
repos), or any task that requires understanding WHY a system is built the way
it is.

This template is adapted from microsoft/skills `wiki-onboarding` Staff
Engineer Guide format. It focuses on the "why" behind decisions, not just
the "what" that exists.

---

## Report Structure

### 1. Executive Summary

What the system is in one dense paragraph. What it owns vs delegates.
What architectural style it follows (monolith, microservices, event-driven,
hexagonal). What language/framework and why (if apparent from ADRs or docs).

### 2. Core Architectural Insight

The SINGLE most important concept that a staff engineer needs to understand.
What makes this system tick. Not a feature list — the load-bearing abstraction.

### 3. System Architecture Diagram

ASCII or Mermaid `graph TB` showing major components. Call out the "heart"
of the system — the component everything else depends on.

```
[entry point] → [routing/dispatch] → [core domain] → [persistence]
                                   ↘ [external integrations]
```

### 4. Domain Model

Core entities and their relationships. Use a table:

| Entity | Purpose | Key invariants | Enforced by |
|--------|---------|---------------|-------------|
| ... | ... | ... | ... |

### 5. Key Abstractions and Interfaces

The load-bearing abstractions — interfaces, traits, base classes that the
system is built on. For each: what it abstracts, why that boundary exists,
what would break if you changed it.

### 6. Decision Log

The most valuable section for evaluating a repo's practices:

| Decision | Alternatives considered | Rationale | Evidence |
|----------|----------------------|-----------|----------|
| ... | ... | ... | file:line or ADR link |

If the repo has no ADRs, reconstruct decisions from git history, README,
and code patterns. A repo with no documented decisions is a yellow flag.

### 7. Dependency Rationale

| Dependency | Purpose | What it replaced/prevents | Risk if removed |
|-----------|---------|--------------------------|-----------------|
| ... | ... | ... | ... |

### 8. Testing Strategy

What's tested, what isn't, and the testing philosophy:
- Unit test coverage areas
- Integration test approach
- What's explicitly NOT tested and why
- Test infrastructure (frameworks, fixtures, CI integration)

### 9. Known Technical Debt

| Issue | Risk level | Affected files | Impact |
|-------|-----------|----------------|--------|
| ... | ... | ... | ... |

### 10. Security Model

Trust boundaries, auth approach, data sensitivity classification.
Where does the security perimeter live?

### 11. Performance Characteristics

Bottlenecks, scaling limits, hot paths. What breaks first under load?

### 12. Where to Go Deep

Recommended reading order of source files for someone who wants to
understand this system. Not alphabetical — by conceptual dependency.

---

## Usage Notes

- **Dense prose with tables, NOT shallow bullet lists.** Every claim backed
  by a file:line citation or git evidence.
- **Focus on WHY decisions were made**, not just WHAT exists. "They use Redis"
  is inventory. "They use Redis for session caching because their auth flow
  requires sub-10ms lookups and PostgreSQL was adding 40ms p99" is a review.
- **Reconstruct missing rationale from code.** If there's no ADR, the decision
  log should still be filled by reading git blame, commit messages, and
  structural patterns.
- **Flag what's missing.** No tests? No docs? No error handling? Say so.
  Absence is a finding.

(Pattern source: microsoft/skills wiki-onboarding Staff Engineer Guide —
Context7 registry 2026-04-06)
