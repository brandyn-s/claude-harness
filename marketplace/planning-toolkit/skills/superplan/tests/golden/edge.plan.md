# Plan: Edge-minimal supergoal handoff

Demo: parse_plan.py accepts this fixture with only the required trio present

The smallest shape the parser contract allows: a Demo line, a Falsifiers H2
section with at least one list item, and a fenced command block under the
legacy Verification H2 heading (no Metric Commands H3 section, no Guard
Commands, no Artifact Probe, no Forbidden Actions, no Effort line).

## Falsifiers

- [F-edge] parse_plan.py exits non-zero on this fixture — the required-field set or the legacy Verification fallback drifted

## Verification

```bash
echo "METRIC EDGE_OK=1"
```
