"""Environment catalog loader: the one place hooks read environment-specific data.

A hook's LOGIC is generic. The MCP server names it classifies, the topic files
it injects, the failure-pattern files it points at, the repos it syncs and the
labels it prints are the operator's environment, and they live in a JSON
catalog that is read at run time, never in Python. Three layers are merged;
a later layer that defines a section replaces that section wholesale, and a
section a layer omits is inherited from the layers before it:

  1. contracts/environment-catalog.json beside this checkout: the shipped
     default. Every list is empty, so each consuming hook is a clean no-op
     until the operator fills a section in.
  2. $CLAUDE_CONFIG_DIR/environment-catalog.json, else
     ~/.claude/environment-catalog.json: the operator's real values.
     install.sh seeds this file from the default and never overwrites it.
  3. The file named by $CLAUDE_ENVIRONMENT_CATALOG: an explicit override. The
     hook test suite points it at hooks/test-hooks/fixtures/environment-catalog.json.

Sections (see contracts/environment-catalog.example.json for every one in use):

  security_write_confirm   server prefix -> label + write indicators; op-name
                           rules for servers with unstable ids; wrapper tools
  topic_routes             by_tool_prefix (mcp__<server>__ -> topic file) and
                           by_keyword (learning keyword -> topic file, ordered)
  failure_patterns         servers (server token -> *-patterns.md) and hints
                           (error keyword -> fix text, checked before built-ins)
  agent_dispatch           auth_mcp_keywords, protected_repo_paths
  expected_servers         MCP server names the consistency check expects
  repo_paths               friendly name -> path (string) or
                           {"path": ..., "session_sync": bool}
  session_start            config_repo: {"label": ..., "path": ...} or null

Fail-open by design: these hooks are advisory, so a missing layer is skipped
silently, a malformed or mistyped one is skipped with a one-line stderr note,
and nothing here raises for bad data. Keys starting with "_" are comments and
are dropped at every level. Stdlib only, because hooks run under the host's
python3.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

FILE_NAME = "environment-catalog.json"
OVERRIDE_ENV = "CLAUDE_ENVIRONMENT_CATALOG"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"

#: Section name -> the JSON container it must be. A layer whose section has the
#: wrong container is ignored for that section (with a note), never merged.
SECTIONS: dict[str, type] = {
    "security_write_confirm": dict,
    "topic_routes": dict,
    "failure_patterns": dict,
    "agent_dispatch": dict,
    "expected_servers": list,
    "repo_paths": dict,
    "session_start": dict,
}

_HERE = Path(__file__).resolve().parent


def empty_catalog() -> dict:
    """Every section present and empty: what a hook sees with no catalog at all."""
    return {name: kind() for name, kind in SECTIONS.items()}


def default_path() -> Path:
    """The shipped default, resolved relative to this file (repo checkout layout)."""
    return _HERE.parent / "contracts" / FILE_NAME


def home_path() -> Path:
    """The operator's catalog: $CLAUDE_CONFIG_DIR/ or ~/.claude/ + FILE_NAME."""
    config_dir = os.environ.get(CONFIG_DIR_ENV, "").strip()
    base = Path(config_dir).expanduser() if config_dir else Path.home() / ".claude"
    return base / FILE_NAME


def override_path() -> Path | None:
    raw = os.environ.get(OVERRIDE_ENV, "").strip()
    return Path(raw).expanduser() if raw else None


def layer_paths() -> list[Path]:
    """Merge order, lowest precedence first."""
    paths = [default_path(), home_path()]
    override = override_path()
    if override is not None:
        paths.append(override)
    return paths


def _note(message: str) -> None:
    try:
        sys.stderr.write(f"[environment-catalog] {message}\n")
    except Exception:  # noqa: S110, BLE001 -- fail-open: the note itself must never break a hook
        pass


def _strip_comments(value):
    """Drop `_`-prefixed keys (comments) at every dict level; keep lists of strings."""
    if isinstance(value, dict):
        return {
            k: _strip_comments(v)
            for k, v in value.items()
            if not (isinstance(k, str) and k.startswith("_"))
        }
    if isinstance(value, list):
        return [_strip_comments(v) for v in value]
    return value


def _read_layer(path: Path, *, required: bool) -> dict | None:
    """Parse one layer; None when it is absent or unusable (noted unless merely absent)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if required:
            _note(f"{path} is named by ${OVERRIDE_ENV} but does not exist; ignoring it")
        return None
    except OSError as exc:
        _note(f"cannot read {path} ({exc}); ignoring it")
        return None
    try:
        data = json.loads(text)
    except ValueError as exc:
        _note(f"ignoring malformed {path}: {exc}")
        return None
    if not isinstance(data, dict):
        _note(f"ignoring {path}: the top level must be a JSON object")
        return None
    return data


def load_catalog() -> dict:
    """The merged catalog: every section present, later layers replacing earlier ones."""
    catalog = empty_catalog()
    override = override_path()
    for path in layer_paths():
        layer = _read_layer(path, required=(path == override))
        if not layer:
            continue
        for name, kind in SECTIONS.items():
            if name not in layer:
                continue
            value = layer[name]
            if isinstance(value, kind):
                catalog[name] = _strip_comments(value)
            else:
                _note(
                    f"ignoring section {name!r} in {path}: expected a JSON "
                    f"{'object' if kind is dict else 'array'}, got {type(value).__name__}"
                )
    return catalog


def load_section(name: str):
    """One section of the merged catalog. Unknown names are a programming error."""
    if name not in SECTIONS:
        raise KeyError(f"unknown environment-catalog section {name!r}")
    return load_catalog()[name]


def expand_path(value: str) -> Path:
    """`~` and `$VAR` expansion for catalog paths."""
    return Path(os.path.expandvars(str(value))).expanduser()


def repo_entries(section: dict | None) -> list[dict]:
    """Normalise `repo_paths` to [{"name", "path", "session_sync"}] in catalog order.

    Accepts the string shorthand (`"name": "~/path"`, never synced at session
    start) and the object form (`{"path": ..., "session_sync": true}`).
    """
    entries: list[dict] = []
    for name, spec in (section or {}).items():
        if isinstance(spec, str):
            raw, sync = spec, False
        elif isinstance(spec, dict) and isinstance(spec.get("path"), str):
            raw, sync = spec["path"], bool(spec.get("session_sync", False))
        else:
            _note(f"ignoring repo_paths entry {name!r}: expected a path string or an object with 'path'")
            continue
        if not raw.strip():
            _note(f"ignoring repo_paths entry {name!r}: empty path")
            continue
        entries.append({"name": str(name), "path": expand_path(raw), "session_sync": sync})
    return entries
