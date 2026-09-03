# manifests/ — the component graph

Every skill, hook, and rule carries a small manifest. `compile.py` links them into a
graph, and `query_engine.py` answers structural questions from it. This is the
fastest way to understand how the pieces connect, and it needs no setup beyond a
checkout.

```bash
python3 manifests/compile.py --root .                      # build graph.json
python3 manifests/query_engine.py --root . coverage
python3 manifests/query_engine.py --root . unenforced_rules
python3 manifests/query_engine.py --root . hooks_for_tool Bash
```

`graph.json` is generated and not committed — compile it first.

## Queries

| Query | Answers |
|---|---|
| `coverage` | how many components carry manifests |
| `enforcement_chain` | which hook actually enforces a given rule |
| `unenforced_rules` | rules with **no** mechanical backing — advisory only |
| `hooks_for_tool <Tool>` | every hook that fires for one tool |
| `full_session_hooks` | the session-lifecycle hook set |
| `depends_on` / `depended_on_by` | edges in either direction |
| `impact_of_removal <id>` | what breaks if you delete a component |
| `context_for_task` | which components a task should load |
| `skills_by_category` | skills grouped by purpose |
| `skills_requiring_auth` / `auth_requirements` | which skills need credentials, and which |
| `constraint_check` | declared constraints vs source |

`unenforced_rules` is the most interesting one: it names the rules that are text
only, which is exactly the list worth shortening.

## Validation

```bash
python3 manifests/compile.py --root . --check --strict-semantic --no-reindex
```

Exits non-zero on dangling references and drift between a manifest and its
source. CI runs this, and also proves it can fail by planting a manifest with a
dangling reference.

## Files

| File | Role |
|---|---|
| `compile.py` | builds and validates the graph |
| `query_engine.py` | answers queries against it |
| `schema.yaml`, `schemas/` | the manifest schemas |
| `ambient-budget.json` | the always-loaded byte ceiling, derived from a ledger |
| `scaffold.py`, `scaffold_extended.py` | generate manifests for new components |
| `validate_markers.py` | checks in-source markers against manifests |
| `analyze_metrics.py` | manifest coverage metrics |
