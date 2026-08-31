# rule-authoring: Empirical Reference

Extracted from `rules/rule-authoring.md` on 2026-08-26. The ambient rule keeps the
DECISION (which lever, which format, which surfaces, how to measure size); this file
keeps the EVIDENCE that justifies it. Read this when you need the numbers, are
challenging the hierarchy, or are designing a format A/B.

Source: the v1-v5 rule-format trials, 2026-04-17 through 2026-04-19. The historic
harness directory (`~/Documents/format-eval/`) is no longer maintained, so these
figures cannot currently be re-derived — treat them as a dated measurement, not a
standing benchmark.

## Lever 1 — override-pattern naming: the measured spread

Under 12-turn adversarial pressure:

| format | compliance |
|---|---|
| Constitutional | ~99% |
| Hybrid DSL | ~99% |
| Markdown (prose) | 86% |
| Checklist | ties markdown, despite being structured |

The load-bearing interpretation: **the delta is not format — it is whether the rule
names the patterns users actually use to override it.** Checklist format is the
control that proves this. It is structured and still loses, because numbered
imperatives read as negotiable rather than because they lack DSL keywords.

Consequence: DSL structure added WITHOUT GUARD blocks scores like markdown. The
structure is not what buys compliance; the named override patterns are.

## Lever 2 — structure, given guards are present

DSL / hybrid / constitutional outperform prose markdown by:

- **~5-13 pp on Opus**
- **~31 pp on Haiku**

Applies to rules longer than roughly 30 lines. Below that, structure has little room
to matter.

## Lever 3 — strongwording is a floor normalizer, not a universal improver

| model | delta vs markdown |
|---|---|
| Opus 4.7 | +4 pp — marginal |
| Sonnet 4.6 | ~0 pp — ceiling-bound |
| Haiku 4.5 | **+31 pp** — baseline collapses to ~60% without guards |

This is why the ambient rule says "when in doubt, write strongwording": the adoption
cost is low and the floor-normalization benefit is large precisely when you are wrong
about which model will read the rule. A rule that loads in a mixed-model route (worker
agents that may run on Haiku, subagents that may downgrade) has no reliable way to
know its reader.

## Conversions are risk-bearing

The v1-v5 trials measured **~7-9 pp swings per format change**. A rule already
scoring 95%+ has no headroom, so converting it adds variance without benefit.

Before converting an established rule: run an A/B on its representative override
patterns and gather **n>=3 evals** before committing. Spot-check rather than
bulk-convert.

## Rejected formats

**XML and TOON both lost to markdown/strongwording** in our adversarial tests,
variance-confirmed — despite industry claims to the contrary. Do not adopt either for
Claude on the strength of external advocacy.

## Byte-vs-character measurement: the incident

`hooks/rule-size-guard.py` thresholds are **byte** lengths. Ambient rules here are
dense with multi-byte UTF-8 (em-dashes, `→`, box-drawing `─` in section banners), so a
`len(text)` character count understates the real figure by roughly **200-450 bytes per
file** at current sizes.

Measured 2026-07-31 — a char-based headroom check reported files as landable that the
guard would block:

| file | chars | bytes | guard verdict |
|---|---|---|---|
| `check-before-change.md` | 38,859 | 39,268 | OVER BLOCK |
| `diagnose-before-fix.md` | 37,795 | **38,240** | OVER BLOCK (char count said WARN with 205 "headroom") |
| `git-hygiene.md` | 37,440 | 37,788 | WARN, 212 B headroom |

`diagnose-before-fix.md` is the instructive row: the character count said WARN with
205 bytes of apparent headroom, while the byte count was already past BLOCK.

This is also why the ambient rule treats computed headroom under ~500 B as "does not
fit": the append itself carries multi-byte characters, so the margin it consumes is
larger than its character count suggests.

## Surface sensitivity — the reasoning

The rule-format effect is specific to **rule-like surfaces where the model must act
without prior priming**. Scoped workflows do not benefit because skill invocation
already anchors behaviour — the model has been told what task it is performing, which
is the priming a rule has to manufacture for itself.

`Worker prompt templates` remain **UNTESTED**. That is an honest gap, not an implied
"probably fine": default to prose and measure before investing in a format change
there.
