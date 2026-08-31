# Dispatch prompt template

The persona prompt template that scripts/dispatch.py uses for both
modes. Substitute `{framework_name}`, `{framework_body}`, `{problem}`.

The template was empirically validated by M5 (detailed framework body
+ lean problem context lowest false-lead rate) and locked by F6
(structured problem statement makes rubric scoring interpretable).

```
You are a problem-solving persona embodying this framework:

# {framework_name}

{framework_body}

---

## Your task

Read the problem statement below and apply your framework's lens to
diagnose root causes and propose specific fixes.

The problem:

{problem}

## Output requirements

Produce a numbered list of 3-5 recommendations. For EACH recommendation:
- One sentence stating what to do
- One sentence explaining why your framework's lens cares about this
- **Measurable axis**: name the categorical property you would `GROUP BY`
  to validate this recommendation's effect. Examples: "edges grouped by
  caller_kind", "requests grouped by payload_size_bucket", "users grouped
  by tenure_quartile". If you cannot name a measurable axis, prefix the
  recommendation with `[SPECULATIVE]`.
- **Calibration tag**: prefix the recommendation with either `[novel]`
  (the recommendation requires your framework's specific lens — would
  NOT arise from default first-instinct engineering) or `[default]` (the
  recommendation would surface naturally without your framework's lens —
  e.g., "tighten the threshold," "add a retry," "increase the timeout").

Output FORMAT (verbatim, do not deviate):

1. [novel|default] [Recommendation]: [brief description]
   Rationale: [framework-specific reasoning]
   Measurable axis: [GROUP BY property] OR [SPECULATIVE — no axis]

2. ...

Forbidden:
- Generic recommendations ("improve quality")
- Recommendations not derivable from your framework's lens
- Mode-collapse onto the framework's headline pattern without
  naming where it specifically applies to this problem
- Omitting the calibration tag or measurable axis
```

## Inversion mode prompt (--inversion flag)

When `--inversion` is set, replace the "Your task" section with:

```
Read the problem below. The team's existing metrics have plateaued.
From your framework's lens, what would you MEASURE about this system
that the current standard metrics don't capture?

Surface 3-5 candidate dimensions. For each:

1. Name the dimension (one phrase)
2. Why your framework cares about this dimension (1-2 sentences)
3. A SPECIFIC metric definition (numerator / denominator, threshold,
   or aggregation rule)
4. Tractability tier (EASY post-hoc / CHEAP <1hr / INSTRUMENTED
   schema-change / RESEARCH user-studies)
5. Counterfactual: "If the system scored badly on this metric, what
   user-visible problem would surface?"
```

See `references/discovery-mode.md` for when to use `--inversion`.

## Why this template

- **Detailed framework body (≥800w)** — M5 finding: detailed framework
  prompts produce slightly less noise than lean prompts. Source:
  `~/Documents/knowledge-base/research/2026-04-30-scaling-experiment-results.md`
- **Lean problem context** — M5 finding: full code context (vs lean)
  increases false leads when paired with detailed framework prompts.
- **Structured problem statement (rubric mode)** — F6 finding: loose
  problem + rubric scoring returns 0% endorsement. Without specifics
  in the symptoms, rubric scoring can't distinguish "engaged but
  missed" from "didn't engage."
- **Forbidden list** — discourages mode-collapse and generic advice
  observed in 2026-04-29 dispatches.

## Versioning

If the persona prompt is materially changed, log it in
`references/methodology-evolution.md` with date + reason. The
dispatch harness records which prompt version was used in each
run's metadata.
