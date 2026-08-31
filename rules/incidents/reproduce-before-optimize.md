---
paths:
  - "**/rules/reproduce-before-optimize.md"
  - "**/rules/incidents/reproduce-before-optimize.md"
---

# reproduce-before-optimize: Incident Narratives

Extracted from `rules/reproduce-before-optimize.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## on-an-empirical-task-the-output-is-a-measured

```
WHY: on an empirical task the output is a measured metric. An analysis that is not anchored
     to a reproduced number is a HYPOTHESIS, not a result — and hypotheses presented as
     diagnoses drive flip-flopping (each new one replaces the last) because nothing is
     falsifiable. A reproduced number is the ground truth that kills bad theories on contact.
```

## when-a-reference-is-known-to-achieve-the-metric

```
WHY: when a reference is known to achieve the metric, running it verbatim (a) confirms your
     environment reproduces it, (b) yields the working baseline you optimize FROM, and (c)
     lets you DIFF your version against a thing that works. Reconstructing/decoding instead
     diverges SILENTLY — the JED decode was 10 lines vs an 80KB engine and looked "close".
```

## i-read-decoded-the-winning-notebook-is-not-i

```
WHY: "I read/decoded the winning notebook" is not "I ran it and got the number". Reading
     gives you the IDEA; it does not surface the machinery, constants, and edge-handling that
     make the idea actually hit the metric. Only execution does.
```

## competition-submissions-paid-eval-runs-and-deploys-are-the

```
WHY: competition submissions, paid eval runs, and deploys are the resources most tempting to
     spend "to learn". Every one so spent on a guess is gone. Spend them only on (a) a
     replication of a known-working method, or (b) a candidate validated cheaply first.
```

## jed-i-wrote-don-t-blind-n-size-to

```
WHY: JED — I wrote "don't blind-N, size to budget" and blind-N'd the very next submission.
     A conclusion that does not constrain the immediately-following action was never
     internalized. Before the next action, check it against the diagnosis just made.
```
