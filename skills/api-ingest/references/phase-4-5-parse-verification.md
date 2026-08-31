# Phase 4.5 — Constraint Graph Parse Verification

This file holds the inline bootstrap, parse-verification, and outcome-classification
logic that SKILL.md Phase 4.5 references. SKILL.md keeps only the routing summary;
the executable detail lives here.

## Step 4.5a-bootstrap: Create the script on first ingest (if absent)

When `~/Documents/api-docs/constraint_graph.py` does not exist, the skill
issues a `Write(file_path="~/Documents/api-docs/constraint_graph.py",
content=STUB_BODY)` call with the stub from
`references/constraint-graph-bootstrap.md`. The stub parses
`constraints.md` for headings, permission tables, and Common Gotchas
sections, then dumps a JSON shape compatible with `/api-preflight`. The
real environment utility (if shipped separately) will overwrite the stub
on first encounter; the bootstrap exists so a fresh deployment is not
blocked. See `constraint-graph-bootstrap.md` for the full body, the
node-type contract, and the precise gotchas around `--dump` output.

## Step 4.5a: Parse verification

After ensuring the script exists (created by the bootstrap step above
if missing), invoke it to verify the new API produces parseable nodes:

```bash
GRAPH=~/Documents/api-docs/constraint_graph.py
if [ ! -f "$GRAPH" ]; then
  echo "Note: $GRAPH still absent after bootstrap attempt — skipping Phase 4.5."
  echo "Phase 4 semantic index is sufficient; /api-preflight Phase 1 will still work."
  # Continue to Phase 5; do NOT abort.
fi
```

When present, write a small Python script and run it (wrap the subprocess
call so a non-zero exit code surfaces as a Phase 4.5 warning, not an
ingestion-killing exception):

```python
import json, subprocess, sys, collections, pathlib

api_name = "{api-name}"
graph = pathlib.Path.home() / "Documents" / "api-docs" / "constraint_graph.py"
if not graph.exists():
    print(f"Note: {graph} not present — skipping Phase 4.5.")
    sys.exit(0)
try:
    result = subprocess.run(
        [sys.executable, str(graph), "--dump"],
        capture_output=True, check=True,
    )
except FileNotFoundError as e:
    print(f"WARNING: could not invoke constraint_graph.py ({e}).")
    print("Phase 4.5 skipped; Phase 4 semantic index remains valid.")
    sys.exit(0)
except subprocess.CalledProcessError as e:
    print(f"WARNING: constraint_graph.py --dump failed (exit {e.returncode}): "
          f"{e.stderr.decode('utf-8', errors='replace')[:500]}")
    print("Phase 4.5 skipped; Phase 4 semantic index remains valid.")
    sys.exit(0)
data = json.loads(result.stdout.decode("utf-8", errors="replace"))
nodes_for_api = [n for n in data["nodes"] if n.get("api") == api_name]
by_type = collections.Counter(n.get("type", "?") for n in nodes_for_api)
print(f"Graph nodes for {api_name}: {len(nodes_for_api)}")
for t, c in sorted(by_type.items()):
    print(f"  {t}: {c}")
```

## Step 4.5b: Classify outcome

- **0 nodes** — `constraints.md` produced no parseable structure. Warn:
  ```
  WARNING: constraint_graph.py extracted 0 nodes for {api-name}.
  /api-preflight Phase 0 will have no deterministic chains for this API and
  will fall back to slower semantic search. If this API has scoped permissions
  worth querying, restructure constraints.md per the format hints in Phase 3.
  ```
- **1 node (the API stub only)** — same warning but slightly milder; tables / gotchas didn't parse.
- **≥ 1 operation AND ≥ 1 scope** — full parse. Report:
  ```
  Graph: +{N} nodes for {api-name} ({operations} operations, {scopes} scopes,
         {gotchas} gotchas)
  ```
- **Only gotchas parsed** (no operations or scopes) — acceptable for simple bearer-token APIs. Report what was extracted; do not warn.

## Step 4.5c: No manual repair on failure

Do NOT auto-rewrite `constraints.md` when the parse yields 0 nodes. The format may genuinely not fit (e.g., a simple REST API without scoped permissions). Surface the warning to the user so they can decide whether to restructure or accept semantic-search-only traversal for this API.
