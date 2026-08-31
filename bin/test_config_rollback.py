#!/usr/bin/env python3
"""Tests for the config snapshot/rollback tool.

All tests run against a DISPOSABLE temporary config root. Nothing here touches
the live ~/.claude checkout -- that is a hard requirement of the remediation, and
a test that violated it would be the exact hazard the tool guards against.

Run: pytest bin/test_config_rollback.py -q
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys

import config_rollback as cr
import pytest


@pytest.fixture()
def env(tmp_path):
    """A disposable config root, sibling app state, and snapshot store."""
    root = tmp_path / "cfg"
    (root / "hooks").mkdir(parents=True)
    (root / "agents").mkdir(parents=True)
    (root / "settings.json").write_text(
        json.dumps({"env": {"A": "1"}, "hooks": {}}), encoding="utf-8"
    )
    (root / "hooks" / "guard.py").write_text("print('v1')\n", encoding="utf-8")
    (root / "agents" / "worker.md").write_text("v1\n", encoding="utf-8")
    state_file = tmp_path / ".claude.json"
    state_file.write_text(
        json.dumps({"mcpServers": {"example": {"command": "disposable"}}}),
        encoding="utf-8",
    )
    store = tmp_path / "snaps"
    return {
        "root": str(root),
        "state_file": str(state_file),
        "store": str(store),
        "repo": str(tmp_path),
    }


def ns(env, **kw):
    import argparse

    base = {
        "store": env["store"],
        "root": env["root"],
        "state_file": env["state_file"],
        "repo": env["repo"],
        "id": None,
        "confirm": False,
    }
    base.update(kw)
    return argparse.Namespace(**base)


def test_common_options_parse_identically_before_or_after_subcommand(env, monkeypatch):
    captured = []

    def capture(args):
        captured.append(
            (args.store, args.root, args.state_file, args.repo, args.cmd)
        )
        return 0

    monkeypatch.setattr(cr, "cmd_list", capture)
    common = [
        "--store",
        env["store"],
        "--root",
        env["root"],
        "--state-file",
        env["state_file"],
        "--repo",
        env["repo"],
    ]

    assert cr.main([*common, "list"]) == 0
    assert cr.main(["list", *common]) == 0
    assert captured == [
        (env["store"], env["root"], env["state_file"], env["repo"], "list"),
        (env["store"], env["root"], env["state_file"], env["repo"], "list"),
    ]


def test_restore_mapping_rejects_dot_dot_segments(env):
    with pytest.raises(ValueError, match="unsafe snapshot path"):
        cr.restore_destination(ns(env), "hooks/../settings.json")


def test_snapshot_captures_protected_files(env):
    rc = cr.cmd_snapshot(ns(env, id="s1"))
    assert rc == 0
    manifest = json.loads(
        (open(os.path.join(env["store"], "s1", "manifest.json"), encoding="utf-8")).read()
    )
    assert "settings.json" in manifest["files"]
    assert os.path.join("hooks", "guard.py").replace("\\", "/") in {
        k.replace("\\", "/") for k in manifest["files"]
    }
    # Each file records a content hash so "known good" is content-pinned.
    assert all("sha256" in v for v in manifest["files"].values())


def test_snapshot_cli_captures_global_app_state(env):
    rc = cr.main(
        [
            "snapshot",
            "--id",
            "s1",
            "--store",
            env["store"],
            "--root",
            env["root"],
            "--state-file",
            env["state_file"],
            "--repo",
            env["repo"],
        ]
    )

    assert rc == 0
    manifest = json.load(
        open(os.path.join(env["store"], "s1", "manifest.json"), encoding="utf-8")
    )
    logical_path = "global-app-state/claude.json"
    assert logical_path in manifest["files"]
    snap_copy = os.path.join(env["store"], "s1", "files", logical_path)
    assert json.load(open(snap_copy, encoding="utf-8"))["mcpServers"]["example"]


def test_snapshot_refuses_symlink_global_state_source(env):
    os.remove(env["state_file"])
    outside_target = os.path.join(os.path.dirname(env["state_file"]), "outside.json")
    with open(outside_target, "w", encoding="utf-8") as fh:
        fh.write('{"outside":true}')
    os.symlink(outside_target, env["state_file"])

    rc = cr.cmd_snapshot(ns(env, id="s1"))

    assert rc == 2
    assert not os.path.exists(os.path.join(env["store"], "s1"))
    assert open(outside_target, encoding="utf-8").read() == '{"outside":true}'


def test_global_state_appearing_at_atomic_open_is_captured_once(env, monkeypatch):
    os.remove(env["state_file"])
    original_open = cr._open_regular_no_follow
    appeared = False

    def appear_before_atomic_open(path, **kwargs):
        nonlocal appeared
        if os.fspath(path) == env["state_file"] and not appeared:
            with open(env["state_file"], "w", encoding="utf-8") as fh:
                fh.write('{"appeared":"at classification"}')
            appeared = True
        return original_open(path, **kwargs)

    monkeypatch.setattr(cr, "_open_regular_no_follow", appear_before_atomic_open)

    assert cr.cmd_snapshot(ns(env, id="s1")) == 0
    manifest = json.load(
        open(os.path.join(env["store"], "s1", "manifest.json"), encoding="utf-8")
    )
    assert appeared is True
    assert cr.GLOBAL_APP_STATE_LOGICAL in manifest["files"]
    assert cr.GLOBAL_APP_STATE_LOGICAL not in manifest["absent_files"]


def test_global_state_disappearing_at_atomic_open_is_recorded_absent(
    env, monkeypatch
):
    original_open = cr._open_regular_no_follow
    disappeared = False

    def disappear_before_atomic_open(path, **kwargs):
        nonlocal disappeared
        if os.fspath(path) == env["state_file"] and not disappeared:
            os.remove(env["state_file"])
            disappeared = True
        return original_open(path, **kwargs)

    monkeypatch.setattr(cr, "_open_regular_no_follow", disappear_before_atomic_open)

    assert cr.cmd_snapshot(ns(env, id="s1")) == 0
    manifest = json.load(
        open(os.path.join(env["store"], "s1", "manifest.json"), encoding="utf-8")
    )
    assert disappeared is True
    assert cr.GLOBAL_APP_STATE_LOGICAL not in manifest["files"]
    assert manifest["absent_files"] == [cr.GLOBAL_APP_STATE_LOGICAL]


def test_secure_snapshot_copy_hashes_the_same_open_descriptor(tmp_path, monkeypatch):
    source = tmp_path / "source.json"
    target = tmp_path / "snapshot" / "source.json"
    original = b'{"trusted":"opened descriptor"}'
    tampered = b'{"attacker":"replacement path"}'
    source.write_bytes(original)
    open_regular = cr._open_regular_no_follow
    swapped = False

    def swap_path_after_open(path, **kwargs):
        nonlocal swapped
        descriptor, opened_stat = open_regular(path, **kwargs)
        if os.fspath(path) == os.fspath(source) and not swapped:
            replacement = tmp_path / "replacement.json"
            replacement.write_bytes(tampered)
            os.replace(replacement, source)
            swapped = True
        return descriptor, opened_stat

    monkeypatch.setattr(cr, "_open_regular_no_follow", swap_path_after_open)

    digest = cr._copy_source_to_snapshot(str(source), str(target))

    assert swapped is True
    assert target.read_bytes() == original
    assert digest == hashlib.sha256(original).hexdigest()


def test_snapshot_refuses_source_beneath_symlinked_descendant_parent(
    env, monkeypatch
):
    outside_dir = os.path.join(os.path.dirname(env["root"]), "outside-hooks")
    os.mkdir(outside_dir)
    outside_file = os.path.join(outside_dir, "guard.py")
    with open(outside_file, "w", encoding="utf-8") as fh:
        fh.write("outside must not be captured\n")
    linked_parent = os.path.join(env["root"], "linked-hooks")
    os.symlink(outside_dir, linked_parent)
    original_iter = cr.iter_files

    def inject_parent_symlink_source(root):
        yield from original_iter(root)
        yield os.path.join(linked_parent, "guard.py"), "hooks/injected.py"

    monkeypatch.setattr(cr, "iter_files", inject_parent_symlink_source)

    assert cr.cmd_snapshot(ns(env, id="s1")) == 2
    assert not os.path.lexists(os.path.join(env["store"], "s1"))


def test_secure_snapshot_copy_verifies_the_stored_copy(tmp_path, monkeypatch):
    source = tmp_path / "source.json"
    target = tmp_path / "snapshot" / "source.json"
    source.write_bytes(b'{"trusted":true}')
    real_fsync = os.fsync
    tampered = False

    def tamper_target_after_fsync(descriptor):
        nonlocal tampered
        real_fsync(descriptor)
        if not tampered:
            target.write_bytes(b'{"tampered":true}')
            tampered = True

    monkeypatch.setattr(os, "fsync", tamper_target_after_fsync)

    with pytest.raises(OSError, match="stored snapshot verification failed"):
        cr._copy_source_to_snapshot(str(source), str(target))

    assert tampered is True
    assert not target.exists()


def test_snapshot_fails_closed_when_source_becomes_symlink_after_enumeration(
    env, monkeypatch
):
    outside = os.path.join(os.path.dirname(env["state_file"]), "outside.json")
    with open(outside, "w", encoding="utf-8") as fh:
        fh.write('{"outside":"must not be captured"}')
    original_open = cr._open_regular_no_follow
    swapped = False

    def swap_global_state(path, **kwargs):
        nonlocal swapped
        if os.fspath(path) == env["state_file"] and not swapped:
            os.remove(path)
            os.symlink(outside, path)
            swapped = True
        return original_open(path, **kwargs)

    monkeypatch.setattr(cr, "_open_regular_no_follow", swap_global_state)

    rc = cr.cmd_snapshot(ns(env, id="s1"))

    assert rc == 2
    assert swapped is True
    assert not os.path.lexists(os.path.join(env["store"], "s1"))
    assert open(outside, encoding="utf-8").read() == (
        '{"outside":"must not be captured"}'
    )


def test_diff_reports_changed_global_app_state_without_contents(env, capsys):
    cr.cmd_snapshot(ns(env, id="s1"))
    secret_marker = "diff-secret-marker"
    with open(env["state_file"], "w", encoding="utf-8") as fh:
        fh.write('{"token":"' + secret_marker + '"}')

    assert cr.cmd_diff(ns(env, id="s1")) == 0
    output = capsys.readouterr().out

    assert "M global-app-state/claude.json" in output
    assert secret_marker not in output


def test_snapshot_refuses_to_overwrite(env):
    assert cr.cmd_snapshot(ns(env, id="s1")) == 0
    # A second snapshot under the same id must fail rather than silently clobber
    # the known-good reference point.
    assert cr.cmd_snapshot(ns(env, id="s1")) == 2


def test_snapshot_refuses_preexisting_broken_symlink_slot_without_traceback(
    env, capsys
):
    os.makedirs(env["store"])
    snapshot_slot = os.path.join(env["store"], "s1")
    outside = os.path.join(os.path.dirname(env["store"]), "missing-outside")
    os.symlink(outside, snapshot_slot)

    assert cr.cmd_snapshot(ns(env, id="s1")) == 2
    assert os.path.islink(snapshot_slot)
    assert not os.path.lexists(outside)
    assert "refusing to overwrite" in capsys.readouterr().err


def test_snapshot_fails_closed_if_new_store_is_replaced_after_slot_creation(
    env, monkeypatch
):
    """All snapshot writes stay on the store/slot descriptors we created."""

    outside_store = os.path.join(os.path.dirname(env["store"]), "outside-store")
    parked_store = os.path.join(os.path.dirname(env["store"]), "parked-store")
    os.mkdir(outside_store)
    original_iter = cr.iter_files
    swapped = False

    def replace_store_before_first_copy(root):
        nonlocal swapped
        os.rename(env["store"], parked_store)
        os.symlink(outside_store, env["store"])
        swapped = True
        yield from original_iter(root)

    monkeypatch.setattr(cr, "iter_files", replace_store_before_first_copy)

    assert cr.cmd_snapshot(ns(env, id="s1")) == 2
    assert swapped is True
    assert os.path.islink(env["store"])
    assert not os.path.lexists(os.path.join(outside_store, "s1"))
    assert not os.path.lexists(os.path.join(parked_store, "s1"))


def test_snapshot_fails_closed_if_store_is_replaced_between_mkdir_and_open(
    env, monkeypatch
):
    outside_store = os.path.join(os.path.dirname(env["store"]), "outside-store")
    parked_store = os.path.join(os.path.dirname(env["store"]), "parked-store")
    os.mkdir(outside_store)
    original_mkdir = os.mkdir
    swapped = False

    def replace_store_after_mkdir(path, *args, **kwargs):
        nonlocal swapped
        result = original_mkdir(path, *args, **kwargs)
        if not swapped and os.path.lexists(env["store"]):
            candidate = os.fspath(path)
            if candidate == env["store"] or candidate == os.path.basename(env["store"]):
                os.rename(env["store"], parked_store)
                os.symlink(outside_store, env["store"])
                swapped = True
        return result

    monkeypatch.setattr(os, "mkdir", replace_store_after_mkdir)
    monkeypatch.setattr(cr, "_supports_no_follow_directory_fds", lambda: True)

    assert cr.cmd_snapshot(ns(env, id="s1")) == 2
    assert swapped is True
    assert os.path.islink(env["store"])
    assert not os.path.lexists(os.path.join(outside_store, "s1"))


def test_snapshot_fails_closed_if_new_slot_is_replaced_before_first_copy(
    env, monkeypatch
):
    outside_slot = os.path.join(os.path.dirname(env["store"]), "outside-slot")
    parked_slot = os.path.join(env["store"], "parked-s1")
    os.mkdir(env["store"])
    os.mkdir(outside_slot)
    original_iter = cr.iter_files
    swapped = False

    def replace_slot_before_first_copy(root):
        nonlocal swapped
        os.rename(os.path.join(env["store"], "s1"), parked_slot)
        os.symlink(outside_slot, os.path.join(env["store"], "s1"))
        swapped = True
        yield from original_iter(root)

    monkeypatch.setattr(cr, "iter_files", replace_slot_before_first_copy)

    assert cr.cmd_snapshot(ns(env, id="s1")) == 2
    assert swapped is True
    assert os.path.islink(os.path.join(env["store"], "s1"))
    assert os.listdir(outside_slot) == []
    assert os.listdir(parked_slot) == []


def test_snapshot_fails_closed_if_slot_is_replaced_between_mkdir_and_open(
    env, monkeypatch
):
    outside_slot = os.path.join(os.path.dirname(env["store"]), "outside-slot")
    parked_slot = os.path.join(env["store"], "parked-s1")
    os.mkdir(env["store"])
    os.mkdir(outside_slot)
    original_mkdir = os.mkdir
    slot_path = os.path.join(env["store"], "s1")
    swapped = False

    def replace_slot_after_mkdir(path, *args, **kwargs):
        nonlocal swapped
        result = original_mkdir(path, *args, **kwargs)
        if not swapped and os.path.lexists(slot_path):
            candidate = os.fspath(path)
            if candidate == slot_path or candidate == "s1":
                os.rename(slot_path, parked_slot)
                os.symlink(outside_slot, slot_path)
                swapped = True
        return result

    monkeypatch.setattr(os, "mkdir", replace_slot_after_mkdir)
    monkeypatch.setattr(cr, "_supports_no_follow_directory_fds", lambda: True)

    assert cr.cmd_snapshot(ns(env, id="s1")) == 2
    assert swapped is True
    assert os.path.islink(slot_path)
    assert os.listdir(outside_slot) == []


def test_snapshot_fails_closed_if_files_directory_is_replaced_before_copy(
    env, monkeypatch
):
    outside_files = os.path.join(os.path.dirname(env["store"]), "outside-files")
    parked_files = os.path.join(env["store"], "s1", "parked-files")
    os.mkdir(outside_files)
    original_iter = cr.iter_files
    swapped = False

    def replace_files_before_first_copy(root):
        nonlocal swapped
        files_path = os.path.join(env["store"], "s1", "files")
        if not os.path.lexists(files_path):
            os.mkdir(files_path)
        os.rename(files_path, parked_files)
        os.symlink(outside_files, files_path)
        swapped = True
        yield from original_iter(root)

    monkeypatch.setattr(cr, "iter_files", replace_files_before_first_copy)

    assert cr.cmd_snapshot(ns(env, id="s1")) == 2
    assert swapped is True
    assert os.listdir(outside_files) == []
    assert not os.path.lexists(os.path.join(env["store"], "s1"))


def test_snapshot_fails_closed_if_files_is_replaced_between_mkdir_and_open(
    env, monkeypatch
):
    outside_files = os.path.join(os.path.dirname(env["store"]), "outside-files")
    files_path = os.path.join(env["store"], "s1", "files")
    parked_files = os.path.join(env["store"], "s1", "parked-files")
    os.mkdir(outside_files)
    original_mkdir = os.mkdir
    swapped = False

    def replace_files_after_mkdir(path, *args, **kwargs):
        nonlocal swapped
        result = original_mkdir(path, *args, **kwargs)
        if not swapped and os.path.lexists(files_path):
            candidate = os.fspath(path)
            if candidate == files_path or candidate == "files":
                os.rename(files_path, parked_files)
                os.symlink(outside_files, files_path)
                swapped = True
        return result

    monkeypatch.setattr(os, "mkdir", replace_files_after_mkdir)
    monkeypatch.setattr(cr, "_supports_no_follow_directory_fds", lambda: True)

    assert cr.cmd_snapshot(ns(env, id="s1")) == 2
    assert swapped is True
    assert os.listdir(outside_files) == []


def test_snapshot_fails_closed_without_secure_directory_fd_primitives(
    env, monkeypatch, capsys
):
    monkeypatch.setattr(cr, "_supports_no_follow_directory_fds", lambda: False)

    assert cr.cmd_snapshot(ns(env, id="s1")) == 2
    assert not os.path.lexists(env["store"])
    assert "secure atomic snapshot creation is unavailable" in capsys.readouterr().err


def test_unique_pre_restore_id_skips_broken_symlink_slot(env):
    os.makedirs(env["store"])
    base = "pre-restore-fixed"
    os.symlink(
        os.path.join(os.path.dirname(env["store"]), "missing"),
        os.path.join(env["store"], base),
    )

    assert cr.unique_snapshot_id(env["store"], base) == f"{base}-2"


@pytest.mark.parametrize(
    "snapshot_id",
    ["../escaped", "subdir/snapshot", "subdir\\snapshot", ".", ""],
)
def test_snapshot_ids_cannot_escape_or_alias_the_store(env, snapshot_id, capsys):
    outside = os.path.join(os.path.dirname(env["store"]), "escaped")

    rc = cr.cmd_snapshot(ns(env, id=snapshot_id))

    assert rc == 2
    assert not os.path.lexists(outside)
    assert "invalid snapshot id" in capsys.readouterr().err


def test_restore_rejects_snapshot_id_that_resolves_outside_store(env, capsys):
    rc = cr.cmd_restore(ns(env, id="../escaped", confirm=True))

    assert rc == 2
    assert "invalid snapshot id" in capsys.readouterr().err


def test_restore_rejects_snapshot_directory_symlinked_outside_store(env, tmp_path):
    outside_store = tmp_path / "outside-store"
    outside_env = dict(env)
    outside_env["store"] = str(outside_store)
    assert cr.cmd_snapshot(ns(outside_env, id="s1")) == 0
    os.makedirs(env["store"])
    os.symlink(outside_store / "s1", os.path.join(env["store"], "s1"))
    guard = os.path.join(env["root"], "hooks", "guard.py")
    live_before = "print('live must not trust external snapshot')\n"
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write(live_before)

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 2
    with open(guard, encoding="utf-8") as fh:
        assert fh.read() == live_before


def test_restore_uses_anchored_snapshot_after_slot_swap(env, tmp_path, monkeypatch):
    assert cr.cmd_snapshot(ns(env, id="s1")) == 0
    guard = os.path.join(env["root"], "hooks", "guard.py")

    outside_store = tmp_path / "outside-store"
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write("print('attacker snapshot')\n")
    outside_env = dict(env, store=str(outside_store))
    assert cr.cmd_snapshot(ns(outside_env, id="s1")) == 0

    live_before = "print('live before restore')\n"
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write(live_before)

    slot = os.path.join(env["store"], "s1")
    parked = os.path.join(env["store"], "original-s1")
    original_lstat = os.lstat
    original_open = os.open
    swapped = False

    def swap_slot_once():
        nonlocal swapped
        if not swapped:
            os.rename(slot, parked)
            os.symlink(outside_store / "s1", slot)
            swapped = True

    def swapping_lstat(path, *args, **kwargs):
        result = original_lstat(path, *args, **kwargs)
        if os.fspath(path) == slot:
            swap_slot_once()
        return result

    def swapping_open(path, flags, *args, **kwargs):
        descriptor = original_open(path, flags, *args, **kwargs)
        if (
            os.fspath(path) == "s1"
            and kwargs.get("dir_fd") is not None
            and flags & getattr(os, "O_DIRECTORY", 0)
        ):
            swap_slot_once()
        return descriptor

    monkeypatch.setattr(os, "lstat", swapping_lstat)
    monkeypatch.setattr(os, "open", swapping_open)
    monkeypatch.setattr(cr, "_supports_no_follow_directory_fds", lambda: True)

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 0
    assert swapped is True
    assert open(guard, encoding="utf-8").read() == "print('v1')\n"


def test_snapshot_excludes_pycache(env):
    cache = os.path.join(env["root"], "hooks", "__pycache__")
    os.makedirs(cache)
    with open(os.path.join(cache, "x.pyc"), "w", encoding="utf-8") as fh:
        fh.write("junk")
    cr.cmd_snapshot(ns(env, id="s1"))
    manifest = json.load(
        open(os.path.join(env["store"], "s1", "manifest.json"), encoding="utf-8")
    )
    assert not any("__pycache__" in k for k in manifest["files"])


def test_restore_is_a_dry_run_without_confirm(env):
    cr.cmd_snapshot(ns(env, id="s1"))
    guard = os.path.join(env["root"], "hooks", "guard.py")
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write("print('v2-MODIFIED')\n")

    rc = cr.cmd_restore(ns(env, id="s1", confirm=False))
    assert rc == 1, "dry run must be non-zero so a caller cannot mistake it for applied"
    # The modification must still be present -- nothing was written.
    assert "MODIFIED" in open(guard, encoding="utf-8").read()


def test_restore_fails_before_snapshot_or_mutation_without_secure_dirfds(
    env, monkeypatch, capsys
):
    cr.cmd_snapshot(ns(env, id="s1"))
    guard = os.path.join(env["root"], "hooks", "guard.py")
    changed = "print('must remain changed')\n"
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write(changed)
    before_entries = sorted(os.listdir(env["store"]))
    monkeypatch.setattr(cr, "_supports_no_follow_directory_fds", lambda: False)

    rc = cr.cmd_restore(ns(env, id="s1", confirm=True))

    assert rc == 2
    assert open(guard, encoding="utf-8").read() == changed
    assert sorted(os.listdir(env["store"])) == before_entries
    assert "secure atomic restore is unavailable" in capsys.readouterr().err


def test_restore_fails_before_mutation_when_destination_cannot_hardlink(
    env, monkeypatch
):
    assert cr.cmd_snapshot(ns(env, id="s1")) == 0
    guard = os.path.join(env["root"], "hooks", "guard.py")
    live_before = "print('live survives unsupported hardlinks')\n"
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write(live_before)

    def fail_hardlink(*_args, **_kwargs):
        raise OSError("hardlinks unavailable")

    monkeypatch.setattr(cr, "_link_no_replace", fail_hardlink)

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 2
    assert open(guard, encoding="utf-8").read() == live_before
    assert not any(
        "config-rollback" in filename
        for directory, _, filenames in os.walk(env["root"])
        for filename in filenames
    )


def test_restore_reverts_a_modified_file(env):
    cr.cmd_snapshot(ns(env, id="s1"))
    guard = os.path.join(env["root"], "hooks", "guard.py")
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write("print('v2-MODIFIED')\n")

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 0
    assert open(guard, encoding="utf-8").read() == "print('v1')\n"


@pytest.mark.parametrize("failure_index", [1, 2])
def test_restore_write_failure_never_leaves_truncated_or_mixed_live_state(
    env, monkeypatch, capsys, failure_index
):
    cr.cmd_snapshot(ns(env, id="s1"))
    guard = os.path.join(env["root"], "hooks", "guard.py")
    worker = os.path.join(env["root"], "agents", "worker.md")
    live = {
        guard: "print('live guard must survive')\n",
        worker: "live worker must survive\n",
    }
    for path, content in live.items():
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)

    original_commit = getattr(cr, "_commit_staged_entry", None)
    calls = 0

    def fail_during_atomic_commit(entry):
        nonlocal calls
        calls += 1
        if calls == failure_index:
            raise OSError("injected write failure")
        assert original_commit is not None
        return original_commit(entry)

    monkeypatch.setattr(
        cr, "_commit_staged_entry", fail_during_atomic_commit, raising=False
    )

    rc = cr.cmd_restore(ns(env, id="s1", confirm=True))
    output = capsys.readouterr()

    assert rc == 2
    assert {path: open(path, encoding="utf-8").read() for path in live} == live
    assert "Undo with:" in output.out
    assert "injected write failure" not in output.out + output.err


def test_keyboard_interrupt_recovers_touched_files_cleans_debris_and_reraises(
    env, monkeypatch
):
    cr.cmd_snapshot(ns(env, id="s1"))
    guard = os.path.join(env["root"], "hooks", "guard.py")
    worker = os.path.join(env["root"], "agents", "worker.md")
    live = {
        guard: "print('live guard survives interrupt')\n",
        worker: "live worker survives interrupt\n",
    }
    for path, content in live.items():
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)

    original_commit = cr._commit_staged_entry
    calls = 0

    def interrupt_second_commit(entry):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt("injected operator interruption")
        return original_commit(entry)

    monkeypatch.setattr(cr, "_commit_staged_entry", interrupt_second_commit)

    with pytest.raises(KeyboardInterrupt, match="operator interruption"):
        cr.cmd_restore(ns(env, id="s1", confirm=True))

    assert calls == 2
    assert {path: open(path, encoding="utf-8").read() for path in live} == live
    assert not any(
        "config-rollback" in filename
        for directory, _, filenames in os.walk(env["root"])
        for filename in filenames
    )


def test_restore_recovers_when_rename_mutates_then_raises_baseexception(
    env, monkeypatch
):
    """Recovery infers syscall success even if Python never records it."""

    assert cr.cmd_snapshot(ns(env, id="s1")) == 0
    guard = os.path.join(env["root"], "hooks", "guard.py")
    live_before = "print('live survives post-syscall interruption')\n"
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write(live_before)

    original_rename = os.rename
    interrupted = False

    def rename_then_interrupt(src, dst, *args, **kwargs):
        nonlocal interrupted
        result = original_rename(src, dst, *args, **kwargs)
        if (
            not interrupted
            and kwargs.get("src_dir_fd") is not None
            and kwargs.get("dst_dir_fd") is not None
        ):
            interrupted = True
            raise KeyboardInterrupt("injected after successful rename")
        return result

    monkeypatch.setattr(os, "rename", rename_then_interrupt)
    monkeypatch.setattr(cr, "_supports_no_follow_directory_fds", lambda: True)

    with pytest.raises(KeyboardInterrupt, match="after successful rename"):
        cr.cmd_restore(ns(env, id="s1", confirm=True))

    assert interrupted is True
    assert open(guard, encoding="utf-8").read() == live_before
    assert not any(
        "config-rollback" in filename
        for directory, _, filenames in os.walk(env["root"])
        for filename in filenames
    )


def test_restore_recovers_when_link_mutates_then_raises_baseexception(
    env, monkeypatch
):
    assert cr.cmd_snapshot(ns(env, id="s1")) == 0
    guard = os.path.join(env["root"], "hooks", "guard.py")
    os.remove(guard)
    original_link = os.link
    interrupted = False

    def link_then_interrupt(src, dst, *args, **kwargs):
        nonlocal interrupted
        result = original_link(src, dst, *args, **kwargs)
        if not interrupted and os.fspath(dst) == "guard.py":
            interrupted = True
            raise KeyboardInterrupt("injected after successful link")
        return result

    monkeypatch.setattr(os, "link", link_then_interrupt)
    monkeypatch.setattr(cr, "_supports_no_follow_directory_fds", lambda: True)

    with pytest.raises(KeyboardInterrupt, match="after successful link"):
        cr.cmd_restore(ns(env, id="s1", confirm=True))

    assert interrupted is True
    assert not os.path.lexists(guard)
    assert not any(
        "config-rollback" in filename
        for directory, _, filenames in os.walk(env["root"])
        for filename in filenames
    )


def test_failed_restore_removes_parent_directories_created_only_for_staging(
    env, monkeypatch
):
    nested_dir = os.path.join(env["root"], "hooks", "nested")
    os.makedirs(nested_dir)
    nested_file = os.path.join(nested_dir, "guard.py")
    with open(nested_file, "w", encoding="utf-8") as fh:
        fh.write("protected nested file\n")
    cr.cmd_snapshot(ns(env, id="s1"))
    os.remove(nested_file)
    os.rmdir(nested_dir)

    def fail_commit(_entry):
        raise OSError("injected commit failure")

    monkeypatch.setattr(cr, "_commit_staged_entry", fail_commit)

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 2
    assert not os.path.lexists(nested_dir)


def test_restore_staging_fsync_failure_leaves_live_state_and_no_temp_files(
    env, monkeypatch, capsys
):
    cr.cmd_snapshot(ns(env, id="s1"))
    guard = os.path.join(env["root"], "hooks", "guard.py")
    live_before = "print('live survives staging disk failure')\n"
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write(live_before)

    original_snapshot = cr.cmd_snapshot
    original_fsync = os.fsync
    armed = False
    failed = False

    def arm_after_pre_restore_snapshot(args):
        nonlocal armed
        rc = original_snapshot(args)
        if rc == 0 and str(args.id).startswith("pre-restore-"):
            armed = True
        return rc

    def fail_first_transaction_fsync(descriptor):
        nonlocal failed
        if armed and not failed:
            failed = True
            raise OSError("injected disk sync failure")
        return original_fsync(descriptor)

    monkeypatch.setattr(cr, "cmd_snapshot", arm_after_pre_restore_snapshot)
    monkeypatch.setattr(os, "fsync", fail_first_transaction_fsync)

    rc = cr.cmd_restore(ns(env, id="s1", confirm=True))
    output = capsys.readouterr()

    assert rc == 2
    assert failed is True
    assert open(guard, encoding="utf-8").read() == live_before
    assert not any(
        "config-rollback" in name
        for directory in (
            os.path.join(env["root"], "hooks"),
            os.path.join(env["root"], "agents"),
        )
        for name in os.listdir(directory)
    )
    assert "Undo with:" in output.out
    assert "injected disk sync failure" not in output.out + output.err


def test_failed_tombstone_commit_recovers_prior_write_and_deleted_file(
    env, monkeypatch
):
    os.remove(env["state_file"])
    cr.cmd_snapshot(ns(env, id="s1"))
    guard = os.path.join(env["root"], "hooks", "guard.py")
    guard_before = "print('live guard')\n"
    state_before = '{"created":"after snapshot"}'
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write(guard_before)
    with open(env["state_file"], "w", encoding="utf-8") as fh:
        fh.write(state_before)

    original_commit = cr._commit_staged_entry
    calls = 0

    def fail_tombstone_commit(entry):
        nonlocal calls
        calls += 1
        if entry["remove"]:
            raise OSError("injected tombstone failure")
        return original_commit(entry)

    monkeypatch.setattr(cr, "_commit_staged_entry", fail_tombstone_commit)

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 2
    assert calls == 2
    assert open(guard, encoding="utf-8").read() == guard_before
    assert open(env["state_file"], encoding="utf-8").read() == state_before


def test_recovery_does_not_overwrite_edit_to_partially_committed_leaf(
    env, monkeypatch, capsys
):
    assert cr.cmd_snapshot(ns(env, id="s1")) == 0
    guard = os.path.join(env["root"], "hooks", "guard.py")
    worker = os.path.join(env["root"], "agents", "worker.md")
    for path, content in {
        guard: "live guard before restore\n",
        worker: "live worker before restore\n",
    }.items():
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)

    original_commit = cr._commit_staged_entry
    concurrent = "concurrent edit after partial commit\n"
    first_path = None
    calls = 0

    def fail_after_concurrent_edit(entry):
        nonlocal calls, first_path
        calls += 1
        if calls == 1:
            original_commit(entry)
            first_path = worker if entry["leaf"] == "worker.md" else guard
            with open(first_path, "w", encoding="utf-8") as fh:
                fh.write(concurrent)
            return
        raise OSError("injected later-entry failure")

    monkeypatch.setattr(cr, "_commit_staged_entry", fail_after_concurrent_edit)

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 2
    assert calls == 2
    assert first_path is not None
    assert open(first_path, encoding="utf-8").read() == concurrent
    assert "automatic recovery was incomplete" in capsys.readouterr().err


def test_restore_detects_v2_to_v3_mutation_after_staging(env, monkeypatch):
    assert cr.cmd_snapshot(ns(env, id="s1")) == 0
    guard = os.path.join(env["root"], "hooks", "guard.py")
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write("print('v2 before restore')\n")

    original_commit = cr._commit_staged_entry
    mutated = False

    def mutate_live_before_commit(entry):
        nonlocal mutated
        if not mutated:
            with open(guard, "w", encoding="utf-8") as fh:
                fh.write("print('v3 concurrent edit')\n")
            mutated = True
        return original_commit(entry)

    monkeypatch.setattr(cr, "_commit_staged_entry", mutate_live_before_commit)

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 2
    assert mutated is True
    assert open(guard, encoding="utf-8").read() == "print('v3 concurrent edit')\n"
    assert not any("config-rollback" in name for name in os.listdir(os.path.dirname(guard)))


def test_restore_compare_and_swap_preserves_edit_at_commit_boundary(
    env, monkeypatch
):
    assert cr.cmd_snapshot(ns(env, id="s1")) == 0
    guard = os.path.join(env["root"], "hooks", "guard.py")
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write("print('v2 before restore')\n")

    original_rename = os.rename
    concurrent = "print('v3 concurrent at commit')\n"
    injected = False

    def edit_immediately_before_first_commit_rename(src, dst, *args, **kwargs):
        nonlocal injected
        if (
            not injected
            and kwargs.get("src_dir_fd") is not None
            and kwargs.get("dst_dir_fd") is not None
        ):
            with open(guard, "w", encoding="utf-8") as fh:
                fh.write(concurrent)
            injected = True
        return original_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "rename", edit_immediately_before_first_commit_rename)
    monkeypatch.setattr(cr, "_supports_no_follow_directory_fds", lambda: True)

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 2
    assert injected is True
    assert open(guard, encoding="utf-8").read() == concurrent
    assert not any(
        "config-rollback" in name for name in os.listdir(os.path.dirname(guard))
    )


def test_restore_no_replace_preserves_file_created_at_publish_boundary(
    env, monkeypatch
):
    assert cr.cmd_snapshot(ns(env, id="s1")) == 0
    guard = os.path.join(env["root"], "hooks", "guard.py")
    os.remove(guard)
    concurrent = "print('created concurrently')\n"
    original_rename = os.rename
    original_link = os.link
    injected = False

    def create_before_publish(target):
        nonlocal injected
        if not injected and os.fspath(target) == "guard.py":
            with open(guard, "w", encoding="utf-8") as fh:
                fh.write(concurrent)
            injected = True

    def racing_rename(src, dst, *args, **kwargs):
        if kwargs.get("dst_dir_fd") is not None:
            create_before_publish(dst)
        return original_rename(src, dst, *args, **kwargs)

    def racing_link(src, dst, *args, **kwargs):
        if kwargs.get("dst_dir_fd") is not None:
            create_before_publish(dst)
        return original_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "rename", racing_rename)
    monkeypatch.setattr(os, "link", racing_link)
    monkeypatch.setattr(cr, "_supports_no_follow_directory_fds", lambda: True)

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 2
    assert injected is True
    assert open(guard, encoding="utf-8").read() == concurrent


def test_restore_claim_preserves_deletion_target_edited_at_commit_boundary(
    env, monkeypatch
):
    os.remove(env["state_file"])
    assert cr.cmd_snapshot(ns(env, id="s1")) == 0
    live_before = '{"created":"after snapshot"}'
    concurrent = '{"edited":"at deletion commit"}'
    with open(env["state_file"], "w", encoding="utf-8") as fh:
        fh.write(live_before)

    original_rename = os.rename
    original_unlink = os.unlink
    state_leaf = os.path.basename(env["state_file"])
    injected = False

    def edit_before_delete(target):
        nonlocal injected
        if not injected and os.fspath(target) == state_leaf:
            with open(env["state_file"], "w", encoding="utf-8") as fh:
                fh.write(concurrent)
            injected = True

    def racing_rename(src, dst, *args, **kwargs):
        if kwargs.get("src_dir_fd") is not None:
            edit_before_delete(src)
        return original_rename(src, dst, *args, **kwargs)

    def racing_unlink(path, *args, **kwargs):
        if kwargs.get("dir_fd") is not None:
            edit_before_delete(path)
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "rename", racing_rename)
    monkeypatch.setattr(os, "unlink", racing_unlink)
    monkeypatch.setattr(cr, "_supports_no_follow_directory_fds", lambda: True)

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 2
    assert injected is True
    assert open(env["state_file"], encoding="utf-8").read() == concurrent


def test_restore_detects_mutation_after_pre_restore_snapshot(env, monkeypatch):
    assert cr.cmd_snapshot(ns(env, id="s1")) == 0
    guard = os.path.join(env["root"], "hooks", "guard.py")
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write("print('v2 captured by undo snapshot')\n")

    original_snapshot = cr.cmd_snapshot
    mutated = False

    def mutate_after_pre_snapshot(args):
        nonlocal mutated
        rc = original_snapshot(args)
        if rc == 0 and str(args.id).startswith("pre-restore-"):
            with open(guard, "w", encoding="utf-8") as fh:
                fh.write("print('v3 after undo snapshot')\n")
            mutated = True
        return rc

    monkeypatch.setattr(cr, "cmd_snapshot", mutate_after_pre_snapshot)

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 2
    assert mutated is True
    assert open(guard, encoding="utf-8").read() == (
        "print('v3 after undo snapshot')\n"
    )


def test_global_app_state_restore_is_reversible(env, monkeypatch):
    # Keep even the current implementation's pre-restore fallback disposable
    # while this test drives explicit state-file propagation.
    monkeypatch.setattr(cr, "DEFAULT_STATE_FILE", env["state_file"])
    original = json.load(open(env["state_file"], encoding="utf-8"))
    cr.cmd_snapshot(ns(env, id="s1"))

    modified = {"mcpServers": {"replacement": {"command": "changed"}}}
    with open(env["state_file"], "w", encoding="utf-8") as fh:
        json.dump(modified, fh)

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 0
    assert json.load(open(env["state_file"], encoding="utf-8")) == original

    pre = [d for d in os.listdir(env["store"]) if d.startswith("pre-restore-")]
    assert len(pre) == 1, pre
    assert cr.cmd_restore(ns(env, id=pre[0], confirm=True)) == 0
    assert json.load(open(env["state_file"], encoding="utf-8")) == modified


def test_undo_removes_global_state_that_was_absent_before_restore(env):
    cr.cmd_snapshot(ns(env, id="s1"))
    os.remove(env["state_file"])

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 0
    assert os.path.isfile(env["state_file"])

    pre = [d for d in os.listdir(env["store"]) if d.startswith("pre-restore-")]
    assert len(pre) == 1, pre
    assert cr.cmd_restore(ns(env, id=pre[0], confirm=True)) == 0
    assert not os.path.lexists(env["state_file"])


def test_new_snapshot_records_missing_global_state_without_private_flag(env):
    os.remove(env["state_file"])

    assert cr.cmd_snapshot(ns(env, id="s1")) == 0
    manifest_path = os.path.join(env["store"], "s1", "manifest.json")
    manifest = json.load(open(manifest_path, encoding="utf-8"))

    assert manifest["schema"] == "config-snapshot/2"
    assert manifest["absent_files"] == ["global-app-state/claude.json"]

    with open(env["state_file"], "w", encoding="utf-8") as fh:
        fh.write('{"created":"after snapshot"}')
    guard = os.path.join(env["root"], "hooks", "guard.py")
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write("print('changed')\n")

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 0
    assert not os.path.lexists(env["state_file"])


def test_schema_v2_rejects_external_file_classified_as_neither_present_nor_absent(
    env,
):
    assert cr.cmd_snapshot(ns(env, id="s1")) == 0
    snapshot = os.path.join(env["store"], "s1")
    manifest_path = os.path.join(snapshot, "manifest.json")
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    manifest["files"].pop(cr.GLOBAL_APP_STATE_LOGICAL)
    os.remove(os.path.join(snapshot, "files", cr.GLOBAL_APP_STATE_LOGICAL))
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)

    assert cr._plan(ns(env, id="s1"))["manifest_valid"] is False


def test_schema_v2_rejects_duplicate_absent_external_file_classification(env):
    os.remove(env["state_file"])
    assert cr.cmd_snapshot(ns(env, id="s1")) == 0
    manifest_path = os.path.join(env["store"], "s1", "manifest.json")
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    manifest["absent_files"].append(cr.GLOBAL_APP_STATE_LOGICAL)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)

    assert cr._plan(ns(env, id="s1"))["manifest_valid"] is False


def test_restore_undo_command_preserves_alternate_paths(env, capsys):
    cr.cmd_snapshot(ns(env, id="s1"))
    with open(env["state_file"], "w", encoding="utf-8") as fh:
        fh.write('{"mcpServers":{"changed":{}}}')

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 0
    output = capsys.readouterr().out

    assert f"--store {env['store']}" in output
    assert f"--root {env['root']}" in output
    assert f"--state-file {env['state_file']}" in output

    undo_line = output.rstrip().splitlines()[-1].strip()
    undo_argv = shlex.split(undo_line)
    assert undo_argv[:2] == [sys.executable, os.path.realpath(cr.__file__)]


def test_restore_undo_command_works_from_a_different_cwd(
    env,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(env["repo"])
    relative_env = {
        key: os.path.relpath(value, env["repo"])
        for key, value in env.items()
    }
    assert cr.cmd_snapshot(ns(relative_env, id="s1")) == 0
    guard = os.path.join(env["root"], "hooks", "guard.py")
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write("print('v2 restored by cross-cwd undo')\n")

    assert cr.cmd_restore(ns(relative_env, id="s1", confirm=True)) == 0
    undo_line = capsys.readouterr().out.rstrip().splitlines()[-1].strip()
    undo_argv = shlex.split(undo_line)

    other_cwd = os.path.join(env["repo"], "different-cwd")
    os.mkdir(other_cwd)
    completed = subprocess.run(
        undo_argv,
        cwd=other_cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert open(guard, encoding="utf-8").read() == (
        "print('v2 restored by cross-cwd undo')\n"
    )


def test_undo_command_uses_platform_appropriate_windows_quoting():
    argv = [
        r"C:\Program Files\Python\python.exe",
        r"C:\Program Files\Claude Config\config_rollback.py",
        "restore",
        "--id",
        "pre-restore-1",
    ]

    assert cr.format_command(argv, platform="nt") == subprocess.list2cmdline(argv)


def test_restore_refuses_symlink_global_state_target(env):
    cr.cmd_snapshot(ns(env, id="s1"))
    os.remove(env["state_file"])
    outside_target = os.path.join(os.path.dirname(env["state_file"]), "outside.json")
    with open(outside_target, "w", encoding="utf-8") as fh:
        fh.write('{"must":"remain unchanged"}')
    os.symlink(outside_target, env["state_file"])

    rc = cr.cmd_restore(ns(env, id="s1", confirm=True))

    assert rc == 2
    assert os.path.islink(env["state_file"])
    assert open(outside_target, encoding="utf-8").read() == '{"must":"remain unchanged"}'


def test_restore_refuses_symlinked_parent_beneath_config_root(env):
    cr.cmd_snapshot(ns(env, id="s1"))
    hooks = os.path.join(env["root"], "hooks")
    os.remove(os.path.join(hooks, "guard.py"))
    os.rmdir(hooks)

    outside_hooks = os.path.join(os.path.dirname(env["root"]), "outside-hooks")
    os.mkdir(outside_hooks)
    outside_guard = os.path.join(outside_hooks, "guard.py")
    with open(outside_guard, "w", encoding="utf-8") as fh:
        fh.write("outside must remain unchanged\n")
    os.symlink(outside_hooks, hooks)

    rc = cr.cmd_restore(ns(env, id="s1", confirm=True))

    assert rc == 2
    assert os.path.islink(hooks)
    assert open(outside_guard, encoding="utf-8").read() == (
        "outside must remain unchanged\n"
    )


def test_restore_accepts_trusted_root_beneath_symlinked_system_ancestor(
    env, tmp_path
):
    cr.cmd_snapshot(ns(env, id="s1"))
    guard = os.path.join(env["root"], "hooks", "guard.py")
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write("print('changed')\n")

    alias = tmp_path / "trusted-alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    alias_env = dict(env)
    alias_env["root"] = str(alias / "cfg")

    assert cr.cmd_restore(ns(alias_env, id="s1", confirm=True)) == 0
    assert open(guard, encoding="utf-8").read() == "print('v1')\n"


def test_restore_refuses_symlinked_snapshot_source(env):
    cr.cmd_snapshot(ns(env, id="s1"))
    snap_source = os.path.join(
        env["store"], "s1", "files", "global-app-state", "claude.json"
    )
    os.remove(snap_source)
    tampered_source = os.path.join(os.path.dirname(env["state_file"]), "tampered.json")
    with open(tampered_source, "w", encoding="utf-8") as fh:
        fh.write('{"tampered":true}')
    os.symlink(tampered_source, snap_source)

    live_before = '{"live":"must remain"}'
    with open(env["state_file"], "w", encoding="utf-8") as fh:
        fh.write(live_before)

    rc = cr.cmd_restore(ns(env, id="s1", confirm=True))

    assert rc == 2
    assert open(env["state_file"], encoding="utf-8").read() == live_before


def test_restore_rejects_symlinked_snapshot_source_even_when_contents_match_live(
    env
):
    cr.cmd_snapshot(ns(env, id="s1"))
    snap_source = os.path.join(env["store"], "s1", "files", "hooks", "guard.py")
    outside = os.path.join(os.path.dirname(env["state_file"]), "matching.py")
    with open(outside, "w", encoding="utf-8") as fh:
        fh.write("print('v1')\n")
    os.remove(snap_source)
    os.symlink(outside, snap_source)

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 2
    assert open(
        os.path.join(env["root"], "hooks", "guard.py"), encoding="utf-8"
    ).read() == "print('v1')\n"


def test_restore_rechecks_snapshot_source_after_pre_restore_snapshot(
    env, monkeypatch, capsys
):
    cr.cmd_snapshot(ns(env, id="s1"))
    guard = os.path.join(env["root"], "hooks", "guard.py")
    live_before = "print('live must remain')\n"
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write(live_before)
    snap_source = os.path.join(env["store"], "s1", "files", "hooks", "guard.py")
    outside = os.path.join(os.path.dirname(env["state_file"]), "unverified.py")
    with open(outside, "w", encoding="utf-8") as fh:
        fh.write("print('unverified payload')\n")
    original_snapshot = cr.cmd_snapshot

    def swap_source_during_pre_snapshot(args):
        rc = original_snapshot(args)
        if rc == 0 and str(args.id).startswith("pre-restore-"):
            os.remove(snap_source)
            os.symlink(outside, snap_source)
        return rc

    monkeypatch.setattr(cr, "cmd_snapshot", swap_source_during_pre_snapshot)

    rc = cr.cmd_restore(ns(env, id="s1", confirm=True))
    output = capsys.readouterr()

    assert rc == 2
    assert open(guard, encoding="utf-8").read() == live_before
    assert "unverified payload" not in output.out + output.err
    assert "Undo with:" in output.out


def test_restore_refuses_snapshot_content_that_fails_manifest_hash(env, capsys):
    cr.cmd_snapshot(ns(env, id="s1"))
    snap_source = os.path.join(
        env["store"], "s1", "files", "global-app-state", "claude.json"
    )
    secret_marker = "tampered-secret-marker"
    with open(snap_source, "w", encoding="utf-8") as fh:
        fh.write('{"token":"' + secret_marker + '"}')

    live_before = '{"live":"must remain"}'
    with open(env["state_file"], "w", encoding="utf-8") as fh:
        fh.write(live_before)

    rc = cr.cmd_restore(ns(env, id="s1", confirm=True))
    output = capsys.readouterr()

    assert rc == 2
    assert open(env["state_file"], encoding="utf-8").read() == live_before
    assert secret_marker not in output.out + output.err


def test_restore_refuses_snapshot_without_integrity_manifest(env):
    cr.cmd_snapshot(ns(env, id="s1"))
    os.remove(os.path.join(env["store"], "s1", "manifest.json"))
    live_before = '{"live":"must remain"}'
    with open(env["state_file"], "w", encoding="utf-8") as fh:
        fh.write(live_before)

    rc = cr.cmd_restore(ns(env, id="s1", confirm=True))

    assert rc == 2
    assert open(env["state_file"], encoding="utf-8").read() == live_before


def test_restore_refuses_snapshot_file_without_recorded_hash(env):
    cr.cmd_snapshot(ns(env, id="s1"))
    manifest_path = os.path.join(env["store"], "s1", "manifest.json")
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    del manifest["files"]["global-app-state/claude.json"]["sha256"]
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
    live_before = '{"live":"must remain"}'
    with open(env["state_file"], "w", encoding="utf-8") as fh:
        fh.write(live_before)

    rc = cr.cmd_restore(ns(env, id="s1", confirm=True))

    assert rc == 2
    assert open(env["state_file"], encoding="utf-8").read() == live_before


def test_restore_recreates_a_deleted_file(env):
    cr.cmd_snapshot(ns(env, id="s1"))
    guard = os.path.join(env["root"], "hooks", "guard.py")
    os.remove(guard)
    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 0
    assert os.path.exists(guard)


def test_restore_recreates_missing_descendant_parent_directories(env):
    nested_dir = os.path.join(env["root"], "hooks", "nested", "deeper")
    os.makedirs(nested_dir)
    nested_file = os.path.join(nested_dir, "guard.py")
    with open(nested_file, "w", encoding="utf-8") as fh:
        fh.write("nested protected content\n")
    cr.cmd_snapshot(ns(env, id="s1"))
    os.remove(nested_file)
    os.removedirs(nested_dir)

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 0
    assert open(nested_file, encoding="utf-8").read() == (
        "nested protected content\n"
    )


def test_restore_is_itself_reversible(env):
    """A rollback that cannot be undone is not a safety mechanism."""
    cr.cmd_snapshot(ns(env, id="s1"))
    guard = os.path.join(env["root"], "hooks", "guard.py")
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write("print('v2-MODIFIED')\n")

    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 0
    assert "v1" in open(guard, encoding="utf-8").read()

    # A pre-restore snapshot must exist, capturing the v2 state we rolled back over.
    pre = [d for d in os.listdir(env["store"]) if d.startswith("pre-restore-")]
    assert len(pre) == 1, pre
    assert cr.cmd_restore(ns(env, id=pre[0], confirm=True)) == 0
    assert "MODIFIED" in open(guard, encoding="utf-8").read()


def test_two_restores_in_the_same_second_both_succeed(env):
    """REGRESSION: second-resolution pre-restore ids used to collide.

    `pre-restore-<UTC seconds>` meant two restores inside one second requested the
    same snapshot id; the (correct) no-overwrite guard then ABORTED the second
    restore -- an availability bug in the recovery path itself. The guard stays;
    the id is de-collided.
    """
    cr.cmd_snapshot(ns(env, id="base"))
    guard = os.path.join(env["root"], "hooks", "guard.py")

    for i in range(3):
        with open(guard, "w", encoding="utf-8") as fh:
            fh.write(f"print('mutation-{i}')\n")
        rc = cr.cmd_restore(ns(env, id="base", confirm=True))
        assert rc == 0, f"restore {i} aborted (id collision?)"
        assert open(guard, encoding="utf-8").read() == "print('v1')\n"

    # Each restore must have left its own recoverable pre-restore snapshot.
    pre = [d for d in os.listdir(env["store"]) if d.startswith("pre-restore-")]
    assert len(pre) == 3, f"expected 3 distinct pre-restore snapshots, got {pre}"


def test_restore_leaves_live_only_files_untouched(env):
    """Restore must not delete files the snapshot never knew about."""
    cr.cmd_snapshot(ns(env, id="s1"))
    newfile = os.path.join(env["root"], "hooks", "added-later.py")
    with open(newfile, "w", encoding="utf-8") as fh:
        fh.write("new\n")
    assert cr.cmd_restore(ns(env, id="s1", confirm=True)) == 0
    assert os.path.exists(newfile), "restore must not delete unknown live files"


def test_legacy_snapshot_leaves_live_only_global_state_untouched(env):
    os.remove(env["state_file"])
    cr.cmd_snapshot(ns(env, id="legacy"))
    manifest_path = os.path.join(env["store"], "legacy", "manifest.json")
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    manifest["schema"] = "config-snapshot/1"
    manifest.pop("absent_files", None)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
    live_only = '{"mcpServers":{"new":{"command":"keep"}}}'
    with open(env["state_file"], "w", encoding="utf-8") as fh:
        fh.write(live_only)
    guard = os.path.join(env["root"], "hooks", "guard.py")
    with open(guard, "w", encoding="utf-8") as fh:
        fh.write("print('changed')\n")

    plan = cr._plan(ns(env, id="legacy"))
    assert "global-app-state/claude.json" in plan["only_in_live"]
    assert cr.cmd_restore(ns(env, id="legacy", confirm=True)) == 0
    assert open(env["state_file"], encoding="utf-8").read() == live_only


def test_restore_noop_when_identical(env):
    cr.cmd_snapshot(ns(env, id="s1"))
    assert cr.cmd_restore(ns(env, id="s1", confirm=False)) == 0


def test_restore_missing_snapshot_is_an_error(env):
    assert cr.cmd_restore(ns(env, id="does-not-exist", confirm=True)) == 2


def test_snapshot_pins_git_state(env):
    cr.cmd_snapshot(ns(env, id="s1"))
    manifest = json.load(
        open(os.path.join(env["store"], "s1", "manifest.json"), encoding="utf-8")
    )
    # tmp_path is not a git repo, so git fields are None -- the KEY must still be
    # present so a snapshot always records whether it was version-pinned.
    assert "git" in manifest


def test_snapshot_documents_that_effective_probe_is_not_recorded(env):
    cr.cmd_snapshot(ns(env, id="s1"))
    manifest_path = os.path.join(env["store"], "s1", "manifest.json")
    with open(manifest_path, encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)

    assert "effective_configuration_probe" not in manifest
    assert "does not run or record an effective-configuration probe" in cr.__doc__


def test_data_dirs_are_not_snapshotted(env):
    """Transcripts/memory are DATA. A rollback must never rewrite the record."""
    projects = os.path.join(env["root"], "projects", "p1")
    os.makedirs(projects)
    with open(os.path.join(projects, "session.jsonl"), "w", encoding="utf-8") as fh:
        fh.write('{"a":1}\n')
    cr.cmd_snapshot(ns(env, id="s1"))
    manifest = json.load(
        open(os.path.join(env["store"], "s1", "manifest.json"), encoding="utf-8")
    )
    assert not any("projects" in k for k in manifest["files"])
