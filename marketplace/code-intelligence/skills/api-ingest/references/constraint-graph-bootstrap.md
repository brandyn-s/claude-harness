# Constraint Graph Bootstrap Stub

Critical Gotchas:
- Do not overwrite an existing `constraint_graph.py` — the real environment utility (if present) is richer than this stub. Check `if not graph.exists()` first.
- Do not emit anything other than valid JSON on stdout for `--dump` — `/api-preflight` Phase 0 calls `json.loads(result.stdout)`. A stray `print()` to stdout breaks it.
- Do not assume `~/Documents/api-docs/` exists — `mkdir -p` it before walking.

Used by Phase 4.5a-bootstrap when `~/Documents/api-docs/constraint_graph.py`
does not exist on first ingest. The skill issues a `Write` call with the
script body below.

## Stub body

```python
#!/usr/bin/env python3
"""Minimal constraint graph extractor — bootstrap stub.
Walks ~/Documents/api-docs/*/constraints.md and emits JSON nodes for
/api-preflight Phase 0. The real environment utility (if shipped
separately) will overwrite this stub."""
import json, pathlib, re, sys

def parse_constraints(api_dir: pathlib.Path):
    nodes = [{"api": api_dir.name, "type": "api"}]
    cmd = api_dir / "constraints.md"
    if not cmd.exists():
        return nodes
    text = cmd.read_text(encoding="utf-8", errors="replace")
    for h in re.findall(r"^###\s+(.+)$", text, re.MULTILINE):
        nodes.append({"api": api_dir.name, "type": "operation", "name": h.strip()})
    for row in re.findall(r"^\|\s*([^|]+?)\s*\|", text, re.MULTILINE):
        if row.strip().lower() not in ("operation", "---"):
            nodes.append({"api": api_dir.name, "type": "scope", "name": row.strip()})
    gotchas_blk = re.search(r"##\s*Common Gotchas\n(.+?)(?=\n##|\Z)", text, re.DOTALL)
    if gotchas_blk:
        for b in re.findall(r"^-\s+(.+)$", gotchas_blk.group(1), re.MULTILINE):
            nodes.append({"api": api_dir.name, "type": "gotcha", "name": b.strip()})
    return nodes

def main():
    root = pathlib.Path.home() / "Documents" / "api-docs"
    root.mkdir(parents=True, exist_ok=True)
    all_nodes = []
    for d in sorted(root.iterdir()):
        if d.is_dir():
            all_nodes.extend(parse_constraints(d))
    if "--dump" in sys.argv:
        print(json.dumps({"nodes": all_nodes}))

if __name__ == "__main__":
    main()
```

## Bootstrap invocation pattern (issued from SKILL.md Phase 4.5a-bootstrap)

```python
import pathlib
graph_path = pathlib.Path.home() / "Documents" / "api-docs" / "constraint_graph.py"
if not graph_path.exists():
    # Write tool call with the stub body above; encoding handled by the tool
    Write(file_path=str(graph_path), content=STUB_BODY)
```

## Node-type contract

| type | source | example |
|---|---|---|
| `api` | each subdirectory under `~/Documents/api-docs/` | `{api: "stripe", type: "api"}` |
| `operation` | `### {Resource Area}` headings in `constraints.md` | `{api: "stripe", type: "operation", name: "Charges"}` |
| `scope` | items in "Delegated Permissions" / "Application Permissions" columns of permission tables | `{api: "stripe", type: "scope", name: "read_charges"}` |
| `gotcha` | `- bullet` entries under `## Common Gotchas` | `{api: "stripe", type: "gotcha", name: "..."}` |

`/api-preflight` Phase 0 filters by `api` field, then traverses by type.
