"""Check config syntax and exact MCP/skill runtime-name collisions.

Claude Code issue #85827 demonstrates one narrow runtime defect: an MCP server
can disappear when a discoverable standalone skill has the *exact same* name.
This guard inventories every documented source but deliberately does not invent
additional equivalence rules. In particular, it does not case-fold or Unicode
normalize names, and it preserves Claude's plugin namespaces.

Exit 0 = PASS, 1 = FAIL (parse/read/discovery error or proven exact collision).
"""

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
HOME = Path.home()
PROJ = os.environ.get("CLAUDE_PROJECT_ID", "")
PLUGINS_DIR = Path(
    os.environ.get("CLAUDE_PLUGIN_DIR", str(Path.home() / ".claude" / "plugins"))
)
PROJECT_CWD = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).expanduser()
if sys.platform == "darwin":
    _DEFAULT_MANAGED_MCP = Path(
        "/Library/Application Support/ClaudeCode/managed-mcp.json"
    )
elif os.name == "nt":
    _DEFAULT_MANAGED_MCP = Path(r"C:\Program Files\ClaudeCode\managed-mcp.json")
else:
    _DEFAULT_MANAGED_MCP = Path("/etc/claude-code/managed-mcp.json")
MANAGED_MCP_PATH = Path(
    os.environ.get("CLAUDE_MANAGED_MCP_PATH", str(_DEFAULT_MANAGED_MCP))
)

GLOBAL_SCOPE = "<global>"
_FRONTMATTER_NAME = re.compile(
    r"^name:\s*(?:['\"](?P<quoted>[^'\"]+)['\"]|(?P<plain>[^#\r\n]+?))\s*$",
    re.MULTILINE,
)


def _read_json_object(path: Path, errors: list[str]) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{path}: unparseable ({exc})")
        return None
    if not isinstance(data, dict):
        errors.append(f"{path}: root is not an object")
        return None
    return data


def _find_repo_root(start: Path) -> tuple[Path, bool]:
    """Return the nearest repository root and whether one was actually found."""
    try:
        current = start.expanduser().resolve()
    except OSError:
        current = start.expanduser().absolute()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate, True
    return current, False


def _parent_chain(start: Path, root: Path):
    current = start.resolve()
    root = root.resolve()
    if current != root and root not in current.parents:
        yield root
        return
    while True:
        yield current
        if current == root:
            return
        current = current.parent


def _nested_skill_dirs(start: Path):
    """Yield nested .claude/skills directories Claude may load on file access."""
    if not start.is_dir():
        return
    try:
        for dirpath, dirnames, _ in os.walk(start, followlinks=False):
            dirnames[:] = [
                name
                for name in dirnames
                if name
                not in {
                    ".git",
                    ".hg",
                    ".svn",
                    ".tox",
                    ".venv",
                    "__pycache__",
                    "build",
                    "dist",
                    "node_modules",
                    "target",
                    "vendor",
                    "venv",
                }
            ]
            directory = Path(dirpath)
            if directory.name == ".claude" and "skills" in dirnames:
                yield directory / "skills"
                dirnames.remove("skills")
    except OSError:
        return


def _plugin_installs(errors: list[str]) -> list[tuple[str, Path, str]]:
    """Return (plugin id, install path, visibility scope) from the registry."""
    registry = PLUGINS_DIR / "installed_plugins.json"
    if not registry.exists():
        return []
    data = _read_json_object(registry, errors)
    if data is None:
        return []
    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        errors.append(f"{registry}: 'plugins' is not an object")
        return []

    installs: list[tuple[str, Path, str]] = []
    for raw_plugin_id, raw_entries in plugins.items():
        if not isinstance(raw_plugin_id, str) or not raw_plugin_id:
            errors.append(f"{registry}: plugin id is not a non-empty string")
            continue
        if not isinstance(raw_entries, (dict, list)):
            errors.append(
                f"{registry}: plugin {raw_plugin_id!r} entry is not an object/list"
            )
            continue
        entries = raw_entries if isinstance(raw_entries, list) else [raw_entries]
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.append(
                    f"{registry}: plugin {raw_plugin_id!r}[{index}] is not an object"
                )
                continue
            raw_path = entry.get("installPath")
            if not isinstance(raw_path, str) or not raw_path.strip():
                errors.append(
                    f"{registry}: plugin {raw_plugin_id!r}[{index}] has no installPath"
                )
                continue
            path = Path(raw_path).expanduser()
            if not path.is_dir():
                errors.append(
                    f"{registry}: plugin {raw_plugin_id!r} installPath missing: {path}"
                )
                continue
            raw_project = entry.get("projectPath")
            if raw_project is not None and not isinstance(raw_project, str):
                errors.append(
                    f"{registry}: plugin {raw_plugin_id!r}[{index}] projectPath "
                    "is not a string"
                )
                continue
            scope = (
                str(_find_repo_root(Path(raw_project))[0])
                if isinstance(raw_project, str) and raw_project.strip()
                else GLOBAL_SCOPE
            )
            installs.append((raw_plugin_id, path, scope))
    return installs


def _add_mcp_map(
    value,
    *,
    scope: str,
    source: str,
    names: dict[str, list[tuple[str, str, str]]],
    errors: list[str],
    namespace: str = "",
) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append(f"{source}: 'mcpServers' is not an object")
        return
    for raw_name, config in value.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            errors.append(f"{source}: MCP server name is not a non-empty string")
            continue
        if not isinstance(config, dict):
            errors.append(f"{source}: MCP server {raw_name!r} is not an object")
            continue
        runtime_name = f"{namespace}{raw_name}" if namespace else raw_name
        names[runtime_name].append((runtime_name, source, scope))


def _mcp_map_from_document(document: dict, source: str, errors: list[str]):
    value = document.get("mcpServers", document)
    if not isinstance(value, dict):
        errors.append(f"{source}: MCP document is not an object")
        return None
    return value


def _standalone_skill_files(skills_dir: Path, errors: list[str]):
    if not skills_dir.exists():
        return []
    if not skills_dir.is_dir():
        errors.append(f"{skills_dir}: skills location is not a directory")
        return []
    try:
        return sorted(skills_dir.glob("*/SKILL.md"))
    except OSError as exc:
        errors.append(f"{skills_dir}: cannot enumerate skills ({exc})")
        return []


def _plugin_skill_files(path: Path, source: str, errors: list[str]):
    if not path.exists():
        errors.append(f"{source}: skill path missing: {path}")
        return []
    if not path.is_dir():
        errors.append(f"{source}: skill path is not a directory: {path}")
        return []
    files = []
    if (path / "SKILL.md").is_file():
        files.append(path / "SKILL.md")
    try:
        files.extend(sorted(path.glob("*/SKILL.md")))
    except OSError as exc:
        errors.append(f"{source}: cannot enumerate skill path {path} ({exc})")
    return files


def _plugin_skill_name(skill_file: Path, errors: list[str]):
    try:
        content = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"{skill_file}: cannot read ({exc})")
        return None
    frontmatter_end = content.find("\n---", 4) if content.startswith("---") else -1
    frontmatter = content[4:frontmatter_end] if frontmatter_end >= 0 else ""
    match = _FRONTMATTER_NAME.search(frontmatter)
    if match:
        raw_name = (match.group("quoted") or match.group("plain") or "").strip()
        if raw_name:
            return raw_name
    return skill_file.parent.name


def _add_standalone_skill_dir(
    skills_dir: Path,
    *,
    scope: str,
    source_prefix: str,
    names: dict[str, list[tuple[str, str, str]]],
    errors: list[str],
    seen_files: set[str],
) -> None:
    for skill_file in _standalone_skill_files(skills_dir, errors):
        try:
            source_key = str(skill_file.resolve())
        except OSError:
            source_key = str(skill_file)
        if source_key in seen_files:
            continue
        seen_files.add(source_key)
        raw_name = skill_file.parent.name
        if raw_name.casefold() == "synced":
            continue
        source = f"{source_prefix}:{skill_file}"
        names[raw_name].append((raw_name, source, scope))


def _add_standalone_commands(
    commands_dir: Path,
    *,
    scope: str,
    source_prefix: str,
    names: dict[str, list[tuple[str, str, str]]],
    errors: list[str],
    seen_files: set[str],
) -> None:
    if not commands_dir.exists():
        return
    if not commands_dir.is_dir():
        errors.append(f"{commands_dir}: commands location is not a directory")
        return
    try:
        command_files = sorted(commands_dir.glob("*.md"))
    except OSError as exc:
        errors.append(f"{commands_dir}: cannot enumerate commands ({exc})")
        return
    for command_file in command_files:
        try:
            source_key = str(command_file.resolve())
        except OSError:
            source_key = str(command_file)
        if source_key in seen_files:
            continue
        seen_files.add(source_key)
        raw_name = command_file.stem
        source = f"{source_prefix}:{command_file}"
        names[raw_name].append((raw_name, source, scope))


def _resolve_manifest_path(
    raw_path: str,
    *,
    install_path: Path,
    field: str,
    source: str,
    errors: list[str],
):
    allow_dot = field == "skills"
    if not raw_path.strip():
        errors.append(f"{source}: {field} path is empty")
        return None
    if raw_path == "." and allow_dot:
        relative = Path(".")
    elif raw_path.startswith("./"):
        relative = Path(raw_path)
    else:
        errors.append(f"{source}: {field} path {raw_path!r} must start with './'")
        return None
    if relative.is_absolute():
        errors.append(f"{source}: {field} path {raw_path!r} must be relative")
        return None
    install_root = install_path.resolve()
    resolved = (install_path / relative).resolve()
    if not resolved.is_relative_to(install_root):
        errors.append(f"{source}: {field} path {raw_path!r} is outside plugin root")
        return None
    return resolved


def _manifest_items(
    value,
    *,
    field: str,
    source: str,
    errors: list[str],
    allow_objects: bool,
):
    if isinstance(value, (str, dict)):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        expected = "string, array, or object" if allow_objects else "string or array"
        errors.append(f"{source}: {field!r} must be a {expected}")
        return []
    accepted = []
    for index, item in enumerate(items):
        if isinstance(item, str) or (allow_objects and isinstance(item, dict)):
            accepted.append(item)
        else:
            expected = "string or object" if allow_objects else "string"
            errors.append(f"{source}: {field}[{index}] must be a {expected}")
    return accepted


def _plugin_manifest(plugin_id: str, install_path: Path, errors: list[str]):
    path = install_path / ".claude-plugin" / "plugin.json"
    if not path.exists():
        return {}, path, plugin_id.split("@", 1)[0]
    manifest = _read_json_object(path, errors)
    if manifest is None:
        return None, path, plugin_id.split("@", 1)[0]
    raw_name = manifest.get("name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        errors.append(f"{path}: manifest 'name' is required and must be a string")
        plugin_name = plugin_id.split("@", 1)[0]
    else:
        plugin_name = raw_name
    return manifest, path, plugin_name


def _add_plugin_inventory(
    plugin_id: str,
    install_path: Path,
    scope: str,
    *,
    mcps: dict[str, list[tuple[str, str, str]]],
    skills: dict[str, list[tuple[str, str, str]]],
    errors: list[str],
    seen_skill_files: set[str],
    include_mcp: bool = True,
) -> None:
    manifest, manifest_path, plugin_name = _plugin_manifest(
        plugin_id, install_path, errors
    )
    if manifest is None:
        return

    skill_paths: list[tuple[Path, str]] = []
    default_skills = install_path / "skills"
    if default_skills.exists():
        skill_paths.append((default_skills, f"plugin {plugin_id}:default skills"))
    if "skills" in manifest:
        for item in _manifest_items(
            manifest["skills"],
            field="skills",
            source=str(manifest_path),
            errors=errors,
            allow_objects=False,
        ):
            path = _resolve_manifest_path(
                item,
                install_path=install_path,
                field="skills",
                source=str(manifest_path),
                errors=errors,
            )
            if path is not None:
                skill_paths.append((path, f"plugin {plugin_id}:{manifest_path}"))
    elif not default_skills.exists() and (install_path / "SKILL.md").is_file():
        skill_paths.append((install_path, f"plugin {plugin_id}:root skill"))

    for skill_path, source in skill_paths:
        for skill_file in _plugin_skill_files(skill_path, source, errors):
            source_key = str(skill_file.resolve())
            if source_key in seen_skill_files:
                continue
            seen_skill_files.add(source_key)
            skill_name = _plugin_skill_name(skill_file, errors)
            if skill_name is None:
                continue
            runtime_name = f"{plugin_name}:{skill_name}"
            skills[runtime_name].append((runtime_name, f"{source}:{skill_file}", scope))

    if not include_mcp:
        return

    mcp_sources: list[tuple[dict, str]] = []
    default_mcp = install_path / ".mcp.json"
    if default_mcp.exists():
        document = _read_json_object(default_mcp, errors)
        if document is not None:
            value = _mcp_map_from_document(document, str(default_mcp), errors)
            if value is not None:
                mcp_sources.append((value, f"plugin {plugin_id}:{default_mcp}"))
    if "mcpServers" in manifest:
        for index, item in enumerate(
            _manifest_items(
                manifest["mcpServers"],
                field="mcpServers",
                source=str(manifest_path),
                errors=errors,
                allow_objects=True,
            )
        ):
            item_source = f"{manifest_path}#mcpServers[{index}]"
            if isinstance(item, dict):
                value = _mcp_map_from_document(item, item_source, errors)
                if value is not None:
                    mcp_sources.append((value, item_source))
                continue
            path = _resolve_manifest_path(
                item,
                install_path=install_path,
                field="mcpServers",
                source=str(manifest_path),
                errors=errors,
            )
            if path is None:
                continue
            if not path.is_file():
                errors.append(f"{item_source}: MCP config missing: {path}")
                continue
            document = _read_json_object(path, errors)
            if document is not None:
                value = _mcp_map_from_document(document, str(path), errors)
                if value is not None:
                    mcp_sources.append((value, f"plugin {plugin_id}:{path}"))
    for value, source in mcp_sources:
        _add_mcp_map(
            value,
            scope=scope,
            source=source,
            names=mcps,
            errors=errors,
            namespace=f"plugin:{plugin_name}:",
        )


def _scopes_overlap(mcp_scope: str, skill_scope: str) -> bool:
    return (
        mcp_scope == GLOBAL_SCOPE
        or skill_scope == GLOBAL_SCOPE
        or mcp_scope == skill_scope
    )


def check_mcp_skill_collisions():
    """Return (collisions, errors, unique MCP names, unique skill names)."""
    errors: list[str] = []
    mcps: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    skills: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    plugin_mcps: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    plugin_skills: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    seen_skill_files: set[str] = set()

    managed_active = MANAGED_MCP_PATH.exists()
    if managed_active:
        managed = _read_json_object(MANAGED_MCP_PATH, errors)
        if managed is not None:
            if "mcpServers" not in managed:
                errors.append(f"{MANAGED_MCP_PATH}: missing 'mcpServers' object")
            else:
                _add_mcp_map(
                    managed["mcpServers"],
                    scope=GLOBAL_SCOPE,
                    source=str(MANAGED_MCP_PATH),
                    names=mcps,
                    errors=errors,
                )

    state_path = HOME / ".claude.json"
    state = _read_json_object(state_path, errors) if state_path.exists() else {}
    # Value marks the active session start. Historical project records are still
    # checked at their direct locations, but only a real repository (or the
    # active project) is eligible for recursive nested-skill discovery.
    project_starts: dict[Path, bool] = {}
    if state is not None:
        if not managed_active:
            _add_mcp_map(
                state.get("mcpServers"),
                scope=GLOBAL_SCOPE,
                source=str(state_path),
                names=mcps,
                errors=errors,
            )
        projects = state.get("projects", {})
        if not isinstance(projects, dict):
            errors.append(f"{state_path}: 'projects' is not an object")
        else:
            for raw_project, entry in projects.items():
                if not isinstance(raw_project, str) or not isinstance(entry, dict):
                    errors.append(
                        f"{state_path}: malformed project entry {raw_project!r}"
                    )
                    continue
                start = Path(raw_project).expanduser()
                root, _ = _find_repo_root(start)
                project_starts.setdefault(start, False)
                if not managed_active:
                    _add_mcp_map(
                        entry.get("mcpServers"),
                        scope=str(root),
                        source=f"{state_path}:projects[{raw_project}]",
                        names=mcps,
                        errors=errors,
                    )

    legacy_path = HOME / ".mcp.json"
    if legacy_path.exists() and not managed_active:
        legacy = _read_json_object(legacy_path, errors)
        if legacy is not None:
            _add_mcp_map(
                legacy.get("mcpServers"),
                scope=GLOBAL_SCOPE,
                source=str(legacy_path),
                names=mcps,
                errors=errors,
            )

    _, cwd_is_repo = _find_repo_root(PROJECT_CWD)
    if cwd_is_repo or os.environ.get("CLAUDE_PROJECT_DIR"):
        project_starts[PROJECT_CWD] = True

    _add_standalone_skill_dir(
        CLAUDE_DIR / "skills",
        scope=GLOBAL_SCOPE,
        source_prefix="user skill",
        names=skills,
        errors=errors,
        seen_files=seen_skill_files,
    )
    _add_standalone_commands(
        CLAUDE_DIR / "commands",
        scope=GLOBAL_SCOPE,
        source_prefix="user command",
        names=skills,
        errors=errors,
        seen_files=seen_skill_files,
    )

    seen_project_mcp: set[str] = set()
    for start, is_active in sorted(
        project_starts.items(), key=lambda item: str(item[0])
    ):
        root, is_repo = _find_repo_root(start)
        scope = str(root)
        discovery_root = root if is_repo else start
        project_mcp = discovery_root / ".mcp.json"
        mcp_key = str(project_mcp)
        if (
            not managed_active
            and project_mcp.exists()
            and mcp_key not in seen_project_mcp
        ):
            seen_project_mcp.add(mcp_key)
            document = _read_json_object(project_mcp, errors)
            if document is not None:
                _add_mcp_map(
                    document.get("mcpServers"),
                    scope=scope,
                    source=str(project_mcp),
                    names=mcps,
                    errors=errors,
                )
        directories = _parent_chain(start, root) if is_repo else (start,)
        for directory in directories:
            _add_standalone_skill_dir(
                directory / ".claude" / "skills",
                scope=scope,
                source_prefix=f"project skill {scope}",
                names=skills,
                errors=errors,
                seen_files=seen_skill_files,
            )
            _add_standalone_commands(
                directory / ".claude" / "commands",
                scope=scope,
                source_prefix=f"project command {scope}",
                names=skills,
                errors=errors,
                seen_files=seen_skill_files,
            )
        if is_repo or is_active:
            for skills_dir in _nested_skill_dirs(start):
                _add_standalone_skill_dir(
                    skills_dir,
                    scope=scope,
                    source_prefix=f"nested project skill {scope}",
                    names=skills,
                    errors=errors,
                    seen_files=seen_skill_files,
                )

    for plugin_id, install_path, scope in _plugin_installs(errors):
        _add_plugin_inventory(
            plugin_id,
            install_path,
            scope,
            mcps=plugin_mcps,
            skills=plugin_skills,
            errors=errors,
            seen_skill_files=seen_skill_files,
            include_mcp=not managed_active,
        )

    collisions = []
    for exact_name in sorted(set(mcps) & set(skills)):
        for mcp_record in mcps[exact_name]:
            for skill_record in skills[exact_name]:
                if _scopes_overlap(mcp_record[2], skill_record[2]):
                    collisions.append((exact_name, mcp_record, skill_record))
    # Plugin components are retained in the inventory/counts, but are excluded
    # from the hard oracle. Claude scopes plugin skills and MCP servers, and an
    # installed plugin may also be disabled for the current project. #85827 only
    # proves exact collisions between standalone runtime names.
    return (
        collisions,
        sorted(set(errors)),
        len(mcps) + len(plugin_mcps),
        len(skills) + len(plugin_skills),
    )


def check_config():
    """Return (status, message). status is PASS or FAIL."""
    cfgs = [
        CLAUDE_DIR / "settings.json",
        CLAUDE_DIR / "settings.local.json",
        HOME / ".mcp.json",
        HOME / ".claude.json",
        (CLAUDE_DIR / "projects" / PROJ / "settings.json") if PROJ else None,
    ]
    ok = total = 0
    bad = []
    seen_cfgs: set[str] = set()
    for config in cfgs:
        if config is None or not config.exists():
            continue
        key = str(config.resolve())
        if key in seen_cfgs:
            continue
        seen_cfgs.add(key)
        total += 1
        try:
            with config.open(encoding="utf-8") as handle:
                json.load(handle)
            ok += 1
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            bad.append(f"{config.name}: {exc}")
    if bad:
        return "FAIL", f"{ok}/{total} valid — " + "; ".join(bad)

    collisions, inventory_errors, mcp_count, skill_count = check_mcp_skill_collisions()
    if inventory_errors:
        return (
            "FAIL",
            f"{ok}/{total} valid — MCP/skill collision inventory incomplete: "
            + "; ".join(inventory_errors[:8]),
        )
    if collisions:
        evidence = []
        for exact_name, mcp, skill in collisions[:5]:
            evidence.append(
                f"{exact_name!r}: MCP {mcp[0]!r} ({mcp[1]}) vs skill "
                f"{skill[0]!r} ({skill[1]})"
            )
        return (
            "FAIL",
            f"{ok} files valid — MCP/skill name collision ({len(collisions)}): "
            + "; ".join(evidence)
            + "; rename the MCP server or skill so their exact runtime names differ",
        )
    return (
        "PASS",
        (
            f"{ok} files valid; {mcp_count} MCP names vs {skill_count} skill names, "
            "0 exact runtime-name collisions"
        ),
    )


def main():
    status, message = check_config()
    print(f"Config: {status} — {message}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
