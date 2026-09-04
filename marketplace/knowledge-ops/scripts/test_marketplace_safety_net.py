"""The safety-net bundle wires bash-pretooluse-dispatcher.py and ships what it runs.

scripts/build-marketplace.py registers the safety-net hooks from its PLUGINS
manifest. At IMPORT it prunes any registration whose script is not in the plugin's
file list -- loudly on the console, silently for an adopter, who would install a
safety-net with no Bash guard at all. So these tests read the manifest AFTER that
prune and pin the shape the bundle must have. They do not run the builder (bundles
are regenerated on merge); the import-containment check below is the builder's own
gate applied to the source files the manifest names.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = "bash-pretooluse-dispatcher.py"


@pytest.fixture(scope="module")
def builder():
    spec = importlib.util.spec_from_file_location("build_marketplace", ROOT / "scripts" / "build-marketplace.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def safety_net(builder) -> dict:
    return next(plugin for plugin in builder.PLUGINS if plugin["name"] == "safety-net")


def _registrations(plugin: dict) -> set[tuple[str, str, str, int]]:
    return {
        (event, group.get("matcher", ""), handler["args"][-1], handler["timeout"])
        for event, groups in plugin["hooks"].items()
        for group in groups
        for handler in group["hooks"]
    }


def _shipped_hooks(plugin: dict) -> dict[str, str]:
    """dest basename -> source path for everything the bundle puts under hooks/."""
    return {dest.split("/")[-1]: src for src, dest in plugin["files"] if dest.startswith("hooks/")}


def _hosted_by_dispatcher() -> list[str]:
    text = (ROOT / "hooks" / DISPATCHER).read_text(encoding="utf-8")
    return re.findall(r'\(\s*"[a-z0-9_-]+"\s*,\s*"([a-z0-9_-]+\.py)"\s*,\s*"(?:closed|warn|open)"\s*\)', text)


def test_safety_net_registers_the_dispatcher_not_the_guards(safety_net):
    registrations = _registrations(safety_net)
    assert ("PreToolUse", "Bash|PowerShell", DISPATCHER, 30) in registrations, registrations
    scripts = {script for _event, _matcher, script, _timeout in registrations}
    assert not scripts & {"bash-security-guard.py", "destructive-ops-guard.py"}, (
        "the guards run inside the dispatcher; registering them too would run them twice"
    )
    # The other two starter registrations are untouched.
    assert ("PreToolUse", "Write|Edit", "config-guard.py", 30) in registrations
    assert ("PostToolUse", "mcp__.*", "result-injection-guard.py", 30) in registrations


def test_safety_net_ships_the_dispatcher_with_every_hook_it_runs(safety_net):
    shipped = _shipped_hooks(safety_net)
    hosted = _hosted_by_dispatcher()
    assert len(hosted) == 6, hosted
    missing = [name for name in (DISPATCHER, *hosted, "run-hook") if name not in shipped]
    assert missing == [], f"safety-net file list lacks {missing}"
    for _event, _matcher, script, _timeout in _registrations(safety_net):
        assert script in shipped, f"registered but not shipped: {script}"


def test_safety_net_hook_imports_are_satisfied_inside_the_bundle(builder, safety_net):
    """check_hook_import_containment() runs against the BUILT tree; apply the same
    rule to the sources the manifest names so the gate is known to pass before the
    bundles are regenerated."""
    local_modules = {p.stem for p in (ROOT / "hooks").glob("*.py")}
    shipped = _shipped_hooks(safety_net)
    shipped_modules = {Path(name).stem for name in shipped if name.endswith(".py")}
    problems = []
    for name, src in shipped.items():
        if not name.endswith(".py"):
            continue
        text = (ROOT / src).read_text(encoding="utf-8", errors="ignore")
        for module in builder._IMPORT_RE.findall(text):
            if module in local_modules and module not in shipped_modules:
                problems.append((name, module))
    assert problems == [], problems
