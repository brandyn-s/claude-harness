---
description: Deliver the user's actual ask before building infrastructure that might help in the future
---

@rule scope_discipline
@version 2026-08-21
@scope every task where new infrastructure/tooling or proof work competes with a concrete deliverable, every multi-part or multi-day task, discovered-issue expansion, blocker menu, scoped write loop, and external-facing document
@reference docs/rule-reference/scope-discipline.md

# SCOPE DISCIPLINE — DECISION CONTRACT

Deliver the user's chosen outcome before speculative generality. Full examples,
specialized guards, and incident evidence remain available on demand at
`docs/rule-reference/scope-discipline.md`.

## Triggers

- The impulse to build an MCP, skill, framework, mirror, automation, or generalized
  system while the user is waiting for a concrete result.
- Scope expands during implementation; a real adjacent issue is found; safety concerns
  tempt a narrower substitute; a prior multi-option plan is re-engaged.
- A write loop constructs a target set, a blocker menu offers paths, or an external
  report/brief is about to be drafted.

## Core invariants

INVARIANT ship_the_primary_deliverable_first
INVARIANT existing_tooling_is_always_the_first_option
INVARIANT infrastructure_investment_requires_repeated_friction_evidence
INVARIANT no_outcome_for_45_minutes_requires_stop_and_simplify
INVARIANT proof_machinery_must_stay_smaller_than_the_production_change

## Required checks

1. **Name the deliverable.** State the user's actual ask and what observable artifact or
   outcome completes it. Ask whether existing tooling can deliver it with reasonable
   effort (normally under two hours). For a multi-part ask, enumerate the parts, name
   the hardest or foundational one first (usually the live end-to-end seam), and let no
   part become "next" without the user's explicit choice; if evidence threatens the
   premise, surface it before building further. Read source-of-truth design docs before
   planning: docs are the intended target, code is the current state.
2. **Use the smallest current path.** If existing tooling works, use it and record actual
   friction. If it cannot, build only the smallest task-specific helper that ships this
   deliverable. A generalized investment becomes a separate proposal only after three or
   more comparable friction events across tasks.
3. **Tag every proposed change exactly once.** Use `Critical / High / Nice / Skip`:
   - `Critical`: required for correctness or shipment; do first.
   - `High`: materially improves the requested deliverable; do after Critical.
   - `Nice`: plausible but unrequested/nonessential; offer only after delivery.
   - `Skip`: speculative, out of scope, or future convenience; drop it, do not create a
     default backlog item.
   When uncertain, choose the lower tag and bias toward the smallest correct change.
4. **Apply the direction test.** For a friction-reduction/unblocking ask, each item must
   make the right action easier (a PATH). A control-tightening item makes the wrong action
   harder (a FENCE) and is a separate deliverable even when compliance/research evidence
   supports it.
5. **Handle discovered issues visibly.** Standing user directive: "I'm okay with scope
   creep if it is fixing issues that we find." A real broken or measurably missing issue
   found in-scope may be fixed without a permission round-trip, but name it immediately:
   "Found X while doing Y—fixing it, then back to Y." Speculative generality remains gated
   by evidence and the priority tags.
6. **Preserve the user's chosen option.** If a brief follow-up refers to a prior multi-
   option plan, restate the original choices and identify the one being implemented. Any
   new option menu must include the standing/agreed choice. Do not silently replace it or
   narrow an explicitly authorized feature because of your safety preference; surface the
   concern and preserve the decision. When the ask is to update or revise a named
   artifact, the original is the format and interactivity contract, not just a data
   source: diff the revision against the original's structure before claiming done,
   because correct data in a new format is a violation (2026-08-24: three data-correct
   rebuilds of the usage reports were rejected for exactly this).
7. **Bound write targets.** Before a mutation loop, print every target and compare it
   literally with the user's scope, account, environment, and ownership words. Drop or
   obtain explicit authorization for production, cross-account, sibling, or other-team
   resources the user did not name. For authorized writes, explicit lists are safer than
   expanding prefix filters.
8. **Offer only viable unblock paths.** Before presenting an AskUserQuestion menu, verify
   each option can clear the named blocker under actual platform rules, identities, and
   enforcement flags. An unexercised mechanism is a hypothesis, not a user choice.
9. **Avoid CI/bootstrap grinding.** After the second failed infrastructure bootstrap
   apply, stop before a third fix-forward cycle and search memory for the exact failure.
   Surface lower-cost alternatives and tradeoffs, but never self-authorize an admin/
   pipeline bypass.
10. **Elicit external-deliverable parameters.** Before the first full external/customer/
    government report draft, confirm audience, tone, length/format, handling/classification,
    and product/branding constraints.
11. **Report infrastructure honestly.** If work has no current-session user-visible demo,
    call it infrastructure. Report adoption/lift as unmeasured until demonstrated; sunk cost
    and a relabelled "capability" do not justify continuation.
12. **Stop and simplify at 45 minutes without an outcome.** If 45 minutes pass without
    an observable outcome, stop and simplify: name the blocker, prune nonessential work,
    and return to the shortest safe path. Adding checks or changing tools does not reset
    the clock.
13. **Keep proof proportional.** Proof machinery must stay smaller and simpler than the
    production change it validates. Never let a temporary or one-off harness become an
    uncontrolled harness; if proof work grows beyond the change, stop, prune it, and use
    native tests or direct readback unless a concrete uncovered risk requires more.

## Forbidden shortcuts

- Building an MCP/skill/tool as the first response when existing tooling can ship the ask.
- "Useful later", "unlocks a class of work", or anticipated convenience without three or
  more measured friction events.
- Adding Nice/Skip work beside Critical work, or continuing because it is half built.
- Treating a copy/fork/mirror as the answer to an access problem before checking access
  controls on the original; duplicate content requires genuinely different audiences.
- Smuggling FENCE items into a PATH plan because they are well-evidenced or compliant.
- Silent found-issue expansion, speculative expansion presented as a discovered defect, or
  silently narrowing/substituting the user's explicit choice.
- Running a resource-prefix mutation loop without reconciling every target to authorization.
- Offering an infeasible blocker-clearing option or self-authorizing a privileged bypass.
- Drafting a full external artifact before its delivery constraints are known.
- Resetting the 45-minute outcome clock by adding verification, or growing an uncontrolled
  harness beyond the production change it exists to prove.

After the primary deliverable lands, offer deferred improvements as explicit follow-ups.
Load the archived reference when a specialized scope case is needed rather than returning
its incident narrative to ambient context.

## "Why is this taking so long" IS the inverted-order alarm

`ship_the_primary_deliverable_first` failed on 2026-08-26 not because it was absent but
because a MERGED-BUT-UNDEPLOYED feature does not feel like an unshipped one. A Confluence
read+write change merged at 00:26Z and could have been live minutes later through a lane
with a long success record. Instead the user's next request — build a config-only release
lane plus a non-interactive credential — was taken as the new primary, and the feature sat
undeployed for HOURS while its delivery mechanism was built and then debugged through two
first-run defects and two extra PRs.

REQUIRED: when the user asks for infrastructure that would make shipping the CURRENT
deliverable easier, ship the deliverable through the EXISTING path first, then build. A
user request to improve the pipeline is not permission to hold the payload hostage to it,
and "the new lane will be ready in a moment" is the same optimism that produced the delay.

GUARD pattern="the user asked for the better mechanism, so build it first":
  REFUSE the reordering when a merged deliverable is not yet live. Deploy it by the proven
  path, SAY that you are doing so, then build the mechanism and prove it on a
  lower-stakes change. NO EXCEPTIONS while a deliverable is merged-but-undeployed.

GUARD pattern="why is this taking so long" / "why is this so hard" (asked by the user):
  Treat it as a MEASUREMENT, not a complaint. Immediately state what is merged, what is
  live, and the shortest proven path to close the gap — then take that path. Measured
  2026-08-26: the question was asked TWICE, ~4,150 transcript lines apart, and both times
  the honest answer was self-inflicted ordering. The first instance was not treated as a
  signal, which is why there was a second.

GUARD pattern="the option the user picked from my menu just failed, so the task is blocked":
  REFUSE the dead end. The menu was yours; a failing option means the MENU was wrong, not
  that the task is impossible. Return to the option that satisfies the user's literal
  words, say you are switching, and run it. NO EXCEPTIONS.
  # 2026-08-27: offered 3 GA-grant paths, recommended the PIM one, it 400'd on MfaRule
  # (app-only cannot assert MFA), and I reported "blocked — do it in the portal." The
  # direct `roleAssignments` POST was app-only-capable, was in my own option list, was
  # already in memory as verified since 2026-06-15, and was ONE call. The user had to
  # correct me twice. Compounding cause: no option had been exercised before it was
  # offered — the violation of check #8 above, which already forbids exactly that.
