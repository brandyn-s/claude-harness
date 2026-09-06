# Skill listing decisions

The skill listing — `name: description + when_to_use` for every model-visible
skill, each cut at 1,536 characters — is what the model routes on. It has a
budget: `skillListingBudgetFraction` is 0.03, so 6,000 tokens on a 200K-context
model, and Claude Code truncates the listing past it. Truncation is silent, and it
is alphabetical: the skills at the end of the alphabet stop being routable first.
README §Author-workstation profile has called the listing "3.1× oversubscribed"
since 2026-09-03. This document records what was measured about which skills are
actually used, and the decisions that follow.

## What was measured

`bin/skill-usage-report.py` over 3,403 transcripts (933 sessions, 2026-07-02 →
2026-09-06, the author's complete backup), counting two invocation signals per
skill — a `/name` slash command in a user turn, and a `Skill` tool call with that
name — plus the sessions each skill appeared in.

| finding | number |
|---|---|
| skills in the tree | 82 |
| skills invoked at least once in 66 days | 37 |
| skills never invoked | 45 |
| of the 45: members of a parameterisable family (`gather-*`, `scout*`, `superplan-*`) | 6 |
| of the 45: standalone | 39 (one, `frame`, shipped on the last day and has no window) |
| skills invoked only by slash command, never auto-routed | 9 |
| listing today, chars/4 proxy | 12,032 tokens |
| the same listing measured with `count_tokens` on 2026-09-03 | 18,687 tokens (so the proxy reads ×1.55 low) |
| budget | 6,000 measured ≈ 3,870 proxy |

The top of the table is where the work is: `retro` 677 invocations, `distill` 327,
`capture` 283, `ship` 175, `garden` 115, `mega-distill` 89, `pr-fix` 65,
`superplan` 49, `mega-capture` 44, `gather-claude` 32. Every one of the first six
was already `name-only` — they are invoked by name, by `/retro`'s chain, or by a
launchd schedule, and their descriptions were never what routed them.

What the listing costs after each decision (proxy tokens; multiply by 1.55 for the
measured scale):

| step | listed skills | listing (proxy) | × budget |
|---|---|---|---|
| today (8 name-only) | 74 | 12,032 | 3.1× |
| + the 9 slash-only skills → name-only | 65 | 10,906 | 2.8× |
| + the 6 unused family members → name-only | 59 | 9,854 | 2.5× |
| + the 38 unused standalone skills → name-only | 18 | 3,701 | 0.96× |

The listing fits the budget only at the last row. Marking family members
name-only is the right cut and it is not enough on its own; the truncation is
made by the 38 skills nobody invoked in 66 days.

## Decisions

**D1 — slash-only skills are name-only (applied).** `audit-architecture`,
`audit-fix`, `audit-rules`, `gather-claude`, `gather-intel`,
`gather-openai-endpoints`, `gather-research`, `gather-vendor`, `threat-model` were
invoked 1–32 times, always by their name, never by the router. A description the
router never used costs listing space and routes nothing. Slash invocation is
unaffected by `name-only`.

**D2 — unused family members are name-only (applied).** `gather-repos`, `scout`,
`scout-frontier`, `scout-skills`, `superplan-loop`, `superplan-status`: zero
invocations, and each family keeps its most-used member listed (`gather-claude-
endpoints`, `supergoal`; the `scout` family has no used member and is listed by
none). The family stays installable and invocable; it stops competing for the
router's attention.

**D3 — the 38 unused standalone skills: name-only is proposed, deletion is the
question.** `bin/skill-usage-report.py` prints them under "standalone (not
proposed)". Zero invocations in 66 days of daily use is the strongest signal
`docs/skill-cap-decisions.md` accepts for a skill's disposition, and it points at
deletion, not at hiding — a skill that is never routed to and never called is
carrying test, manifest and bundle weight for nothing. That is a per-skill call
(some are bundle members that make sense for a different operator; some are
scaffolding for skills that were never finished) and is not made here. Until it
is, the listing stays 2.5× over budget with D1 + D2 applied, and a 200K session
will not be able to route to skills late in the alphabet. On a 1M-context model
none of this bites.

**D4 — `frame` stays listed.** It shipped 2026-09-06 and is the one skill whose
purpose is to be auto-routed (a substantive ask with no `INTENT.md` should reach
it). It gets a window before it is judged.

**D5 — the measurement is the policy.** A skill earns its listing by being
auto-routed to; a skill invoked by name does not need one; a skill invoked by
nobody does not need to exist. Re-run
`bin/skill-usage-report.py --root ~/claude-transcript-backups/<date> --since <60 days ago> --propose-overrides`
before adding a skill to the listing and once a quarter; the proposal it prints
is D2 applied to the current window.

## What this did not decide

- Parameterising a family into one skill (`gather <target>`) rather than hiding
  its members. The usage numbers say the family's members other than one are not
  invoked; whether the one should absorb the others is a design change with its
  own eval (`scripts/test_skill_description_eval.py` routes a corpus against the
  listing and would show whether a merged description still routes).
- Raising `skillListingBudgetFraction`. It moves the truncation point, at the
  price of ambient tokens on every prompt; the ratchet plan's whole direction is
  the other way.
