"""Credential resolution must survive a Keychain rename, and an unrunnable
round count must fail before the run spends anything."""

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _keychain():
    return _load("roundtable_keychain_under_test", SCRIPTS / "keychain.py")


def _harness():
    sys.path.insert(0, str(SCRIPTS / "adapters"))
    sys.path.insert(0, str(SCRIPTS))
    return _load("roundtable_harness_rounds", SCRIPTS / "harness.py")


# --- credential resolution -------------------------------------------------


def test_openai_resolves_from_renamed_item_when_legacy_name_absent(monkeypatch):
    """The 2026-08-04 rename regression: OPENAI_API_KEY the ITEM is gone, so a
    lookup keyed on the env-var name finds nothing and silently drops the GPT
    arm. Only OPENAI_PLATFORM_API exists on the host."""
    kc = _keychain()
    present = {"OPENAI_PLATFORM_API": "sk-live-value"}
    asked = []

    def fake_read(service):
        asked.append(service)
        return present.get(service)

    monkeypatch.setattr(kc, "_read_keychain_item", fake_read)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    statuses = kc.load_keys(["OPENAI_API_KEY"])

    import os
    assert os.environ["OPENAI_API_KEY"] == "sk-live-value"
    # Proves the resolver tried the CURRENT name, i.e. it is not env-var-keyed.
    assert "OPENAI_PLATFORM_API" in asked
    assert "OPENAI_PLATFORM_API" in statuses[0]
    # The value must never appear in a printable status line.
    assert "sk-live-value" not in statuses[0]


def test_admin_items_are_never_candidates():
    """Admin keys authenticate the Admin/Compliance surfaces, not inference. A
    panel arm falling back to one would run under a credential whose scope the
    protocol never intended."""
    kc = _keychain()
    for candidates in kc.KEY_CANDIDATES.values():
        for service in candidates:
            assert "ADMIN" not in service.upper(), service


def test_existing_env_value_is_not_overwritten(monkeypatch):
    kc = _keychain()

    def fake_read(service):
        raise AssertionError(f"Keychain must not be consulted; asked for {service}")

    monkeypatch.setattr(kc, "_read_keychain_item", fake_read)
    monkeypatch.setenv("XAI_API_KEY", "operator-supplied")

    statuses = kc.load_keys(["XAI_API_KEY"])

    import os
    assert os.environ["XAI_API_KEY"] == "operator-supplied"
    assert "already set in env" in statuses[0]


def test_unresolved_required_key_is_reported(monkeypatch):
    kc = _keychain()
    monkeypatch.setattr(kc, "_read_keychain_item", lambda _service: None)
    for name in kc.REQUIRED_KEYS:
        monkeypatch.delenv(name, raising=False)

    statuses = kc.load_keys(list(kc.REQUIRED_KEYS))

    assert kc.missing_required() == list(kc.REQUIRED_KEYS)
    # The failure must name what was actually checked, so an operator can fix it.
    assert "OPENAI_PLATFORM_API" in " ".join(statuses)


def test_post_processing_keys_are_optional_not_required():
    """VOYAGE_API_KEY (--auto-stop embedding) and TAVILY_API_KEY
    (validate_claims.py) are post-processing keys. Their absence must not abort
    a panel run — only a missing ARM key may do that."""
    kc = _keychain()
    for optional in ("VOYAGE_API_KEY", "TAVILY_API_KEY"):
        assert optional in kc.KEY_CANDIDATES, optional
        assert optional not in kc.REQUIRED_KEYS, optional


def test_synthesis_needs_only_the_anthropic_key():
    """synthesize.py dispatches the Anthropic arm alone, so requiring all three
    panel keys would block synthesis of an already-paid-for run."""
    kc = _keychain()
    assert kc.SYNTHESIS_KEYS == ("ANTHROPIC_API_KEY",)
    for key in kc.SYNTHESIS_KEYS:
        assert key in kc.KEY_CANDIDATES


# --- round ceiling ---------------------------------------------------------


def test_round_ceiling_matches_templates_actually_on_disk():
    """Derived, not pinned: compare against the templates present, so adding a
    round_6_main.md raises the ceiling without touching this test."""
    harness = _harness()
    templates = harness.TEMPLATES_DIR
    expected = 1
    while True:
        nxt = expected + 1
        name = "round_2_critique.md" if nxt == 2 else f"round_{nxt}_main.md"
        if not (templates / name).is_file():
            break
        expected = nxt
    assert harness.round_ceiling() == expected
    assert expected >= 3, "protocol needs at least 3 rounds of templates"


def test_round_ceiling_is_read_from_disk_not_hardcoded(monkeypatch, tmp_path):
    """A truncated template set must lower the ceiling. If the ceiling were a
    literal 5, this passes while the harness still crashes mid-run."""
    harness = _harness()
    (tmp_path / "round_2_critique.md").write_text("x", encoding="utf-8")
    (tmp_path / "round_3_main.md").write_text("x", encoding="utf-8")
    # round_4_main.md deliberately absent
    monkeypatch.setattr(harness, "TEMPLATES_DIR", tmp_path)

    assert harness.round_ceiling() == 3


def test_ceiling_of_one_when_no_templates_exist(monkeypatch, tmp_path):
    harness = _harness()
    monkeypatch.setattr(harness, "TEMPLATES_DIR", tmp_path)
    assert harness.round_ceiling() == 1


# --- budget accounting ------------------------------------------------------


def test_prereg_phase_cost_is_accumulated_not_discarded():
    """total_cost is the variable --budget is enforced against, so a discarded
    prereg return value makes the budget guard blind to real spend.

    Structural (AST) rather than textual: it asserts the prereg run_phase call's
    result is BOUND, which a comment mentioning the bug cannot satisfy.
    Measured 2026-08-30: 6 prereg calls were $1.24 of $5.45 actual spend while
    the harness reported $4.22.
    """
    import ast

    source = (SCRIPTS / "harness.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    prereg_calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name != "run_phase":
            continue
        # Identify the prereg call by its literal phase argument.
        for arg in node.args:
            if isinstance(arg, ast.Constant) and arg.value == "prereg":
                prereg_calls.append(node)
                break

    assert prereg_calls, "no run_phase(..., 'prereg', ...) call found"

    # Every prereg call must have its return value bound to something.
    bound_calls = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for sub in ast.walk(node):
                if sub in prereg_calls:
                    bound_calls.add(id(sub))

    unbound = [c for c in prereg_calls if id(c) not in bound_calls]
    assert not unbound, (
        f"{len(unbound)} prereg run_phase call(s) discard the returned cost; "
        "prereg spend would not count toward --budget"
    )

    # And the bound cost must actually be added to the running total.
    assert "total_cost += prereg_cost" in source, (
        "prereg cost is captured but never added to total_cost"
    )
