# Anti-Patterns This Skill Prevents

15 documented anti-patterns and their counter-mechanisms.

## Evaluation discipline

- **Over-evaluation** — 3-phase framework on 5-line additive changes. Counter: classify by risk, act proportionally.
- **Incident-evidence gates on low-risk changes** — required friction history for additive patterns. Counter: additive changes skip evidence gates.
- **Feature-list comparison** — "they have X, we don't" without checking if gap matters. Counter: Step 3 asks "does our skill achieve the same outcome?"

## Rejection / verification bias

- **Rejection bias** — "our skill covers this" without reading either skill. Counter: side-by-side read in Step 3 + Step 3.5 quorum.
- **Asymmetric evidentiary burden** — SKIP verdict trusted without same scrutiny as ADOPT. Counter: Step 3.5 dispatches to 2 external models; flips on disagreement.
- **Single-surface quorum** — Step 3.5 anchored on OUR SKILL only. Counter: verify_skip.py v2 takes architecture-wide `--ours` (repeatable).

## Extraction quality

- **Editorial-polish bias** — extracting only visual artifact (matrix/table) collapses real techniques into SKILL.md prose. Counter: Step 2.7 technique card before Step 3; Step 4 Domain Insight bucket.
- **Single-author technique extraction** — reader's framing biases the card. Counter: Step 2.7 mandatory 3rd-party GPT card; field-by-field divergences escalate.
- **Silent bias recurrence** — session with 100% SKILL.md adoptions could be regressing. Counter: Step 5.5 Session Output Audit fires at ≥3 SKILL.md-only adoptions.

## Classification accuracy

- **Hook misclassified as Behavioral** — routing conflates skill execution change with all-session enforcement. Counter: Step 4 Hook bucket distinct; mirrors /distill T0-hook staging.
- **Executable methodology trapped in prose** — Domain Insight prose-only loses the HOW. Counter: Step 4 Domain Insight (Harness) produces topic + script in same PR.

## Process discipline

- **Subagent trust** — agent findings as verified fact. Counter: Step 2 read SKILL.md yourself.
- **Premature narrowing** — locked onto 9 items, ignored 254. Counter: Step 0 searches 8+ categories.
- **False saturation** — "exhausted" after each strategy once. Counter: rotate strategies; stop only after 3+ creative variations across 2+ strategies return nothing new.
- **Table-only presentation** — terse table, then file edits. Counter: mandatory narrative per finding before edits.
