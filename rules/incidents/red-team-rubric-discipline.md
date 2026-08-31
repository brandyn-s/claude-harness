---
paths:
  - "**/rules/red-team-rubric-discipline.md"
  - "**/rules/incidents/red-team-rubric-discipline.md"
---

# red-team-rubric-discipline: Incident Narratives

Extracted from `rules/red-team-rubric-discipline.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## severity-is-implicitly-graded-against-an-optimization-target

```
WHY: severity is implicitly graded against an optimization target.
     If the target is unstated, you'll grade against the most salient
     one and apply that severity to fixes that may damage the OTHER
     goals the artifact serves. 2026-04-30 /persona incident: graded
     against rubric-mode validity criteria, applied to discovery-mode
     fixes; user pushback ("would jeopardize the creativity I saw")
     revealed half the findings would actively damage what the skill
     was for.
```

## a-multi-mode-artifact-has-different-success-criteria-per

```
WHY: a multi-mode artifact has different success criteria per mode.
     A finding that is HIGH severity for one mode may be LOW severity
     or NOT-A-FINDING for another. Without classification, you grade
     against the wrong rubric for half the findings.
```

## implicit-evaluation-criteria-are-the-parent-failure-mode-behind

```
WHY: implicit evaluation criteria are the parent failure mode behind
     three separate documented incidents (2026-04-05 softening bias,
     2026-04-19 sbom-rs over-rejection, 2026-04-30 /persona severity-
     rubric mismatch). Each was a different specific failure mode of
     leaving the framework implicit. The fix in all three: state the
     framework before applying it.
```

## 2026-07-30-airlock-five-instances-one-session-both

```
WHY: 2026-07-30 Airlock — five instances, one session, both directions.
(a) Populations inferred from policy-group NAMES; measurement inverted the
    ranking, then measuring one level deeper inverted it again (603 blocks
    but blocked_unique=4 — 597 from ONE host in a retry loop, so the
    per-endpoint "worst by 4x" was a mean over a single outlier).
(b) "Blocklist hits are not friction, that's policy working" written into an
    include/exclude table with instructions to filter by type — using list
    membership to classify events makes any config error unfindable. Measured
    refutation: NordVPN's publisher is TRUSTED while Mullvad is BLOCKED, and
    ~60 trusted publishers carry invalid signature chains including one named
    "Code Sign Test (DO NOT TRUST)". The lists do not encode coherent intent.
(c) The SAME assumption inverted: recommended trusting publisher OpenVPN Inc.
    as "39% of blocks, zero risk" — assuming a BLOCK means friction. Zero
    OpenVPN allowlist among 130 fleet-wide while three other tunnel products
    are allowlisted; likely unsanctioned, i.e. the control working.
(d) A "zero new trust required" fix whose premise was refuted by its own
    verification step (hash was in NO allowlist). The caveat fired and saved
    a no-op write that would have been reported as a 98.8% fix — this is the
    POSITIVE control: the mechanism that works is naming the check and running
    it before acting.
(e) A hard PRECONDITION attached to a plan on a premise the same session's
    own data refuted (otp_total was nonzero with the setting OFF), which put
    a production setting into a live group on a false rationale.
```

## 2026-04-30-persona-red-team-graded-against-falsifiability

```
INCIDENT 2026-04-30 /persona red-team: graded against falsifiability
/ measurement-validity rubric. Listed 14 findings as HIGH/MEDIUM/LOW.
User asked "what are you optimizing for?" — revealed implicit rubric
was rubric-mode-only criteria. Half the findings (B, C, D, L, E)
would have damaged discovery-mode wildness. Surgical fix: classify
findings by mode, re-grade, identify the four that survive.
```

## 2026-04-05-absorb-v3-red-team-14-6

```
INCIDENT 2026-04-05 absorb v3 red-team: 14 → 6 deferred for "lack of
evidence." User challenged 3; all 3 flipped to IMPLEMENT. Implicit
framework: "no incident = defer." Explicit framework would have
surfaced that absence-of-incidents is not evidence.
```

## 2026-04-19-sbom-rs-cdx-1-7-red

```
INCIDENT 2026-04-19 sbom-rs CDX 1.7: red-team rejected 7/7 IMPLEMENTs
as additive (additive doesn't need full red-team per compare-by-need).
Implicit framework: "additive = trivially low cost = always implement"
got applied as "additive = trivially low importance = always reject."
The change-type classification was implicit, not explicit.
```

## 2026-06-12-csod-assessment-shipped-kb-report-pr

```
INCIDENT 2026-06-12 CSOD assessment (shipped KB report PR #798): graded the
over-scoped OAuth credential HIGH and asserted it "can rewrite the directory
+ mint API keys" from the OBSERVED granted scope alone. Vendor docs showed a
TWO-GATE model (OAuth scope AND the backing user's security-role permission;
401 if either missing) so granted-scope != exercisable-capability, and
`bulkapikey` = Edge Import PGP keys, not API credentials. Both over-claims
reached a shipped artifact; only a later doc review caught them.
Exploitability was never tested (read-only probe couldn't; several endpoints
already 401'd) yet was published as fact.
```
