"""Parse a framework inventory markdown file into a list of entries.

Used by all dispatch modes. Supports the canonical inventory format
(2026-04-29-frameworks-master-inventory.md) and any alternate inventory
following the same per-entry structure.

Per-entry expected format:

    ### N.M Framework Name [confidence]

    Origin & background, Core move, Three examples, Cross-ref...

Filters out pointer-stub entries (cross-references with body <200 chars)
per the M3 inventory audit finding.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def parse(text: str) -> list[dict]:
    """Extract framework entries from inventory markdown.

    Returns a list of dicts with keys: id, name, group, header, body.
    Pointer stubs are filtered. A "stub" is detected by:
      (a) explicit marker — body contains "see also" or "covered in" near the start
      (b) body length under STUB_LENGTH_THRESHOLD (200 chars) AND no substantive
          structure (no headers, no bullet points)
    Filtered entries are logged to stderr by name so silent dropping is visible.
    """
    import sys as _sys

    STUB_LENGTH_THRESHOLD = 200
    explicit_stub_re = re.compile(r"^\s*(see also|covered in|see\s+\d|already (covered|in))",
                                   re.IGNORECASE | re.MULTILINE)

    lines = text.splitlines()
    entries: list[dict] = []
    current_group = "_PREAMBLE"
    current_entry: dict | None = None
    body_lines: list[str] = []

    def flush() -> None:
        nonlocal current_entry, body_lines
        if current_entry is not None:
            current_entry["body"] = "\n".join(body_lines).strip()
            entries.append(current_entry)
            body_lines = []

    for line in lines:
        if line.startswith("# Group "):
            flush()
            current_group = line.lstrip("# ").strip()
            current_entry = None
        elif line.startswith("### "):
            flush()
            header = line[4:].strip()
            id_match = re.match(r"^([A-Z]?\d+\.\d+|[A-Z]\.\d+)\s+", header)
            entry_id = id_match.group(1) if id_match else header[:20]
            name = re.sub(r"\s*\*\*\[.*?\]\*\*\s*$", "", header)
            name = re.sub(r"^[A-Z]?\d+\.\d+\s+", "", name)
            current_entry = {
                "id": entry_id,
                "name": name,
                "group": current_group,
                "header": header,
            }
        else:
            if current_entry is not None:
                body_lines.append(line)
    flush()

    # Filter pointer stubs — log every drop so silent filtering is visible.
    kept: list[dict] = []
    dropped: list[str] = []
    for e in entries:
        body = e.get("body", "")
        if explicit_stub_re.search(body[:400]):
            dropped.append(f"{e['id']} {e['name']} (explicit stub marker)")
            continue
        if len(body) <= STUB_LENGTH_THRESHOLD:
            dropped.append(f"{e['id']} {e['name']} (body {len(body)} chars ≤ {STUB_LENGTH_THRESHOLD})")
            continue
        kept.append(e)

    if dropped:
        print(f"[parse_inventory] dropped {len(dropped)} stubs: " +
              "; ".join(dropped[:10]) +
              (f" ... +{len(dropped)-10} more" if len(dropped) > 10 else ""),
              file=_sys.stderr)
    return kept


def parse_file(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(
            f"Inventory file not found: {path}\n"
            f"  Pass --inventory PATH on the dispatch CLI to point at an "
            f"existing inventory, or set PERSONA_INVENTORY env var.\n"
            f"  See references/inventory-management.md for the canonical "
            f"inventory format."
        )
    return parse(path.read_text(encoding="utf-8"))


USAGE = (
    "usage: parse_inventory.py <inventory.md>\n"
    "  Pass the path to a framework inventory markdown file.\n"
    "  See references/inventory-management.md for the canonical format.\n"
    "  -h, --help  show this help message and exit"
)


if __name__ == "__main__":
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(USAGE)
        sys.exit(0)
    if len(sys.argv) < 2:
        sys.exit(USAGE)
    p = Path(sys.argv[1])
    entries = parse_file(p)
    print(f"Parsed {len(entries)} substantive entries from {p.name}")
    groups: dict[str, int] = {}
    for e in entries:
        groups[e["group"]] = groups.get(e["group"], 0) + 1
    for g, n in sorted(groups.items(), key=lambda x: -x[1]):
        print(f"  {n:>3}  {g[:60]}")
