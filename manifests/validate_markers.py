"""Validate inter-skill runtime markers against their JSON schemas.

Markers are JSON files in ~/.claude/ written by one skill or hook and read by
others. They form an implicit contract surface that has drifted historically
(see PR #958: one writer emitted `lessons[]` while a historical reader expected
`lesson_count`, giving silent zeros for months).

Schemas live in manifests/schemas/*.schema.json and follow JSON Schema draft-07.
This validator implements only the subset of draft-07 the schemas use:
type / required / properties / additionalProperties / items / enum / const /
oneOf / pattern / minimum / format=date-time. Adding a feature here is cheaper
than pulling in the jsonschema package; we'll switch if the subset grows.

CLI usage:
    python manifests/validate_markers.py <marker-id> <path-to-file>
    # e.g. python manifests/validate_markers.py last-distill ~/.claude/last-distill.json

Library usage:
    from manifests.validate_markers import validate
    issues = validate("last-distill", marker_dict)
    if issues:
        raise ValueError("marker invalid: " + "; ".join(issues))
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"

_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}


def _load_schema(marker_id: str) -> dict[str, Any]:
    if marker_id in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[marker_id]
    path = SCHEMAS_DIR / f"{marker_id}.schema.json"
    if not path.exists():
        raise FileNotFoundError(f"no schema for marker '{marker_id}' at {path}")
    schema = json.loads(path.read_text(encoding="utf-8"))
    _SCHEMA_CACHE[marker_id] = schema
    return schema


def _type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)


def _check(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    """Return a list of issue strings (empty = valid)."""
    issues: list[str] = []

    # oneOf — value must match exactly one branch
    if "oneOf" in schema:
        matches = [s for s in schema["oneOf"] if not _check(value, s, path)]
        if len(matches) != 1:
            issues.append(f"{path}: value matched {len(matches)} oneOf branches (expected exactly 1)")
        return issues

    # const
    if "const" in schema and value != schema["const"]:
        issues.append(f"{path}: expected const {schema['const']!r}, got {value!r}")
        return issues

    # enum
    if "enum" in schema and value not in schema["enum"]:
        issues.append(f"{path}: value {value!r} not in enum {schema['enum']}")
        return issues

    # type (may be a string or a list of strings)
    expected_type = schema.get("type")
    if expected_type:
        allowed = [expected_type] if isinstance(expected_type, str) else list(expected_type)
        if not any(_type_matches(value, t) for t in allowed):
            issues.append(f"{path}: expected type {expected_type}, got {type(value).__name__}")
            return issues
        # Downstream format/pattern/minimum checks assume a single resolved type.
        # Pick the one that actually matched so they don't misfire.
        for t in allowed:
            if _type_matches(value, t):
                expected_type = t
                break

    # string format / pattern
    if expected_type == "string":
        if schema.get("format") == "date-time":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                issues.append(f"{path}: not a valid ISO 8601 date-time: {value!r}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            issues.append(f"{path}: value {value!r} does not match pattern {schema['pattern']!r}")

    # integer minimum
    if expected_type == "integer" and "minimum" in schema and value < schema["minimum"]:
        issues.append(f"{path}: value {value} < minimum {schema['minimum']}")

    # object — required, properties, additionalProperties
    if expected_type == "object" and isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                issues.append(f"{path}: missing required property {req!r}")
        properties = schema.get("properties", {})
        for key, sub in properties.items():
            if key in value:
                issues.extend(_check(value[key], sub, f"{path}.{key}"))
        additional = schema.get("additionalProperties", True)
        if additional is False:
            extras = [k for k in value if k not in properties]
            for extra in extras:
                issues.append(f"{path}: unexpected property {extra!r}")
        elif isinstance(additional, dict):
            for key in value:
                if key not in properties:
                    issues.extend(_check(value[key], additional, f"{path}.{key}"))

    # array — items
    if expected_type == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(value):
                issues.extend(_check(item, item_schema, f"{path}[{i}]"))

    return issues


def validate(marker_id: str, data: Any) -> list[str]:
    """Validate `data` against the schema for `marker_id`. Returns a list of
    human-readable issue strings; empty means valid.
    """
    schema = _load_schema(marker_id)
    return _check(data, schema, marker_id)


def validate_consistency(marker_id: str, data: Any) -> list[str]:
    """Schema-orthogonal invariants the JSON Schema can't express on its own."""
    issues: list[str] = []
    if marker_id == "last-distill" and isinstance(data, dict):
        lc = data.get("lesson_count")
        lessons = data.get("lessons")
        if isinstance(lc, int) and isinstance(lessons, list) and lc != len(lessons):
            issues.append(
                f"last-distill: lesson_count={lc} but len(lessons)={len(lessons)}"
            )
    return issues


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: validate_markers.py <marker-id> <path-to-file>", file=sys.stderr)
        print("       marker-id: one of " + ", ".join(sorted(
            p.stem.replace(".schema", "") for p in SCHEMAS_DIR.glob("*.schema.json")
        )), file=sys.stderr)
        return 2

    marker_id, path = sys.argv[1], Path(sys.argv[2])
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 2

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"invalid JSON: {e}", file=sys.stderr)
        return 1

    issues = validate(marker_id, data) + validate_consistency(marker_id, data)
    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1

    print(f"{path}: valid against {marker_id} schema")
    return 0


if __name__ == "__main__":
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__ or "<usage TBD>")
        sys.exit(0)
    sys.exit(main())
