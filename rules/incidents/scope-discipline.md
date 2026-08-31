---
paths:
  - "**/rules/scope-discipline.md"
  - "**/rules/incidents/scope-discipline.md"
---

# scope-discipline: Incident Narratives

Extracted from `rules/scope-discipline.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## users-ask-for-results-not-infrastructure-schedule-the-netsuite

```
WHY: users ask for results, not infrastructure. "Schedule the NetSuite
     sync" was the ask. Building a 17-tool MCP server was the detour.
     Infrastructure should emerge from repeated need, not from imagined
     future convenience.
```

## az-cli-python-scripts-could-have-scheduled-the-netsuite

```
WHY: az CLI + Python scripts could have scheduled the NetSuite sync on
     day one. Investing ~3 hours building a dedicated MCP delayed the
     actual delivery by that same amount. The MCP IS valuable — but it
     should have come AFTER shipping the sync, not before.
```

## build-tooling-when-the-pain-is-proven-repeated-not

```
WHY: build tooling when the pain is proven repeated, not anticipated.
     One-off tasks don't justify new tooling. Two similar tasks might.
     Three almost certainly do.
```

## curbs-the-rush-to-build-everything-overengineering-pattern-without

```
WHY: curbs the "rush to build everything" overengineering pattern. Without
     an explicit tag, every plausible-sounding addition reads as worth
     building. The tag forces a triage call BEFORE code exists.
     (citypaul pattern.)
```

## 2026-07-30-airlock-friction-engagement-three-consecutive-user

```
WHY: 2026-07-30 Airlock friction engagement — THREE consecutive user
corrections for one reflex. Asked for low-friction approaches; I bundled
remove-a-broad-path-rule + enable-script-control + expand-enforcement-to-
servers + shorten-OTP into the friction deliverable. Corrected. I then
NAMED the reflex myself, citing the 2026-06-18 KB entry — and one turn
later used freshly-researched ACSC Essential Eight evidence ("script
control is an ML1 requirement") to REINSTATE the same items and closed by
asking the user's target maturity level. User: "I didn't ask for maturity
levels, I asked for low friction approaches." The relevant KB entry
([[engineering-assessment-maturity-and-gap-closing]], "Building more fence
when the ask was a path through the fence") had been surfaced in-context by
a hook mid-session. Knowing the failure mode, and having just articulated
it, did not prevent the third instance — which is why this is now a GUARD
with a per-item mechanical test rather than a FAILURE note to recognise.
```

## 2026-06-19-cloud-paved-roads-a-private-repo

```
WHY: 2026-06-19 cloud-paved-roads — a private repo blocked the target team,
so I built a re-pathed 9-file consumer "kit" in a new repo before discovering
that flipping the SOURCE repo to internal visibility solved access with zero
drift (and the "internals" weren't sensitive, so no content-divergence
justification either). The kit was retired. SECOND instance same session:
the layer-hub was built-then-held as deploy-on-demand. Both are
"change a setting / use existing access" reached past in favor of
"build a thing." See KB topic artifact-distribution-shape.md.
```

## relabeling-lets-infrastructure-bypass-invariant-3

```
WHY: relabeling lets infrastructure bypass invariant 3
(`infrastructure_investment_requires_repeated_friction_evidence`).
"Capability" sounds like user lift; "infrastructure" forces honest
cost/benefit accounting. The first framing has no defense; the
second forces it. See FAILURE shipped_infrastructure_as_capability_no_lift
below.
```

## 2026-04-24-azure-automation-netsuite-sync-user-asked

```
INCIDENT 2026-04-24 Azure Automation NetSuite sync: user asked "can you
connect Claude to Azure Automation to schedule this sync". I built a
17-tool MCP server over ~3 hours before the sync was deployed. The
right first move was az CLI scripts to ship the sync in ~1 hour. The
MCP remains valuable — but it should have been the SECOND deliverable,
unblocked by the user actually needing to iterate on multiple runbooks.
```

## the-naming-still-matters-2026-07-26-began-as

```
WHY the naming still matters: 2026-07-26 began as "what MCPs am I using for
Slack?" and became six PRs across three repos touching authorization policy,
CI gates, and an Entra enterprise app. Every expansion was justified by a real
finding — which is exactly what unchecked accretion feels like from the inside.
Nobody DECIDED to spend the session on the org's Terraform pipeline; it
accumulated one discovery at a time. The fixes were right; the silence was the
defect.
```

## 2026-05-18-example-app-prompt-editor-user-said

```
INCIDENT 2026-05-18 ExampleApp prompt editor: user said
"I want the option to change the prompt. I should also be able to
change the version forward and back." I shipped only the version-
navigation half and framed the save endpoint as needing "explicit
authorization" because the shared dev+prod agent makes saves prod-
affecting. User had to push back ("I asked you to make the agent
system prompt editable and instead you kept it as read-only"); a
follow-up PR (#46) shipped the editor. The directive ALREADY
authorized the save — narrowing it for safety was a unilateral
scope-down, not a safety gate.
```

## 2026-06-27-fp-handling-the-user-agreed-to

```
INCIDENT 2026-06-27 FP-handling: the user agreed to a plan whose option 1 =
"LLM judge auto-suppresses real-time false positives" and option 2 = a
deterministic detector fix. A later brief instruction ("clean up the posted
FPs") COULD map to several mechanisms; I built the human-👎-confirmation
suppression loop (originally option 3, which I'd myself said to DEFER) and
shipped 2 PRs around it — NOT the judge. Worse: my AskUserQuestion "cleanup
posture" choices offered ONLY 👎-variants and never listed "let the judge
auto-suppress" (the standing option 1), so the question itself STEERED the
user off their own plan. The user caught it twice ("I thought we were
implementing a judge"). ~2 PRs of work landed on the wrong mechanism (one
salvageable as a backstop, but not what was asked).
```

## 2026-05-18-eval-harness-synthesis-hooks-a-roundtable

```
INCIDENT 2026-05-18 eval-harness + synthesis hooks: a /roundtable
session re-ranked memory-search work as exhausted; user pushed back
against further "instrumentation" recommendations. I reframed three
options as "capability work" (eval-harness extraction, synthesis
hooks, ExampleApp). User approved all three; I shipped PR #430
(mcp-servers) and PR #913 (claude-config). When the user asked
"did they improve anything?" the honest answer was no:
  - PR #430 is a byte-equivalent refactor; lift requires later
    adapter PRs (PR2-PR4 in DESIGN.md) that no one has scheduled.
  - PR #913's first synthesis entry hasn't even fired yet.
  - ExampleApp declined was the only honest call of the three.
Both PRs are real engineering, but neither is "capability" in the
user-felt sense the bench-vs-capability feedback memory anchored on.
I labeled platform-infrastructure as "capability work" to bypass
the friction-evidence invariant. The cost: $21 roundtable + $1
demo + dev time, with zero measurable current-session lift, and a
forced retraction in the impact-honesty turn.
```

## 2026-07-24-bedrock-invocation-logging-a-one-time

```
INCIDENT 2026-07-24 Bedrock invocation-logging: a one-time bootstrap
(KMS key + S3 bucket + Glue table + logging config) took 6 merged PRs +
~6 failed CI applies, each clearing a distinct blocker (missing
bedrock:*/KMS grant, KMS ARN→policy dependency cycle, the 6,144
managed-PolicySize quota silently rejecting the grant, a
principal-relative KMS key-policy lockout check). ALL of those facts
were ALREADY in the KB (terraform-ci-iam-scoping.md: two-cycle,
tag-at-create, 6144 managed-policy limit; compliance-api-ingestion.md:
"applied locally first with full admin, then merged the CI fix"), and
diagnose-before-fix's cloud_infrastructure_debug STEP_1 already MANDATES
memory_search-before-grinding on KMS/AccessDenied. This was a
rule-ADHERENCE failure (I hold the rule, didn't run it), not a rule gap.
```

## 2026-07-28-task-a2-was-scoped-to-gibraltar

```
WHY: 2026-07-28 — task A2 was scoped to `gibraltar-staging`, but the apply script's
association loop also carried `gibraltar-prod-alb`, a production LB in ANOTHER team's
account (123456789012). Caught by the permission classifier, NOT by my own review, and
the earlier AskUserQuestion consent ("apply the fixes") did not name that target. Same
session, same shape: a general "proceed" was nearly read as authorizing a deployment
gate it never covered. Distinct from silently_narrowed_user_directive_for_safety below
(that WITHHOLDS an authorized action); this WIDENS to an unauthorized one, and the
asymmetry matters — narrowing is recoverable by shipping the rest, widening writes to
a resource nobody approved.
```

## 2026-07-17-example-target-echelon-security-overview-drafted-a

```
WHY: 2026-07-17 ExampleTarget+Echelon security overview — drafted a comprehensive internal-style
doc, then the user revealed piecemeal that it was customer-facing -> positive/high-level ->
~3 pages -> no LLM-style bold -> drop the product brand. ~6 full rewrites, each a constraint
an upfront audience/tone/length/branding question would have surfaced. Distinct from
simple_solution_bias (over-building infra): this is under-scoping the DELIVERABLE SHAPE and
then churning it. Fix: elicit-then-draft, not draft-then-discover.
```
