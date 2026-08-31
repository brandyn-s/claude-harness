#!/usr/bin/env python3
"""Verify provider-monitor skill routing against one sealed source catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
import sys
import tarfile
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NamedTuple

BINDING_RELATIVE_PATH = Path(
    "skills/_shared/provider-monitor-source-bindings.v1.json"
)
SERVER_PIN_RELATIVE_PATH = Path(".github/provider-monitor-server-pin.v1.json")
TRUSTED_WORKFLOW_RELATIVE_PATH = Path(
    ".github/workflows/provider-monitor-catalog-trusted.yml"
)
# One-time, self-sealing migration target. The base-controlled verifier accepts
# these exact reviewed bytes while the trusted workflow still has the old
# digest. After the target lands, ordinary byte equality is the only effective
# path because this digest is then the trusted workflow itself.
#
# CURRENT TARGET (registered 2026-08-26): the mergeability-poll fix for
# `Resolve the immutable base-integrated candidate`. The trusted lane polls GitHub
# for the PR's merge_commit_sha on a 10x3s = 30-second budget; measured on BOTH
# PR #2151 and PR #2152, GitHub left mergeable_state "unknown" well past that with
# the platform fully operational, so the step failed and
# provider-monitor-catalog-trusted cascaded off its result. A plain re-run then
# passed with no content change -- a red trust-lane check for a reason that had
# nothing to do with the pull request. The approved bytes widen the budget to a
# wall-clock 240s and make the timeout message name GitHub's async mergeability
# computation (and keep an API/permissions failure reported as a DISTINCT cause)
# so the next reader is not sent to the wrong place.
#
# This registration admits exactly ONE revision, byte-for-byte. The workflow
# cannot be edited further without re-registering, which is the point.
#
# NOTE, not changed here: the digest this slot held before today (1f855713...)
# matched NEITHER the workflow on main (623c7804...) nor anything else in the
# tree -- a standing approval for an artifact that is not present. Practical risk
# is low (using it needs a sha256 pre-image, i.e. possession of those exact
# bytes), but it is a control pointing at nothing. Deliberately left for a
# separately-reviewed decision by the control's owner rather than folded into a
# CI-ergonomics fix.
APPROVED_TRUSTED_WORKFLOW_MIGRATION_SHA256 = (
    "a4f11422e49f50f502cb27034e02bdc6c6a676576fd579d1a897e5bc38d2d7b3"
)
MARKETPLACE_ROOT = Path("marketplace/knowledge-ops/skills")
EXPECTED_SKILL_BINDINGS: Mapping[str, Mapping[str, object]] = {
    "cc-monitor": {
        "role": "provider_router",
        "providers": ["anthropic"],
        "source_selector": "all_provider_sources",
    },
    "openai-monitor": {
        "role": "provider_router",
        "providers": ["openai"],
        "source_selector": "all_provider_sources",
    },
    "enterprise-ai-monitor": {
        "role": "cross_provider_composer",
        "providers": ["anthropic", "openai"],
        "source_selector": "union_of_provider_bindings",
        "requires_skills": ["cc-monitor", "openai-monitor"],
    },
}
CONFIG_INPUT_RELATIVE_PATHS = (
    BINDING_RELATIVE_PATH,
    MARKETPLACE_ROOT / "_shared" / BINDING_RELATIVE_PATH.name,
    *(
        relative_path
        for skill_name in EXPECTED_SKILL_BINDINGS
        for relative_path in (
            Path("skills") / skill_name / "SKILL.md",
            MARKETPLACE_ROOT / skill_name / "SKILL.md",
        )
    ),
)
SERVER_BUNDLE_MANIFEST_PATH = "manifest.json"
SERVER_BUNDLE_ANCESTRY_PATH = "ancestor-revisions.txt"
SERVER_CATALOG_RELATIVE_PATH = (
    "scripts/enterprise_ai_monitor/provider_source_catalog.v1.json"
)
SERVER_EMITTER_RELATIVE_PATH = (
    "scripts/enterprise_ai_monitor/expected_emitter_registry.v1.json"
)
SERVER_BUNDLE_PAYLOAD_PATHS = (
    SERVER_BUNDLE_ANCESTRY_PATH,
    SERVER_EMITTER_RELATIVE_PATH,
    SERVER_CATALOG_RELATIVE_PATH,
)
SERVER_BUNDLE_MEMBER_PATHS = (
    SERVER_BUNDLE_MANIFEST_PATH,
    *SERVER_BUNDLE_PAYLOAD_PATHS,
)
SERVER_BUNDLE_MAX_BYTES = {
    SERVER_BUNDLE_MANIFEST_PATH: 64 * 1024,
    SERVER_BUNDLE_ANCESTRY_PATH: 16 * 1024 * 1024,
    SERVER_CATALOG_RELATIVE_PATH: 4 * 1024 * 1024,
    SERVER_EMITTER_RELATIVE_PATH: 4 * 1024 * 1024,
}
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_YAML_HEX_ESCAPE = re.compile(
    rb"\\(?:x([0-9a-fA-F]{2})|u([0-9a-fA-F]{4})|U([0-9a-fA-F]{8}))"
)
_YAML_LINE_CONTINUATION = re.compile(rb"\\\r?\n[\t ]*")


class RepositoryState(NamedTuple):
    """Exact source-repository state presented to the verifier."""

    revision: str
    clean: bool
    reviewed_revision_is_ancestor: bool


class VerificationError(ValueError):
    """A stable, content-free provider-monitor verification failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise VerificationError("duplicate_json_key")
        value[key] = item
    return value


def _load_json_bytes(payload: bytes, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except VerificationError:
        raise
    except (UnicodeError, ValueError) as exc:
        raise VerificationError(code) from exc
    if type(value) is not dict:
        raise VerificationError(code)
    return value


def _load_json(path: Path, *, code: str) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise VerificationError(code) from exc
    return _load_json_bytes(payload, code=code)


def _validate_config_input_paths(config_root: Path) -> Path:
    """Reject candidate-controlled links and non-files before content reads."""

    try:
        root = config_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise VerificationError("config_candidate_path_unsafe") from exc
    for relative_path in CONFIG_INPUT_RELATIVE_PATHS:
        candidate = config_root / relative_path
        cursor = config_root
        try:
            for part in relative_path.parts:
                cursor /= part
                if cursor.is_symlink():
                    raise VerificationError("config_candidate_path_unsafe")
            if not stat.S_ISREG(candidate.lstat().st_mode):
                raise VerificationError("config_candidate_path_unsafe")
            candidate.resolve(strict=True).relative_to(root)
        except VerificationError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise VerificationError("config_candidate_path_unsafe") from exc
    return root


def _read_regular_contained_file(
    root: Path,
    relative_path: Path,
    *,
    code: str,
) -> bytes:
    candidate = root / relative_path
    cursor = root
    try:
        resolved_root = root.resolve(strict=True)
        for part in relative_path.parts:
            cursor /= part
            if cursor.is_symlink():
                raise VerificationError(code)
        if not stat.S_ISREG(candidate.lstat().st_mode):
            raise VerificationError(code)
        candidate.resolve(strict=True).relative_to(resolved_root)
        return candidate.read_bytes()
    except VerificationError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise VerificationError(code) from exc


def _normalize_workflow_tokens(payload: bytes) -> bytes:
    """Expose ASCII tokens hidden by YAML double-quoted escape syntax."""

    def replace_hex_escape(match: re.Match[bytes]) -> bytes:
        digits = next(group for group in match.groups() if group is not None)
        codepoint = int(digits, 16)
        if codepoint > 0x7F:
            return match.group(0)
        return bytes((codepoint,))

    for _ in range(8):
        normalized = _YAML_LINE_CONTINUATION.sub(b"", payload)
        normalized = _YAML_HEX_ESCAPE.sub(replace_hex_escape, normalized)
        if normalized == payload:
            return normalized
        payload = normalized
    raise VerificationError("candidate_privileged_workflow_scope_invalid")


def verify_candidate_trust_contract(
    *,
    trusted_config_root: Path,
    candidate_config_root: Path,
) -> dict[str, str]:
    """Inspect the candidate's closed server pin with trusted code."""

    trusted_workflow = _read_regular_contained_file(
        trusted_config_root,
        TRUSTED_WORKFLOW_RELATIVE_PATH,
        code="trusted_workflow_unreadable",
    )
    candidate_workflow = _read_regular_contained_file(
        candidate_config_root,
        TRUSTED_WORKFLOW_RELATIVE_PATH,
        code="candidate_workflow_unsafe",
    )
    candidate_workflow_sha256 = hashlib.sha256(candidate_workflow).hexdigest()
    if (
        candidate_workflow != trusted_workflow
        and candidate_workflow_sha256
        != APPROVED_TRUSTED_WORKFLOW_MIGRATION_SHA256
    ):
        raise VerificationError("candidate_trusted_workflow_mismatch")
    workflows_root = candidate_config_root / ".github/workflows"
    try:
        workflow_paths = sorted(
            path
            for path in workflows_root.iterdir()
            if path.suffix in {".yml", ".yaml"}
        )
    except OSError as exc:
        raise VerificationError("candidate_privileged_workflow_scope_invalid") from exc
    if len(workflow_paths) > 128:
        raise VerificationError("candidate_privileged_workflow_scope_invalid")
    for workflow_path in workflow_paths:
        relative_path = workflow_path.relative_to(candidate_config_root)
        workflow_bytes = _read_regular_contained_file(
            candidate_config_root,
            relative_path,
            code="candidate_privileged_workflow_scope_invalid",
        )
        if len(workflow_bytes) > 1024 * 1024:
            raise VerificationError("candidate_privileged_workflow_scope_invalid")
        if relative_path == TRUSTED_WORKFLOW_RELATIVE_PATH:
            continue
        workflow_tokens = _normalize_workflow_tokens(workflow_bytes)
        workflow_tokens_lower = workflow_tokens.lower()
        if (
            b"pull_request_target" in workflow_tokens
            or b"enterprise-monitor-cross-repo-read" in workflow_tokens
            or b"MCP_SERVERS_READ_SSH_KEY" in workflow_tokens
            or b"environment" in workflow_tokens_lower
        ):
            raise VerificationError("candidate_privileged_workflow_scope_invalid")
    pin_bytes = _read_regular_contained_file(
        candidate_config_root,
        SERVER_PIN_RELATIVE_PATH,
        code="server_pin_unreadable",
    )
    pin = _load_json_bytes(pin_bytes, code="server_pin_invalid")
    if pin_bytes != _canonical_json_bytes(pin):
        raise VerificationError("server_pin_not_canonical")
    _expect_exact_keys(
        pin,
        {"schema_version", "repository", "source_commit"},
        code="server_pin_invalid",
    )
    if (
        pin["schema_version"] != "provider-monitor-server-pin/v1"
        or pin["repository"] != "example-org/mcp-servers"
        or type(pin["source_commit"]) is not str
        or not _REVISION.fullmatch(pin["source_commit"])
    ):
        raise VerificationError("server_pin_invalid")
    return {
        "schema_version": "provider-monitor-candidate-trust/v1",
        "server_revision": pin["source_commit"],
        "status": "pass",
    }


def _canonical_sha256(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise VerificationError("document_not_canonical_json") from exc
    return hashlib.sha256(encoded).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError, UnicodeError) as exc:
        raise VerificationError("server_bundle_manifest_invalid") from exc


def _identifier_set_sha256(values: set[str]) -> str:
    return _canonical_sha256(sorted(values))


def _expect_exact_keys(
    value: Mapping[str, Any], expected: set[str], *, code: str
) -> None:
    if set(value) != expected:
        raise VerificationError(code)


def _expect_count_map(
    value: object, expected_keys: set[str], *, code: str
) -> dict[str, int]:
    if type(value) is not dict or set(value) != expected_keys:
        raise VerificationError(code)
    result: dict[str, int] = {}
    for key, count in value.items():
        if type(count) is not int or count < 0:
            raise VerificationError(code)
        result[key] = count
    return result


def _expect_relative_path(value: object, *, code: str) -> Path:
    if type(value) is not str or not value:
        raise VerificationError(code)
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise VerificationError(code)
    return path


def _validate_binding(binding: Mapping[str, Any]) -> None:
    _expect_exact_keys(
        binding,
        {
            "schema_version",
            "truth_scope",
            "catalog",
            "emitter_registry",
            "skill_bindings",
        },
        code="binding_shape_mismatch",
    )
    if binding["schema_version"] != "provider-monitor-skill-bindings/v1":
        raise VerificationError("binding_schema_mismatch")
    if binding["truth_scope"] != "source_identity_and_routing_only":
        raise VerificationError("binding_truth_scope_mismatch")

    catalog = binding["catalog"]
    if type(catalog) is not dict:
        raise VerificationError("catalog_binding_shape_mismatch")
    _expect_exact_keys(
        catalog,
        {
            "repository",
            "reviewed_revision",
            "path",
            "schema_version",
            "source_generation",
            "document_sha256",
            "source_count",
            "provider_source_counts",
            "provider_source_set_sha256",
        },
        code="catalog_binding_shape_mismatch",
    )
    if catalog["repository"] != "example-org/mcp-servers":
        raise VerificationError("catalog_repository_mismatch")
    if type(catalog["reviewed_revision"]) is not str or not _REVISION.fullmatch(
        catalog["reviewed_revision"]
    ):
        raise VerificationError("catalog_revision_invalid")
    _expect_relative_path(catalog["path"], code="catalog_path_invalid")
    if catalog["schema_version"] != "provider-source-catalog/v1":
        raise VerificationError("catalog_schema_binding_mismatch")
    if type(catalog["source_generation"]) is not str or not catalog[
        "source_generation"
    ]:
        raise VerificationError("catalog_generation_binding_invalid")
    if type(catalog["document_sha256"]) is not str or not _DIGEST.fullmatch(
        catalog["document_sha256"]
    ):
        raise VerificationError("catalog_digest_binding_invalid")
    if type(catalog["source_count"]) is not int or catalog["source_count"] < 1:
        raise VerificationError("catalog_count_binding_invalid")
    _expect_count_map(
        catalog["provider_source_counts"],
        {"anthropic", "openai"},
        code="provider_source_count_binding_invalid",
    )
    provider_source_digests = catalog["provider_source_set_sha256"]
    if type(provider_source_digests) is not dict or set(
        provider_source_digests
    ) != {"anthropic", "openai"}:
        raise VerificationError("provider_source_set_digest_binding_invalid")
    if any(
        type(digest) is not str or not _DIGEST.fullmatch(digest)
        for digest in provider_source_digests.values()
    ):
        raise VerificationError("provider_source_set_digest_binding_invalid")

    registry = binding["emitter_registry"]
    if type(registry) is not dict:
        raise VerificationError("emitter_binding_shape_mismatch")
    _expect_exact_keys(
        registry,
        {
            "path",
            "schema_version",
            "source_generation",
            "document_sha256",
            "emitter_count",
            "provider_emitter_counts",
        },
        code="emitter_binding_shape_mismatch",
    )
    _expect_relative_path(registry["path"], code="emitter_path_invalid")
    if registry["schema_version"] != "expected-emitter-registry/v1":
        raise VerificationError("emitter_schema_binding_mismatch")
    if registry["source_generation"] != catalog["source_generation"]:
        raise VerificationError("emitter_generation_binding_mismatch")
    if type(registry["document_sha256"]) is not str or not _DIGEST.fullmatch(
        registry["document_sha256"]
    ):
        raise VerificationError("emitter_digest_binding_invalid")
    if type(registry["emitter_count"]) is not int or registry["emitter_count"] < 1:
        raise VerificationError("emitter_count_binding_invalid")
    _expect_count_map(
        registry["provider_emitter_counts"],
        {"anthropic", "openai", "unknown"},
        code="provider_emitter_count_binding_invalid",
    )

    skill_bindings = binding["skill_bindings"]
    if type(skill_bindings) is not dict or set(skill_bindings) != set(
        EXPECTED_SKILL_BINDINGS
    ):
        raise VerificationError("skill_binding_set_mismatch")
    for name, expected in EXPECTED_SKILL_BINDINGS.items():
        if skill_bindings[name] != expected:
            raise VerificationError("skill_binding_role_mismatch")


def _validate_catalog(
    catalog: Mapping[str, Any], binding: Mapping[str, Any]
) -> tuple[dict[str, set[str]], dict[str, int]]:
    if catalog.get("schema_version") != binding["schema_version"]:
        raise VerificationError("catalog_schema_mismatch")
    if catalog.get("source_generation") != binding["source_generation"]:
        raise VerificationError("catalog_generation_mismatch")
    if _canonical_sha256(catalog) != binding["document_sha256"]:
        raise VerificationError("catalog_digest_mismatch")

    sources = catalog.get("sources")
    if type(sources) is not list:
        raise VerificationError("catalog_sources_invalid")
    by_provider = {"anthropic": set(), "openai": set()}
    all_ids: set[str] = set()
    for source in sources:
        if type(source) is not dict:
            raise VerificationError("catalog_source_invalid")
        source_id = source.get("source_registry_id")
        provider = source.get("provider")
        if type(source_id) is not str or not source_id or source_id in all_ids:
            raise VerificationError("catalog_source_identity_invalid")
        if type(provider) is not str or provider not in by_provider:
            raise VerificationError("catalog_source_provider_invalid")
        if source.get("source_generation") != binding["source_generation"]:
            raise VerificationError("catalog_source_generation_mismatch")
        all_ids.add(source_id)
        by_provider[provider].add(source_id)

    actual_counts = {name: len(values) for name, values in by_provider.items()}
    if len(all_ids) != binding["source_count"]:
        raise VerificationError("catalog_source_count_mismatch")
    if actual_counts != binding["provider_source_counts"]:
        raise VerificationError("catalog_provider_count_mismatch")
    if by_provider["anthropic"] & by_provider["openai"]:
        raise VerificationError("catalog_provider_partition_invalid")
    actual_digests = {
        provider: _identifier_set_sha256(source_ids)
        for provider, source_ids in by_provider.items()
    }
    if actual_digests != binding["provider_source_set_sha256"]:
        raise VerificationError("catalog_provider_source_set_digest_mismatch")
    return by_provider, actual_counts


def _validate_emitters(
    registry: Mapping[str, Any],
    binding: Mapping[str, Any],
    *,
    catalog_sha256: str,
    provider_sources: Mapping[str, set[str]],
) -> None:
    if registry.get("schema_version") != binding["schema_version"]:
        raise VerificationError("emitter_schema_mismatch")
    if registry.get("source_generation") != binding["source_generation"]:
        raise VerificationError("emitter_generation_mismatch")
    if registry.get("source_catalog_sha256") != catalog_sha256:
        raise VerificationError("emitter_catalog_lineage_mismatch")
    if _canonical_sha256(registry) != binding["document_sha256"]:
        raise VerificationError("emitter_digest_mismatch")

    emitters = registry.get("emitters")
    if type(emitters) is not list:
        raise VerificationError("emitter_registry_invalid")
    emitter_ids: set[str] = set()
    provider_counts: Counter[str] = Counter()
    for emitter in emitters:
        if type(emitter) is not dict:
            raise VerificationError("emitter_invalid")
        emitter_id = emitter.get("emitter_registry_id")
        provider = emitter.get("provider")
        source_id = emitter.get("source_registry_id")
        if type(emitter_id) is not str or not emitter_id or emitter_id in emitter_ids:
            raise VerificationError("emitter_identity_invalid")
        if type(provider) is not str or provider not in {
            "anthropic",
            "openai",
            "unknown",
        }:
            raise VerificationError("emitter_provider_invalid")
        if type(source_id) is not str or not source_id:
            raise VerificationError("emitter_source_identity_invalid")
        if provider == "unknown":
            if source_id != "unknown/quarantine":
                raise VerificationError("unknown_emitter_source_invalid")
        elif source_id not in provider_sources[provider]:
            raise VerificationError("emitter_source_provider_mismatch")
        emitter_ids.add(emitter_id)
        provider_counts[provider] += 1

    if len(emitter_ids) != binding["emitter_count"]:
        raise VerificationError("emitter_count_mismatch")
    actual_provider_counts = {
        provider: provider_counts[provider]
        for provider in ("anthropic", "openai", "unknown")
    }
    if actual_provider_counts != binding["provider_emitter_counts"]:
        raise VerificationError("emitter_provider_count_mismatch")


def _validate_skill_copies(
    config_root: Path, *, binding_bytes: bytes
) -> None:
    marketplace_binding = (
        config_root / MARKETPLACE_ROOT / "_shared" / BINDING_RELATIVE_PATH.name
    )
    try:
        if marketplace_binding.read_bytes() != binding_bytes:
            raise VerificationError("marketplace_binding_drift")
    except OSError as exc:
        raise VerificationError("marketplace_binding_drift") from exc

    for skill_name in EXPECTED_SKILL_BINDINGS:
        source_path = config_root / "skills" / skill_name / "SKILL.md"
        marketplace_path = config_root / MARKETPLACE_ROOT / skill_name / "SKILL.md"
        try:
            source_bytes = source_path.read_bytes()
            marketplace_bytes = marketplace_path.read_bytes()
        except OSError as exc:
            raise VerificationError("skill_copy_unreadable") from exc
        if source_bytes != marketplace_bytes:
            raise VerificationError("marketplace_skill_copy_drift")
        marker = (
            "../_shared/provider-monitor-source-bindings.v1.json"
            f"#skill_bindings.{skill_name}"
        ).encode()
        if source_bytes.count(marker) != 1:
            raise VerificationError("skill_binding_marker_mismatch")


def _read_server_bundle(
    bundle_path: Path,
    *,
    binding: Mapping[str, Any] | None,
    expected_mcp_servers_revision: str,
    expected_bundle_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Validate a sealed, minimal server bundle without extracting it."""

    if not _DIGEST.fullmatch(expected_bundle_sha256):
        raise VerificationError("server_bundle_artifact_digest_invalid")
    try:
        if bundle_path.is_symlink() or not stat.S_ISREG(bundle_path.lstat().st_mode):
            raise VerificationError("server_bundle_path_unsafe")
        if bundle_path.stat().st_size > 32 * 1024 * 1024:
            raise VerificationError("server_bundle_shape_mismatch")
        actual_bundle_sha256 = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    except VerificationError:
        raise
    except OSError as exc:
        raise VerificationError("server_bundle_path_unsafe") from exc
    if actual_bundle_sha256 != expected_bundle_sha256:
        raise VerificationError("server_bundle_artifact_digest_mismatch")

    try:
        with tarfile.open(bundle_path, mode="r:", errorlevel=2) as bundle:
            members = bundle.getmembers()
            if bundle.pax_headers:
                raise VerificationError("server_bundle_shape_mismatch")
            if [member.name for member in members] != list(
                SERVER_BUNDLE_MEMBER_PATHS
            ):
                unsafe_name = any(
                    not member.isreg()
                    or member.name.startswith("/")
                    or "\\" in member.name
                    or ".." in Path(member.name).parts
                    for member in members
                )
                if unsafe_name:
                    raise VerificationError("server_bundle_path_unsafe")
                raise VerificationError("server_bundle_shape_mismatch")

            payloads: dict[str, bytes] = {}
            member_modes: dict[str, int] = {}
            for member in members:
                if not member.isreg():
                    raise VerificationError("server_bundle_path_unsafe")
                if (
                    member.mode != 0o644
                    or member.uid != 0
                    or member.gid != 0
                    or member.mtime != 0
                    or member.uname != ""
                    or member.gname != ""
                    or member.pax_headers
                ):
                    raise VerificationError("server_bundle_payload_mismatch")
                if member.size > SERVER_BUNDLE_MAX_BYTES[member.name]:
                    raise VerificationError("server_bundle_shape_mismatch")
                extracted = bundle.extractfile(member)
                if extracted is None:
                    raise VerificationError("server_bundle_path_unsafe")
                content = extracted.read(SERVER_BUNDLE_MAX_BYTES[member.name] + 1)
                if len(content) != member.size:
                    raise VerificationError("server_bundle_payload_mismatch")
                payloads[member.name] = content
                member_modes[member.name] = member.mode
    except VerificationError:
        raise
    except (OSError, tarfile.TarError, EOFError) as exc:
        raise VerificationError("server_bundle_shape_mismatch") from exc

    manifest_bytes = payloads[SERVER_BUNDLE_MANIFEST_PATH]
    manifest = _load_json_bytes(
        manifest_bytes,
        code="server_bundle_manifest_invalid",
    )
    if manifest_bytes != _canonical_json_bytes(manifest):
        raise VerificationError("server_bundle_manifest_not_canonical")
    _expect_exact_keys(
        manifest,
        {
            "schema_version",
            "repository",
            "source_commit",
            "ancestor_count",
            "files",
        },
        code="server_bundle_manifest_invalid",
    )
    if manifest["schema_version"] != "provider-monitor-server-bundle/v1":
        raise VerificationError("server_bundle_manifest_invalid")
    if manifest["repository"] != "example-org/mcp-servers":
        raise VerificationError("server_bundle_manifest_invalid")
    source_commit = manifest["source_commit"]
    if type(source_commit) is not str or not _REVISION.fullmatch(source_commit):
        raise VerificationError("server_bundle_manifest_invalid")
    if source_commit != expected_mcp_servers_revision:
        raise VerificationError("mcp_servers_expected_revision_mismatch")
    if (
        type(manifest["ancestor_count"]) is not int
        or manifest["ancestor_count"] < 1
    ):
        raise VerificationError("server_bundle_manifest_invalid")

    file_entries = manifest["files"]
    if type(file_entries) is not list or len(file_entries) != len(
        SERVER_BUNDLE_PAYLOAD_PATHS
    ):
        raise VerificationError("server_bundle_manifest_invalid")
    for expected_path, entry in zip(SERVER_BUNDLE_PAYLOAD_PATHS, file_entries):
        if type(entry) is not dict:
            raise VerificationError("server_bundle_manifest_invalid")
        _expect_exact_keys(
            entry,
            {"path", "sha256", "size", "mode"},
            code="server_bundle_manifest_invalid",
        )
        if (
            entry["path"] != expected_path
            or type(entry["sha256"]) is not str
            or not _DIGEST.fullmatch(entry["sha256"])
            or type(entry["size"]) is not int
            or entry["size"] < 0
            or entry["mode"] != "0644"
        ):
            raise VerificationError("server_bundle_manifest_invalid")
        content = payloads[expected_path]
        if (
            len(content) != entry["size"]
            or hashlib.sha256(content).hexdigest() != entry["sha256"]
            or member_modes[expected_path] != 0o644
        ):
            raise VerificationError("server_bundle_payload_mismatch")

    ancestor_bytes = payloads[SERVER_BUNDLE_ANCESTRY_PATH]
    try:
        ancestor_text = ancestor_bytes.decode("ascii")
    except UnicodeError as exc:
        raise VerificationError("server_bundle_ancestry_invalid") from exc
    ancestor_revisions = ancestor_text.splitlines()
    if (
        not ancestor_revisions
        or ("\n".join(ancestor_revisions) + "\n").encode("ascii")
        != ancestor_bytes
        or len(ancestor_revisions) != len(set(ancestor_revisions))
        or any(not _REVISION.fullmatch(item) for item in ancestor_revisions)
        or len(ancestor_revisions) != manifest["ancestor_count"]
        or ancestor_revisions[0] != source_commit
    ):
        raise VerificationError("server_bundle_ancestry_invalid")
    if binding is not None:
        if binding["catalog"]["reviewed_revision"] not in ancestor_revisions:
            raise VerificationError("mcp_servers_reviewed_revision_not_ancestor")
        if binding["catalog"]["path"] != SERVER_CATALOG_RELATIVE_PATH:
            raise VerificationError("catalog_path_invalid")
        if binding["emitter_registry"]["path"] != SERVER_EMITTER_RELATIVE_PATH:
            raise VerificationError("emitter_path_invalid")

    catalog = _load_json_bytes(
        payloads[SERVER_CATALOG_RELATIVE_PATH],
        code="catalog_unreadable",
    )
    registry = _load_json_bytes(
        payloads[SERVER_EMITTER_RELATIVE_PATH],
        code="emitter_registry_unreadable",
    )
    return catalog, registry, ancestor_revisions


def verify_server_bundle_envelope(
    *,
    server_bundle: Path,
    expected_mcp_servers_revision: str,
    expected_bundle_sha256: str,
) -> dict[str, object]:
    """Authenticate a server bundle without consulting a config binding."""

    _, _, ancestor_revisions = _read_server_bundle(
        server_bundle,
        binding=None,
        expected_mcp_servers_revision=expected_mcp_servers_revision,
        expected_bundle_sha256=expected_bundle_sha256,
    )
    return {
        "ancestor_count": len(ancestor_revisions),
        "schema_version": "provider-monitor-server-bundle-envelope/v1",
        "server_revision": expected_mcp_servers_revision,
        "status": "pass",
    }


def _verify_loaded_contract(
    *,
    config_root: Path,
    binding_path: Path,
    binding: Mapping[str, Any],
    catalog: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> dict[str, object]:
    """Verify already-authenticated catalog and emitter documents."""

    provider_sources, provider_counts = _validate_catalog(
        catalog, binding["catalog"]
    )
    _validate_emitters(
        registry,
        binding["emitter_registry"],
        catalog_sha256=binding["catalog"]["document_sha256"],
        provider_sources=provider_sources,
    )
    try:
        binding_bytes = binding_path.read_bytes()
    except OSError as exc:
        raise VerificationError("binding_unreadable") from exc
    _validate_skill_copies(config_root, binding_bytes=binding_bytes)

    skill_sources = {
        "cc-monitor": provider_sources["anthropic"],
        "openai-monitor": provider_sources["openai"],
        "enterprise-ai-monitor": (
            provider_sources["anthropic"] | provider_sources["openai"]
        ),
    }
    if skill_sources["enterprise-ai-monitor"] != set().union(
        *provider_sources.values()
    ):
        raise VerificationError("enterprise_skill_source_union_mismatch")

    return {
        "schema_version": "provider-monitor-skill-binding-verification/v1",
        "status": "pass",
        "source_generation": binding["catalog"]["source_generation"],
        "catalog_sha256": binding["catalog"]["document_sha256"],
        "source_count": sum(provider_counts.values()),
        "provider_source_counts": provider_counts,
        "emitter_count": binding["emitter_registry"]["emitter_count"],
        "skill_source_counts": {
            name: len(sources) for name, sources in skill_sources.items()
        },
        "truth_scope": binding["truth_scope"],
    }


def verify_repository_contract(
    *,
    config_root: Path,
    mcp_servers_root: Path,
    repository_state: RepositoryState,
    expected_mcp_servers_revision: str,
) -> dict[str, object]:
    """Verify exact catalog lineage and derive each skill's source subset."""

    config_root = _validate_config_input_paths(config_root)
    mcp_servers_root = mcp_servers_root.resolve()
    binding_path = config_root / BINDING_RELATIVE_PATH
    binding = _load_json(binding_path, code="binding_unreadable")
    _validate_binding(binding)

    if not _REVISION.fullmatch(expected_mcp_servers_revision):
        raise VerificationError("mcp_servers_expected_revision_invalid")
    if repository_state.revision != expected_mcp_servers_revision:
        raise VerificationError("mcp_servers_expected_revision_mismatch")
    if repository_state.clean is not True:
        raise VerificationError("mcp_servers_checkout_dirty")
    if repository_state.reviewed_revision_is_ancestor is not True:
        raise VerificationError("mcp_servers_reviewed_revision_not_ancestor")

    catalog_path = mcp_servers_root / binding["catalog"]["path"]
    registry_path = mcp_servers_root / binding["emitter_registry"]["path"]
    catalog = _load_json(catalog_path, code="catalog_unreadable")
    registry = _load_json(registry_path, code="emitter_registry_unreadable")
    return _verify_loaded_contract(
        config_root=config_root,
        binding_path=binding_path,
        binding=binding,
        catalog=catalog,
        registry=registry,
    )


def verify_server_bundle_contract(
    *,
    config_root: Path,
    server_bundle: Path,
    expected_mcp_servers_revision: str,
    expected_bundle_sha256: str,
) -> dict[str, object]:
    """Verify candidate config against a sealed minimal server bundle."""

    config_root = _validate_config_input_paths(config_root)
    binding_path = config_root / BINDING_RELATIVE_PATH
    binding = _load_json(binding_path, code="binding_unreadable")
    _validate_binding(binding)
    if not _REVISION.fullmatch(expected_mcp_servers_revision):
        raise VerificationError("mcp_servers_expected_revision_invalid")
    catalog, registry, _ = _read_server_bundle(
        server_bundle,
        binding=binding,
        expected_mcp_servers_revision=expected_mcp_servers_revision,
        expected_bundle_sha256=expected_bundle_sha256,
    )
    return _verify_loaded_contract(
        config_root=config_root,
        binding_path=binding_path,
        binding=binding,
        catalog=catalog,
        registry=registry,
    )


def inspect_repository_state(
    mcp_servers_root: Path, *, reviewed_revision: str
) -> RepositoryState:
    """Read exact HEAD, cleanliness, and reviewed-revision ancestry from Git."""

    root = mcp_servers_root.resolve()

    def run(*arguments: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", "-C", str(root), *arguments],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise VerificationError("mcp_servers_git_state_unreadable") from exc

    top_level = run("rev-parse", "--show-toplevel")
    if top_level.returncode != 0:
        raise VerificationError("mcp_servers_git_state_unreadable")
    try:
        resolved_top_level = Path(top_level.stdout.strip()).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise VerificationError("mcp_servers_git_state_unreadable") from exc
    try:
        same_checkout = resolved_top_level.samefile(root)
    except OSError as exc:
        raise VerificationError("mcp_servers_git_state_unreadable") from exc
    if not same_checkout:
        raise VerificationError("mcp_servers_checkout_root_mismatch")

    head_result = run("rev-parse", "--verify", "HEAD")
    if head_result.returncode != 0:
        raise VerificationError("mcp_servers_git_state_unreadable")
    revision = head_result.stdout.strip()
    if not _REVISION.fullmatch(revision):
        raise VerificationError("mcp_servers_git_state_unreadable")

    status_result = run("status", "--porcelain=v1", "--untracked-files=all", "-z")
    if status_result.returncode != 0:
        raise VerificationError("mcp_servers_git_state_unreadable")

    ancestry_result = run(
        "merge-base", "--is-ancestor", reviewed_revision, revision
    )
    if ancestry_result.returncode not in {0, 1}:
        raise VerificationError("mcp_servers_git_state_unreadable")
    return RepositoryState(
        revision=revision,
        clean=status_result.stdout == "",
        reviewed_revision_is_ancestor=ancestry_result.returncode == 0,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify provider-monitor skill routing against an exact clean "
            "mcp-servers checkout and sealed source catalog."
        )
    )
    parser.add_argument(
        "--config-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="claude-config repository root (defaults to this script's repository)",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--mcp-servers",
        type=Path,
        help="exact mcp-servers checkout root",
    )
    source.add_argument(
        "--server-bundle",
        type=Path,
        help="sealed minimal mcp-servers bundle tar",
    )
    source.add_argument(
        "--server-bundle-envelope",
        type=Path,
        help="sealed bundle tar to authenticate without a config binding",
    )
    source.add_argument(
        "--inspect-candidate-trust",
        type=Path,
        help="candidate claude-config root to inspect as untrusted data",
    )
    parser.add_argument(
        "--trusted-config-root",
        type=Path,
        help="trusted base claude-config root for candidate trust inspection",
    )
    parser.add_argument(
        "--expected-servers-sha",
        help="full 40-character SHA expected at mcp-servers HEAD",
    )
    parser.add_argument(
        "--expected-bundle-sha256",
        help="full SHA-256 digest expected for --server-bundle",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.inspect_candidate_trust is not None:
            if (
                args.trusted_config_root is None
                or args.expected_servers_sha is not None
                or args.expected_bundle_sha256 is not None
            ):
                raise VerificationError("candidate_trust_arguments_invalid")
            result = verify_candidate_trust_contract(
                trusted_config_root=args.trusted_config_root,
                candidate_config_root=args.inspect_candidate_trust,
            )
        elif args.server_bundle_envelope is not None:
            if args.trusted_config_root is not None:
                raise VerificationError("server_bundle_arguments_invalid")
            if args.expected_servers_sha is None:
                raise VerificationError("mcp_servers_expected_revision_invalid")
            if args.expected_bundle_sha256 is None:
                raise VerificationError("server_bundle_artifact_digest_invalid")
            result = verify_server_bundle_envelope(
                server_bundle=args.server_bundle_envelope,
                expected_mcp_servers_revision=args.expected_servers_sha,
                expected_bundle_sha256=args.expected_bundle_sha256,
            )
        elif args.server_bundle is not None:
            if args.trusted_config_root is not None:
                raise VerificationError("server_bundle_arguments_invalid")
            if args.expected_servers_sha is None:
                raise VerificationError("mcp_servers_expected_revision_invalid")
            if args.expected_bundle_sha256 is None:
                raise VerificationError("server_bundle_artifact_digest_invalid")
            result = verify_server_bundle_contract(
                config_root=args.config_root,
                server_bundle=args.server_bundle,
                expected_mcp_servers_revision=args.expected_servers_sha,
                expected_bundle_sha256=args.expected_bundle_sha256,
            )
        else:
            if (
                args.trusted_config_root is not None
                or args.expected_servers_sha is None
                or args.expected_bundle_sha256 is not None
            ):
                raise VerificationError("server_bundle_artifact_digest_invalid")
            binding = _load_json(
                args.config_root.resolve() / BINDING_RELATIVE_PATH,
                code="binding_unreadable",
            )
            _validate_binding(binding)
            state = inspect_repository_state(
                args.mcp_servers,
                reviewed_revision=binding["catalog"]["reviewed_revision"],
            )
            result = verify_repository_contract(
                config_root=args.config_root,
                mcp_servers_root=args.mcp_servers,
                repository_state=state,
                expected_mcp_servers_revision=args.expected_servers_sha,
            )
    except VerificationError as exc:
        print(
            f"provider-monitor-source-catalog: {exc.code}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
