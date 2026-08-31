"""Check 1b (coverage) + 1c (error handling) for hooks/*.py.

Only counts ACTUAL hooks — files that fire as a hook — against the
coverage/try-except denominators. A hook receives its payload on stdin, so
"reads stdin OR is registered in settings.json" is the hook signal. Pure
helper/library modules (`_platform.py`, `atomic_write.py`, `git_lock.py`,
`manifest_metrics.py`) are imported, never fire, and need neither a dedicated
test_*.py nor a top-level try/except — counting them produced false WARNs
(observed 2026-06-16: `_platform.py` flagged for no try/except; 4 helpers
flagged "untested"). Helpers are reported separately, not as failures.

The helper also inventories hook definitions from every installPath in
``plugins/installed_plugins.json``. This is intentionally independent of
``enabledPlugins`` and Claude's ``/hooks`` display: disabled plugin hooks have
been observed remaining active upstream, so an installed disabled plugin with
hook definitions is surfaced with its on-disk evidence path.

Exit 0 = PASS, 1 = WARN (coverage/schema issue or disabled plugin hooks),
2 = FAIL (plugin registry/manifest/hook metadata could not be audited).
"""

import json
import os
import re
import sys
from pathlib import Path

H = os.path.expanduser("~/.claude")
HOOKS = f"{H}/hooks"
TESTS = f"{HOOKS}/test-hooks"
PROJECT_CWD = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).expanduser()

STDIN_RE = re.compile(r"sys\.stdin|json\.load\(\s*sys\.stdin|input\(")

_HOOK_METADATA_KEYS = {"description", "version", "$schema", "name"}


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


def _records_from_hook_document(
    document: dict,
    *,
    plugin_id: str,
    state: str,
    state_source: str,
    source: str,
    errors: list[str],
) -> list[dict]:
    """Validate a plugin hook document and return one evidence row per hook."""
    if "hooks" in document:
        hook_map = document["hooks"]
    else:
        hook_map = {
            key: value
            for key, value in document.items()
            if key not in _HOOK_METADATA_KEYS
        }
    if not isinstance(hook_map, dict):
        errors.append(f"{source}: 'hooks' is not an object")
        return []
    if not hook_map:
        errors.append(f"{source}: hook metadata contains no hook events")
        return []

    records: list[dict] = []
    for event, groups in hook_map.items():
        if not isinstance(event, str) or not event.strip():
            errors.append(f"{source}: hook event name is not a non-empty string")
            continue
        if not isinstance(groups, list):
            errors.append(f"{source}:{event}: matcher groups are not a list")
            continue
        for group_index, group in enumerate(groups):
            location = f"{source}:{event}[{group_index}]"
            if not isinstance(group, dict):
                errors.append(f"{location}: matcher group is not an object")
                continue
            matcher = group.get("matcher")
            if matcher is not None and not isinstance(matcher, str):
                errors.append(f"{location}: matcher is not a string")
                continue
            hooks = group.get("hooks")
            if not isinstance(hooks, list):
                errors.append(f"{location}: 'hooks' is not a list")
                continue
            for hook_index, hook in enumerate(hooks):
                if not isinstance(hook, dict):
                    errors.append(f"{location}.hooks[{hook_index}]: not an object")
                    continue
                records.append(
                    {
                        "plugin": plugin_id,
                        "state": state,
                        "state_source": state_source,
                        "enabled": (
                            True
                            if state == "enabled"
                            else False
                            if state == "disabled"
                            else None
                        ),
                        "event": event,
                        "matcher": matcher,
                        "source": source,
                    }
                )
    return records


def _find_repo_root(start: Path) -> Path:
    try:
        current = start.expanduser().resolve()
    except OSError:
        current = start.expanduser().absolute()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def _enabled_plugin_layers(
    claude_root: Path, project_dir: Path | None, errors: list[str]
):
    paths = [(claude_root / "settings.json", "user")]
    if project_dir is not None:
        project_root = _find_repo_root(project_dir)
        paths.extend(
            [
                (project_root / ".claude" / "settings.json", "project"),
                (project_root / ".claude" / "settings.local.json", "local"),
            ]
        )
    layers = []
    for path, scope in paths:
        if not path.exists():
            continue
        document = _read_json_object(path, errors)
        if document is None:
            continue
        configured = document.get("enabledPlugins", {})
        if not isinstance(configured, dict):
            errors.append(f"{path}: 'enabledPlugins' is not an object")
            continue
        valid = {}
        for plugin_id, value in configured.items():
            if not isinstance(plugin_id, str) or not plugin_id:
                errors.append(f"{path}: enabledPlugins key is not a non-empty string")
                continue
            if not isinstance(value, bool):
                errors.append(f"{path}: enabledPlugins[{plugin_id!r}] is not boolean")
                continue
            valid[plugin_id] = value
        layers.append((valid, f"{path} ({scope})"))
    return layers


def _resolve_plugin_state(
    plugin_id: str,
    *,
    entry: dict,
    manifest: dict,
    manifest_path: Path,
    claude_root: Path,
    project_dir: Path | None,
    errors: list[str],
):
    scope = entry.get("scope", "user")
    if not isinstance(scope, str):
        errors.append(f"{plugin_id}: installed scope is not a string")
        scope = "unknown"
    raw_entry_project = entry.get("projectPath")
    if raw_entry_project is not None and not isinstance(raw_entry_project, str):
        errors.append(f"{plugin_id}: projectPath is not a string")
        raw_entry_project = None
    effective_project = project_dir
    if scope in {"project", "local"} and isinstance(raw_entry_project, str):
        # A registry entry tied to a project must resolve against that project's
        # project/local settings, even while healthcheck runs from another repo.
        effective_project = Path(raw_entry_project).expanduser()
    elif effective_project is None and isinstance(raw_entry_project, str):
        effective_project = Path(raw_entry_project).expanduser()

    layers = _enabled_plugin_layers(claude_root, effective_project, errors)
    decision = None
    source = None
    for configured, layer_source in layers:
        if plugin_id in configured:
            decision = configured[plugin_id]
            source = layer_source
    if decision is not None:
        return ("enabled" if decision else "disabled"), source

    if scope in {"project", "local"} and effective_project is None:
        return "unknown", "project/local enabledPlugins scope unavailable"

    # Marketplace metadata, when retained in the installed entry, overrides the
    # plugin manifest. Otherwise use plugin.json. The documented implicit default
    # is true when neither source specifies defaultEnabled.
    if "defaultEnabled" in entry:
        default = entry["defaultEnabled"]
        if not isinstance(default, bool):
            errors.append(f"{plugin_id}: installed defaultEnabled is not boolean")
            return "unknown", "invalid installed defaultEnabled"
        return ("enabled" if default else "disabled"), (
            f"{plugin_id} installed metadata#defaultEnabled"
        )

    plugin_name, separator, marketplace_name = plugin_id.rpartition("@")
    if separator and plugin_name and marketplace_name:
        marketplace_path = (
            claude_root
            / "plugins"
            / "marketplaces"
            / marketplace_name
            / ".claude-plugin"
            / "marketplace.json"
        )
        if marketplace_path.exists():
            marketplace = _read_json_object(marketplace_path, errors)
            if marketplace is None:
                return "unknown", f"{marketplace_path}#defaultEnabled(unreadable)"
            listings = marketplace.get("plugins")
            if not isinstance(listings, list):
                errors.append(f"{marketplace_path}: 'plugins' is not an array")
                return "unknown", f"{marketplace_path}#defaultEnabled(invalid)"
            for index, listing in enumerate(listings):
                if not isinstance(listing, dict):
                    errors.append(
                        f"{marketplace_path}: plugins[{index}] is not an object"
                    )
                    continue
                if listing.get("name") != plugin_name:
                    continue
                if "defaultEnabled" not in listing:
                    break
                default = listing["defaultEnabled"]
                if not isinstance(default, bool):
                    errors.append(
                        f"{marketplace_path}: plugins[{index}].defaultEnabled "
                        "is not boolean"
                    )
                    return "unknown", (
                        f"{marketplace_path}#plugins[{index}].defaultEnabled(invalid)"
                    )
                return ("enabled" if default else "disabled"), (
                    f"{marketplace_path}#plugins[{index}].defaultEnabled"
                )
    if "defaultEnabled" in manifest:
        default = manifest["defaultEnabled"]
        if not isinstance(default, bool):
            errors.append(f"{manifest_path}: defaultEnabled is not boolean")
            return "unknown", f"{manifest_path}#defaultEnabled(invalid)"
        return ("enabled" if default else "disabled"), (
            f"{manifest_path}#defaultEnabled"
        )
    return "enabled", f"{manifest_path}#defaultEnabled(default=true)"


def _manifest_items(value, *, source: str, errors: list[str]):
    if isinstance(value, (str, dict)):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        errors.append(f"{source}: 'hooks' must be a string, array, or object")
        return []
    accepted = []
    for index, item in enumerate(items):
        if isinstance(item, (str, dict)):
            accepted.append(item)
        else:
            errors.append(f"{source}: hooks[{index}] must be a string or object")
    return accepted


def _resolve_hook_path(
    raw_path: str, *, install_path: Path, source: str, errors: list[str]
):
    if not raw_path.startswith("./"):
        errors.append(f"{source}: hook path {raw_path!r} must start with './'")
        return None
    relative = Path(raw_path)
    if relative.is_absolute():
        errors.append(f"{source}: hook path {raw_path!r} must be relative")
        return None
    install_root = install_path.resolve()
    resolved = (install_path / relative).resolve()
    if not resolved.is_relative_to(install_root):
        errors.append(f"{source}: hook path {raw_path!r} is outside plugin root")
        return None
    if not resolved.is_file():
        errors.append(f"{source}: declared hook metadata missing: {resolved}")
        return None
    return resolved


def scan_installed_plugin_hooks(claude_dir=None, *, project_dir=None):
    """Inventory installed plugin hooks independent of enabled state/UI.

    Returns ``(records, errors)``. Any error means the inventory is incomplete
    and callers must fail closed rather than report a false clean result.
    """
    root = Path(claude_dir) if claude_dir is not None else Path(H)
    registry_path = root / "plugins" / "installed_plugins.json"
    errors: list[str] = []

    explicit_project = Path(project_dir).expanduser() if project_dir else None
    user_layers = _enabled_plugin_layers(root, explicit_project, errors)
    declared_plugins = {plugin_id for layer, _ in user_layers for plugin_id in layer}

    if not registry_path.exists():
        if declared_plugins:
            errors.append(
                f"{registry_path}: missing while settings declare enabled plugins"
            )
        return [], errors

    registry = _read_json_object(registry_path, errors)
    if registry is None:
        return [], errors
    plugins = registry.get("plugins")
    if not isinstance(plugins, dict):
        errors.append(f"{registry_path}: 'plugins' is not an object")
        return [], errors

    records: list[dict] = []
    for raw_plugin_id, raw_entries in plugins.items():
        if not isinstance(raw_plugin_id, str) or not raw_plugin_id:
            errors.append(f"{registry_path}: plugin id is not a non-empty string")
            continue
        plugin_id = raw_plugin_id
        entries = raw_entries if isinstance(raw_entries, list) else [raw_entries]
        if not isinstance(raw_entries, (dict, list)):
            errors.append(
                f"{registry_path}: plugin {plugin_id!r} entry is not an object/list"
            )
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.append(
                    f"{registry_path}: plugin {plugin_id!r}[{index}] is not an object"
                )
                continue
            install_raw = entry.get("installPath")
            if not isinstance(install_raw, str) or not install_raw.strip():
                errors.append(
                    f"{registry_path}: plugin {plugin_id!r}[{index}] has no installPath"
                )
                continue
            install_path = Path(install_raw).expanduser()
            if not install_path.is_dir():
                errors.append(
                    f"{registry_path}: plugin {plugin_id!r} installPath missing: "
                    f"{install_path}"
                )
                continue
            manifest_path = install_path / ".claude-plugin" / "plugin.json"
            manifest = {}
            if manifest_path.exists():
                loaded_manifest = _read_json_object(manifest_path, errors)
                if loaded_manifest is None:
                    continue
                manifest = loaded_manifest
                manifest_name = manifest.get("name")
                if not isinstance(manifest_name, str) or not manifest_name.strip():
                    errors.append(
                        f"{manifest_path}: manifest 'name' is required and must be a string"
                    )

            state, state_source = _resolve_plugin_state(
                plugin_id,
                entry=entry,
                manifest=manifest,
                manifest_path=manifest_path,
                claude_root=root,
                project_dir=explicit_project,
                errors=errors,
            )

            sources: list[Path] = []
            if "hooks" in manifest:
                for item_index, declared in enumerate(
                    _manifest_items(
                        manifest["hooks"], source=str(manifest_path), errors=errors
                    )
                ):
                    inline_source = f"{manifest_path}#hooks[{item_index}]"
                    if isinstance(declared, dict):
                        records.extend(
                            _records_from_hook_document(
                                {"hooks": declared},
                                plugin_id=plugin_id,
                                state=state,
                                state_source=state_source,
                                source=inline_source,
                                errors=errors,
                            )
                        )
                        continue
                    declared_path = _resolve_hook_path(
                        declared,
                        install_path=install_path,
                        source=str(manifest_path),
                        errors=errors,
                    )
                    if declared_path is not None:
                        sources.append(declared_path)
            else:
                conventional = install_path / "hooks" / "hooks.json"
                if conventional.is_file():
                    sources.append(conventional.resolve())

            seen_sources: set[str] = set()
            for source_path in sources:
                source_key = str(source_path)
                if source_key in seen_sources:
                    continue
                seen_sources.add(source_key)
                document = _read_json_object(source_path, errors)
                if document is None:
                    continue
                records.extend(
                    _records_from_hook_document(
                        document,
                        plugin_id=plugin_id,
                        state=state,
                        state_source=state_source,
                        source=str(source_path),
                        errors=errors,
                    )
                )

    return records, sorted(set(errors))


def registered_hook_basenames():
    """Basenames of every .py referenced in settings.json + settings.local.json hooks."""
    names = set()
    for cfg in (f"{H}/settings.json", f"{H}/settings.local.json"):
        if not os.path.exists(cfg):
            continue
        try:
            with open(cfg, encoding="utf-8") as handle:
                d = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        for regs in d.get("hooks", {}).values():
            if not isinstance(regs, list):
                continue
            for reg in regs:
                if not isinstance(reg, dict):
                    continue
                hook_entries = reg.get("hooks", [])
                if not isinstance(hook_entries, list):
                    continue
                for h in hook_entries:
                    if not isinstance(h, dict):
                        continue
                    for m in re.findall(r"[\w./-]+\.py", h.get("command", "")):
                        names.add(os.path.basename(m))
    return names


def norm(n):
    n = n.replace("-", "_")
    n = n.removeprefix("test_")
    n = n.removesuffix(".py")
    return n


def check_matcher_schema():
    """Validate every settings.json / settings.local.json hook matcher-group is
    schema-valid. Motivation: upstream #75071/#75081 (v2.1.204, macOS, has repro) —
    ONE schema-invalid hook matcher (a matcher that isn't a compilable regex, or a
    malformed matcher-group / hook entry) SILENTLY DISABLES ALL settings.json hooks
    with no warning, so our entire PreToolUse/PostToolUse security stack
    (bash-security-guard, worktree-enforcement, security-write-confirm) can go dark
    from a single typo. This surfaces the offending entry before it kills the stack.
    Returns a list of human-readable problems (empty = clean)."""
    problems = []
    for cfg in (f"{H}/settings.json", f"{H}/settings.local.json"):
        if not os.path.exists(cfg):
            continue
        base = os.path.basename(cfg)
        try:
            with open(cfg, encoding="utf-8") as handle:
                d = json.load(handle)
        except (OSError, json.JSONDecodeError) as e:
            problems.append(f"{base}: unparseable ({e})")
            continue
        hooks = d.get("hooks", {})
        if not isinstance(hooks, dict):
            problems.append(f"{base}: 'hooks' is not an object")
            continue
        for event, regs in hooks.items():
            if not isinstance(regs, list):
                problems.append(f"{base}:{event}: value is not a list")
                continue
            for i, reg in enumerate(regs):
                loc = f"{base}:{event}[{i}]"
                if not isinstance(reg, dict):
                    problems.append(f"{loc}: matcher-group is not an object")
                    continue
                m = reg.get("matcher")
                # matcher is optional (some events match all); when present it MUST be
                # a compilable regex string — a bad regex is a prime #75071 trigger.
                if m is not None:
                    if not isinstance(m, str):
                        problems.append(
                            f"{loc}: matcher is not a string ({type(m).__name__})"
                        )
                    else:
                        try:
                            re.compile(m)
                        except re.error as e:
                            problems.append(
                                f"{loc}: matcher {m!r} is not a valid regex ({e})"
                            )
                hlist = reg.get("hooks", [])
                if not isinstance(hlist, list):
                    problems.append(f"{loc}: 'hooks' is not a list")
                    continue
                for j, h in enumerate(hlist):
                    if not isinstance(h, dict):
                        problems.append(f"{loc}.hooks[{j}]: not an object")
                        continue
                    # A hook carries a payload: `command` (command hook) or `prompt`
                    # (prompt hook); `type` may be implicit. Flag ONLY an entry with
                    # neither — over-rejecting a valid/unknown hook shape would itself
                    # DoS the check (verify-effectiveness hook-block-rate class; the
                    # 2026-07-08 known-negative already caught an over-strict draft that
                    # rejected our live `type: "prompt"` hooks). The load-bearing #75071
                    # trigger is the matcher-regex check above, not hook internals.
                    cmd, prompt = h.get("command"), h.get("prompt")
                    has_cmd = isinstance(cmd, str) and bool(cmd.strip())
                    has_prompt = isinstance(prompt, str) and bool(prompt.strip())
                    if not has_cmd and not has_prompt:
                        problems.append(
                            f"{loc}.hooks[{j}]: no command or prompt payload (type={h.get('type')!r})"
                        )
    return problems


def main():
    schema_problems = check_matcher_schema()
    plugin_hooks, plugin_errors = scan_installed_plugin_hooks(project_dir=PROJECT_CWD)
    disabled_plugin_hooks = [
        hook for hook in plugin_hooks if hook["state"] == "disabled"
    ]
    unknown_plugin_hooks = [hook for hook in plugin_hooks if hook["state"] == "unknown"]
    registered = registered_hook_basenames()
    all_py = sorted(f for f in os.listdir(HOOKS) if f.endswith(".py"))

    hooks, helpers = [], []
    for f in all_py:
        body = ""
        try:
            with open(f"{HOOKS}/{f}", encoding="utf-8") as handle:
                body = handle.read()
        except OSError:
            pass
        # A hook fires because it's registered in settings.json OR reads its
        # payload from stdin. Registration wins over the leading-underscore
        # convention so a registered `_foo.py` is never mis-binned. Everything
        # else in hooks/ is an imported helper/library — no test_*.py or
        # top-level try/except required.
        if f in registered or STDIN_RE.search(body):
            hooks.append(f)
        else:
            helpers.append(f)

    test_norms = {norm(t) for t in os.listdir(TESTS) if t.startswith("test_")}

    # 1b coverage (real hooks only)
    untested = sorted(h for h in hooks if norm(h) not in test_norms)
    # 1c error handling (real hooks only)
    no_try = []
    for h in hooks:
        try:
            with open(f"{HOOKS}/{h}", encoding="utf-8") as handle:
                body = handle.read()
            if "try:" not in body:
                no_try.append(h)
        except OSError:
            no_try.append(f"{h} (read error)")

    warn = bool(
        untested
        or no_try
        or schema_problems
        or disabled_plugin_hooks
        or unknown_plugin_hooks
    )
    plugin_error_message = (
        f"PLUGIN HOOK INVENTORY INCOMPLETE ({len(plugin_errors)}) — "
        + "; ".join(plugin_errors[:5])
        if plugin_errors
        else ""
    )
    schema_message = (
        f"INVALID HOOK MATCHER ({len(schema_problems)}) — a schema-invalid matcher "
        f"SILENTLY DISABLES ALL settings.json hooks (#75071/#75081): "
        + "; ".join(schema_problems[:5])
        if schema_problems
        else ""
    )
    disabled_message = ""
    if disabled_plugin_hooks:
        evidence = "; ".join(
            f"{hook['plugin']}:{hook['event']} ({hook['source']})"
            for hook in disabled_plugin_hooks[:5]
        )
        disabled_message = (
            f"DISABLED PLUGIN HOOKS ({len(disabled_plugin_hooks)}) — definitions "
            f"may remain active despite enabledPlugins or /hooks state (#85893): {evidence}"
        )
    unknown_message = ""
    if unknown_plugin_hooks:
        evidence = "; ".join(
            f"{hook['plugin']}:{hook['event']} ({hook['state_source']}; "
            f"{hook['source']})"
            for hook in unknown_plugin_hooks[:5]
        )
        unknown_message = (
            f"UNKNOWN PLUGIN HOOK STATE ({len(unknown_plugin_hooks)}) — definitions "
            f"were inventoried but enabledPlugins precedence could not be resolved: "
            f"{evidence}"
        )

    primary = (
        plugin_error_message or schema_message or disabled_message or unknown_message
    )
    if primary:
        # The most severe issue prints first so _check_all's one-line capture
        # cannot misreport an incomplete/disabled stack as clean.
        print(primary)

    if plugin_errors:
        if schema_message:
            print(schema_message)
        if disabled_message:
            print(disabled_message)
        if unknown_message:
            print(unknown_message)
    elif schema_message and primary != schema_message:
        print(schema_message)
    if disabled_message and primary != disabled_message and not plugin_errors:
        print(disabled_message)
    if unknown_message and primary != unknown_message and not plugin_errors:
        print(unknown_message)
    print(
        f"Hook coverage: {len(hooks) - len(untested)}/{len(hooks)} hooks have tests "
        f"({len(helpers)} helper modules excluded)"
    )
    for u in untested:
        print(f"    untested hook: {u}")
    print(
        f"Hook error handling: {'PASS' if not no_try else 'WARN'} — "
        f"{len(hooks) - len(no_try)}/{len(hooks)} crash-safe"
    )
    for h in no_try:
        print(f"    missing try/except: {h}")
    if helpers:
        print(f"    (helpers excluded: {', '.join(helpers)})")
    if not plugin_errors and not disabled_plugin_hooks and not unknown_plugin_hooks:
        if plugin_hooks:
            print(
                f"Plugin hooks: PASS — {len(plugin_hooks)} installed definition(s) "
                "independently inventoried"
            )
        else:
            print("Plugin hooks: PASS — 0 installed definitions")
    if plugin_errors:
        return 2
    return 1 if warn else 0


if __name__ == "__main__":
    sys.exit(main())
