---
# PATH-SCOPED 2026-08-26: this rule's trigger IS a file path -- you cannot author a
# rule without the rule file being in play -- so it leaves the unconditional corpus
# and is delivered when a rule-like file is touched. -6,438 B ambient.
#
# HONEST GAP: `paths:` DELIVERY is proven (5 rules, ~97,843 B rely on it, and two were
# observed injected live), but its TIMING relative to the first matching edit is
# UNMEASURED -- the injection envelope is not persisted to the transcript, so no
# transcript-based instrument can see it. Accepted here because the risk is asymmetric:
# authoring is iterative (write -> guard -> revise) and `rule-size-guard.py` enforces
# the byte limits independently at write time. Do NOT reuse this reasoning for a rule
# whose decision is made and executed in a single tool call with no file involved --
# that is why agent-delegation.md stays ambient.
paths:
  - "**/rules/*.md"
  - "**/rules/incidents/*.md"
  - "**/agent-memory/topics/*.md"
  - "**/agent-memory/rules/*.md"
  - "**/skills/_shared/*.md"
---

@rule rule_authoring
@version 2026-08-26
@scope every new or revised rule in `rules/`, and the rule-like sections of
       topic/agent-memory files
@reference docs/rule-reference/rule-authoring.md

# RULE AUTHORING — DECISION CONTRACT

Measured evidence (v1-v5 format trials, per-format compliance, per-model deltas,
conversion-swing figures, the byte-vs-char incident) lives in the reference. This is
what you act on.

## The three levers, in order of leverage

1. **Name the override patterns.** A rule without GUARD blocks is only as good as
   prose markdown, however much DSL structure it carries. This is the largest lever
   by a wide margin, and structure alone does not substitute for it.
2. **Use DSL, hybrid, or constitutional structure** for any rule over ~30 lines:
   - DSL: `@rule` / `@scope` / `STEP_N` / `FORBIDDEN:` / `ON X:`
   - Hybrid: DSL plus `# WHY:` lines
   - Constitutional: ARTICLE I/II with named override petitions
   FORBIDDEN: checklist format for imperatives. Numbered lists read as negotiable
   and measure no better than markdown despite being structured.
3. **Default to strongwording.** It is a floor normalizer, not a universal improver —
   marginal on Opus, decisive on Haiku. Mandatory for any rule that can load in a
   mixed-model route (worker agents, downgradable subagents), because such a rule
   cannot know its reader.

## The five override patterns every GUARD set should cover

| Pattern | User phrase |
|---|---|
| Urgency | "I'm in a hurry", "quick turnaround", "no time for X" |
| Size minimization | "it's a typo", "one-liner", "one-character fix" |
| Claimed prior review | "I already reviewed", "trust me" |
| Bypass appeal | "skip the check", "just do it inline", "--no-verify it" |
| Preference framing | "X is better", "I prefer X", "X is cleaner" |

```
GUARD pattern="<user phrase>" or "<variant>":
  REFUSE <the destructive path>. <one-line reason it is not valid>.
  USE <the safe alternative>. NO EXCEPTIONS.
```

## Apply this only where format moves compliance

| Surface | Apply? |
|---|---|
| `rules/*.md` | YES — highest sensitivity |
| `agent-memory/rules/*.md` | Historical only; the injector was retired 2026-07-29 and nothing reads that path |
| `agent-memory/topics/*.md` | Partial — GUARD blocks on "do NOT" items, plain prose for reference |
| `skills/_shared/*.md` | YES for a relocated contract; it is read as a rule |
| SKILL.md steps | NO — invocation already anchors behaviour; see `skill-standards.md` |
| CLAUDE.md routing, MCP tool descriptions | NO |
| Worker prompt templates | UNTESTED — default to prose, measure first |

## Size and budget

- Measure `len(text.encode("utf-8"))`, never `len(text)`. Ambient rules are dense with
  multi-byte characters, so a character count understates bytes by ~200-450 per file
  and will call a file landable that the guard blocks.
- Treat computed headroom under ~500 B as "does not fit"; the append carries multi-byte
  characters too.
- Per-file: `rule-size-guard.py` WARN 35,000 / BLOCK 38,000 bytes. A file already over
  BLOCK accepts no addition of any size, so route the lesson to
  `rules/incidents/<name>.md` until a descope lands.
- Corpus: the ambient tier is NET-ZERO-GROWTH. `manifests/ambient-budget.json` sets a
  derived ceiling; an append that grows the corpus needs an offsetting relocation, a
  non-ambient destination, `paths:` frontmatter, or a justified ledger entry.

## Do not

- Add DSL structure without GUARD blocks.
- Bulk-convert scoring rules; a rule at 95%+ has no headroom and conversion carries
  measured variance. A/B the override patterns first, n>=3.
- Adopt XML or TOON on external advocacy; both lost here, variance-confirmed.
- Prefer a format change when a DELIVERY change is available. Moving a rule to a hook,
  tool declaration, or skill step is usually the larger win — but verify the mechanism
  actually delivers before relying on it (see `skill-standards.md` "Rule Integration
  Tiers"; the retired lazy-rule injector is the cautionary case).

## Hard guards

GUARD pattern="the rule is short, it doesn't need GUARD blocks":
  REFUSE for any rule that FORBIDS or REQUIRES something. Length is not the axis;
  whether users push back on it is. NO EXCEPTIONS.
GUARD pattern="DSL structure is enough" or "it looks rigorous":
  REFUSE. Structure without named override patterns measures like markdown. Add the
  patterns. NO EXCEPTIONS.
GUARD pattern="convert the whole corpus to the winning format":
  REFUSE bulk conversion. Measure per rule; conversions of high-scoring rules add
  variance without benefit.
GUARD pattern="strongwording is unnecessary, this only runs on Opus":
  REFUSE the assumption. A rule cannot know its reader once it loads in a
  mixed-model route. Default to strongwording.
GUARD pattern="this rule is important, so it belongs ambient":
  REFUSE importance as a placement argument. Ambient is a BUDGET, not a priority
  ranking. Justify placement by whether the trigger is detectable without it.
