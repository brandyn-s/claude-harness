# Evals

Use these with the `scripts/run-skill-evals.py` eval harness to measure skill
output quality before and after changes.

## Eval 1: Monthly community refresh
**Prompt**: `/gather-intel`
**Grade on**:
1. Did Phase A audit existing intel before Phase B? (yes/no)
2. Were community questions decomposed dynamically? (yes/no)
3. Did adversarial search fire for HIGH-priority findings? (yes/no)
4. Were sources evaluated with the Source Evaluation Framework? (yes/no)
5. Did the report include all 4 sections? (yes/no)

## Eval 2: Focused technique search
**Prompt**: `/gather-intel hooks`
**Grade on**:
1. Were ALL searches narrowed to hooks? (yes/no)
2. Were non-hooks results filtered out? (yes/no)
3. Were findings cross-referenced against existing hooks implementation? (yes/no)

## Eval 3: Cross-reference with research
**Prompt**: `/gather-intel` (after `/gather-research` ran in same session)
**Grade on**:
1. Was the research report consumed for cross-reference? (yes/no)
2. Were community findings tagged `[research-validated]` where applicable? (yes/no)
3. Were baseline files 1,4,5,6,7,8 skipped (already in context)? (yes/no)
