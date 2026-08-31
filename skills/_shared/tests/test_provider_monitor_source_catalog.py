"""Contract tests for the provider-monitor source-catalog binding verifier."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SHARED_DIR = Path(__file__).resolve().parents[1]
VERIFIER_PATH = SHARED_DIR / "verify_provider_monitor_source_catalog.py"
VALIDATE_WORKFLOW_PATH = SHARED_DIR.parents[1] / ".github/workflows/validate.yml"
TRUSTED_WORKFLOW_PATH = (
    SHARED_DIR.parents[1]
    / ".github/workflows/provider-monitor-catalog-trusted.yml"
)
WORKFLOWS_DOC_PATH = SHARED_DIR.parents[1] / ".github/WORKFLOWS.md"
FROZEN_SERVER_SHA = "8ad8a328e406c1d384ee8941f38c3ee9449c32fd"
SERVER_PIN_PATH = Path(".github/provider-monitor-server-pin.v1.json")


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _identifier_set_sha256(values: list[str]) -> str:
    return _canonical_sha256(sorted(values))


def _load_verifier() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("provider_monitor_verifier", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load provider-monitor verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workflow_job(workflow: str, job_name: str) -> str:
    marker = f"  {job_name}:\n"
    start = workflow.index(marker)
    next_job = workflow.find("\n  ", start + len(marker))
    while next_job != -1:
        candidate = workflow[next_job + 1 :].splitlines()[0]
        if candidate.endswith(":") and not candidate.startswith("    "):
            return workflow[start:next_job]
        next_job = workflow.find("\n  ", next_job + 1)
    return workflow[start:]


class ProviderMonitorVerifierWalkingSkeletonTests(unittest.TestCase):
    def test_trusted_candidate_inspection_returns_closed_server_pin(self) -> None:
        verifier = _load_verifier()
        self.assertTrue(hasattr(verifier, "verify_candidate_trust_contract"))

        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            trusted_root = root / "trusted"
            candidate_root = root / "candidate"
            workflow_relative = Path(
                ".github/workflows/provider-monitor-catalog-trusted.yml"
            )
            for config_root in (trusted_root, candidate_root):
                workflow_path = config_root / workflow_relative
                workflow_path.parent.mkdir(parents=True)
                workflow_path.write_bytes(TRUSTED_WORKFLOW_PATH.read_bytes())
            pin_path = candidate_root / SERVER_PIN_PATH
            pin_path.parent.mkdir(parents=True, exist_ok=True)
            pin_path.write_text(
                json.dumps(
                    {
                        "repository": "example-org/mcp-servers",
                        "schema_version": "provider-monitor-server-pin/v1",
                        "source_commit": FROZEN_SERVER_SHA,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )

            result = verifier.verify_candidate_trust_contract(
                trusted_config_root=trusted_root,
                candidate_config_root=candidate_root,
            )

        self.assertEqual(
            {
                "schema_version": "provider-monitor-candidate-trust/v1",
                "server_revision": FROZEN_SERVER_SHA,
                "status": "pass",
            },
            result,
        )

    def test_trusted_candidate_inspection_rejects_workflow_takeover(self) -> None:
        verifier = _load_verifier()
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            trusted_root = root / "trusted"
            candidate_root = root / "candidate"
            workflow_relative = Path(
                ".github/workflows/provider-monitor-catalog-trusted.yml"
            )
            trusted_workflow = trusted_root / workflow_relative
            candidate_workflow = candidate_root / workflow_relative
            trusted_workflow.parent.mkdir(parents=True)
            candidate_workflow.parent.mkdir(parents=True)
            trusted_workflow.write_bytes(TRUSTED_WORKFLOW_PATH.read_bytes())
            candidate_workflow.write_bytes(
                TRUSTED_WORKFLOW_PATH.read_bytes()
                + b"\n# candidate-controlled future secret sink\n"
            )
            pin_path = candidate_root / SERVER_PIN_PATH
            pin_path.parent.mkdir(parents=True, exist_ok=True)
            pin_path.write_text(
                '{"repository":"example-org/mcp-servers",'
                '"schema_version":"provider-monitor-server-pin/v1",'
                f'"source_commit":"{FROZEN_SERVER_SHA}"}}\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                verifier.VerificationError,
                "candidate_trusted_workflow_mismatch",
            ):
                verifier.verify_candidate_trust_contract(
                    trusted_config_root=trusted_root,
                    candidate_config_root=candidate_root,
                )

    def test_trusted_candidate_inspection_accepts_only_approved_migration_digest(
        self,
    ) -> None:
        verifier = _load_verifier()
        self.assertEqual(
            "a4f11422e49f50f502cb27034e02bdc6c6a676576fd579d1a897e5bc38d2d7b3",
            verifier.APPROVED_TRUSTED_WORKFLOW_MIGRATION_SHA256,
        )
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            trusted_root = root / "trusted"
            candidate_root = root / "candidate"
            workflow_relative = Path(
                ".github/workflows/provider-monitor-catalog-trusted.yml"
            )
            trusted_workflow = trusted_root / workflow_relative
            candidate_workflow = candidate_root / workflow_relative
            trusted_workflow.parent.mkdir(parents=True)
            candidate_workflow.parent.mkdir(parents=True)
            trusted_workflow.write_bytes(TRUSTED_WORKFLOW_PATH.read_bytes())
            approved_candidate = (
                TRUSTED_WORKFLOW_PATH.read_bytes() + b"\n# approved migration fixture\n"
            )
            candidate_workflow.write_bytes(approved_candidate)
            pin_path = candidate_root / SERVER_PIN_PATH
            pin_path.parent.mkdir(parents=True, exist_ok=True)
            pin_path.write_text(
                '{"repository":"example-org/mcp-servers",'
                '"schema_version":"provider-monitor-server-pin/v1",'
                f'"source_commit":"{FROZEN_SERVER_SHA}"}}\n',
                encoding="utf-8",
            )
            verifier.APPROVED_TRUSTED_WORKFLOW_MIGRATION_SHA256 = hashlib.sha256(
                approved_candidate
            ).hexdigest()

            result = verifier.verify_candidate_trust_contract(
                trusted_config_root=trusted_root,
                candidate_config_root=candidate_root,
            )

        self.assertEqual("pass", result["status"])

    def test_trusted_candidate_inspection_rejects_second_privileged_workflow(
        self,
    ) -> None:
        verifier = _load_verifier()
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            trusted_root = root / "trusted"
            candidate_root = root / "candidate"
            workflow_relative = Path(
                ".github/workflows/provider-monitor-catalog-trusted.yml"
            )
            for config_root in (trusted_root, candidate_root):
                workflow_path = config_root / workflow_relative
                workflow_path.parent.mkdir(parents=True)
                workflow_path.write_bytes(TRUSTED_WORKFLOW_PATH.read_bytes())
            pin_path = candidate_root / SERVER_PIN_PATH
            pin_path.parent.mkdir(parents=True, exist_ok=True)
            pin_path.write_text(
                '{"repository":"example-org/mcp-servers",'
                '"schema_version":"provider-monitor-server-pin/v1",'
                f'"source_commit":"{FROZEN_SERVER_SHA}"}}\n',
                encoding="utf-8",
            )
            (candidate_root / ".github/workflows/future-secret.yml").write_text(
                "on: pull_request_target\n"
                "jobs:\n"
                "  future:\n"
                "    environment: enterprise-monitor-cross-repo-read\n"
                "    runs-on: ubuntu-24.04\n"
                "    steps:\n"
                "      - run: echo ${{ secrets.MCP_SERVERS_READ_SSH_KEY }}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                verifier.VerificationError,
                "candidate_privileged_workflow_scope_invalid",
            ):
                verifier.verify_candidate_trust_contract(
                    trusted_config_root=trusted_root,
                    candidate_config_root=candidate_root,
                )

    def test_trusted_candidate_inspection_rejects_escaped_privileged_tokens(
        self,
    ) -> None:
        verifier = _load_verifier()
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            trusted_root = root / "trusted"
            candidate_root = root / "candidate"
            workflow_relative = Path(
                ".github/workflows/provider-monitor-catalog-trusted.yml"
            )
            for config_root in (trusted_root, candidate_root):
                workflow_path = config_root / workflow_relative
                workflow_path.parent.mkdir(parents=True)
                workflow_path.write_bytes(TRUSTED_WORKFLOW_PATH.read_bytes())
            pin_path = candidate_root / SERVER_PIN_PATH
            pin_path.parent.mkdir(parents=True, exist_ok=True)
            pin_path.write_text(
                '{"repository":"example-org/mcp-servers",'
                '"schema_version":"provider-monitor-server-pin/v1",'
                f'"source_commit":"{FROZEN_SERVER_SHA}"}}\n',
                encoding="utf-8",
            )
            (candidate_root / ".github/workflows/escaped-secret.yml").write_text(
                'env_key: &env_key "environ\\u006dent"\n'
                '"on": push\n'
                "jobs:\n"
                "  leak:\n"
                "    ? *env_key\n"
                '    : "${{ format(\'enterprise-monitor-{0}-repo-read\', '
                '\'cross\') }}"\n'
                "    runs-on: ubuntu-24.04\n"
                "    steps:\n"
                "      - env:\n"
                '          KEY: "${{ secrets[format('
                '\'MCP_SERVERS_READ_{0}SH_KEY\', \'S\')] }}"\n'
                "        run: echo value-free\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                verifier.VerificationError,
                "candidate_privileged_workflow_scope_invalid",
            ):
                verifier.verify_candidate_trust_contract(
                    trusted_config_root=trusted_root,
                    candidate_config_root=candidate_root,
                )

    def test_candidate_trust_cli_emits_only_the_closed_server_revision(self) -> None:
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            trusted_root = root / "trusted"
            candidate_root = root / "candidate"
            workflow_relative = Path(
                ".github/workflows/provider-monitor-catalog-trusted.yml"
            )
            for config_root in (trusted_root, candidate_root):
                workflow_path = config_root / workflow_relative
                workflow_path.parent.mkdir(parents=True)
                workflow_path.write_bytes(TRUSTED_WORKFLOW_PATH.read_bytes())
            pin_path = candidate_root / SERVER_PIN_PATH
            pin_path.parent.mkdir(parents=True, exist_ok=True)
            pin_path.write_text(
                '{"repository":"example-org/mcp-servers",'
                '"schema_version":"provider-monitor-server-pin/v1",'
                f'"source_commit":"{FROZEN_SERVER_SHA}"}}\n',
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(VERIFIER_PATH),
                    "--trusted-config-root",
                    str(trusted_root),
                    "--inspect-candidate-trust",
                    str(candidate_root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(
            {
                "schema_version": "provider-monitor-candidate-trust/v1",
                "server_revision": FROZEN_SERVER_SHA,
                "status": "pass",
            },
            json.loads(completed.stdout),
        )

    def test_workflow_docs_preserve_the_catalog_activation_boundary(self) -> None:
        documentation = WORKFLOWS_DOC_PATH.read_text(encoding="utf-8")

        self.assertIn("Provider monitor catalog", documentation)
        self.assertIn("MCP_SERVERS_READ_SSH_KEY", documentation)
        self.assertIn("enterprise-monitor-cross-repo-read", documentation)
        self.assertIn("pull_request_target", documentation)
        self.assertIn("stdlib-only mutation suite", documentation)
        self.assertIn("independently pinned landed server revision", documentation)
        self.assertIn("provider-monitor-server-pin.v1.json", documentation)
        self.assertIn("byte-identical to the trusted base", documentation)
        self.assertIn("pin and binding rotate together", documentation)
        self.assertIn("two-stage activation", documentation)
        self.assertIn(
            "manual review cannot create the absent trusted context",
            documentation,
        )
        self.assertIn("fork pull requests fail closed", documentation)
        self.assertIn(
            "The live branch ruleset currently does not require a status check",
            documentation,
        )
        self.assertNotIn("merge-queue candidates", documentation)

    def test_required_ci_provider_catalog_job_is_secretless(self) -> None:
        workflow = VALIDATE_WORKFLOW_PATH.read_text(encoding="utf-8")
        catalog_job = _workflow_job(workflow, "provider-monitor-catalog")
        aggregate_job = _workflow_job(workflow, "validate")

        self.assertIn("ref: ${{ github.sha }}", catalog_job)
        self.assertEqual(1, catalog_job.count("git rev-parse --verify HEAD"))
        self.assertEqual(1, catalog_job.count("git status --porcelain=v1"))
        self.assertIn("python-version: \"3.12\"", catalog_job)
        self.assertIn(
            "python skills/_shared/tests/test_provider_monitor_source_catalog.py",
            catalog_job,
        )
        self.assertNotIn("pip install", catalog_job)
        self.assertNotIn("pytest", catalog_job)
        self.assertNotIn("secrets.", catalog_job)
        self.assertNotIn("MCP_SERVERS_READ_SSH_KEY", catalog_job)
        self.assertNotIn("repository: example-org/mcp-servers", catalog_job)
        self.assertNotIn("ssh-key:", catalog_job)
        self.assertNotIn("continue-on-error", catalog_job)
        self.assertNotIn("jsonschema[format]", catalog_job)
        self.assertNotIn("exit 0", catalog_job)
        self.assertNotIn("\n    if:", catalog_job)

        self.assertIn(
            "needs: [architecture-validate, managed-otel-auth-windows, "
            "provider-monitor-catalog]",
            aggregate_job,
        )
        self.assertIn("always()", aggregate_job)
        self.assertIn(
            "PROVIDER_CATALOG_RESULT: "
            "${{ needs.provider-monitor-catalog.result }}",
            aggregate_job,
        )
        self.assertIn(
            '"provider-monitor-catalog:${PROVIDER_CATALOG_RESULT}"',
            aggregate_job,
        )

    def test_trusted_catalog_workflow_separates_secret_fetch_from_candidate_code(
        self,
    ) -> None:
        workflow = TRUSTED_WORKFLOW_PATH.read_text(encoding="utf-8")
        fetch_job = _workflow_job(workflow, "fetch-trusted-server-bundle")
        verify_job = _workflow_job(workflow, "verify-candidate-catalog")
        dependabot_job = _workflow_job(workflow, "verify-dependabot-scope")
        summary_job = _workflow_job(workflow, "provider-monitor-catalog-trusted")

        self.assertIn("pull_request_target:", workflow)
        self.assertNotIn("\n  pull_request:\n", workflow)
        self.assertIn("name: enterprise-monitor-cross-repo-read", fetch_job)
        self.assertIn("deployment: false", fetch_job)
        self.assertIn(
            "github.event.pull_request.head.repo.full_name == github.repository",
            fetch_job,
        )
        self.assertIn("GITHUB_REF", fetch_job)
        self.assertIn("refs/heads/main", fetch_job)
        self.assertIn(
            "MCP_SERVERS_READ_SSH_KEY: "
            "${{ secrets.MCP_SERVERS_READ_SSH_KEY }}",
            fetch_job,
        )
        self.assertIn(
            'if [ -z "$MCP_SERVERS_READ_SSH_KEY" ]; then',
            fetch_job,
        )
        self.assertNotIn("github.token", fetch_job)
        self.assertIn("repository: example-org/mcp-servers", fetch_job)
        self.assertIn("actions/upload-artifact@", fetch_job)
        self.assertIn("path: server-bundle.tar", fetch_job)
        self.assertIn("archive: false", fetch_job)
        self.assertIn(
            "artifact_id: ${{ steps.upload_bundle.outputs.artifact-id }}",
            fetch_job,
        )
        self.assertIn(
            "artifact_digest: ${{ steps.upload_bundle.outputs.artifact-digest }}",
            fetch_job,
        )
        self.assertNotIn("candidate-config", fetch_job)
        self.assertNotIn("pull_request.head.sha", fetch_job)

        self.assertNotIn("secrets.", verify_job)
        self.assertNotIn("MCP_SERVERS_READ_SSH_KEY", verify_job)
        self.assertNotIn("ssh-key:", verify_job)
        self.assertNotIn("environment:", verify_job)
        self.assertIn("path: trusted-config", verify_job)
        self.assertIn("path: candidate-config", verify_job)
        self.assertIn("allow-unsafe-pr-checkout: true", verify_job)
        self.assertIn(
            "github.event.pull_request.head.repo.full_name == github.repository",
            verify_job,
        )
        self.assertIn("actions/download-artifact@", verify_job)
        self.assertIn(
            "artifact-ids: ${{ needs.fetch-trusted-server-bundle.outputs.artifact_id }}",
            verify_job,
        )
        self.assertIn("digest-mismatch: error", verify_job)
        self.assertIn("EXPECTED_ARTIFACT_DIGEST", verify_job)
        self.assertIn("artifact-download/server-bundle.tar", verify_job)
        self.assertIn(
            "python trusted-config/skills/_shared/"
            "verify_provider_monitor_source_catalog.py",
            verify_job,
        )
        self.assertIn("--config-root candidate-config", verify_job)
        self.assertIn("--server-bundle artifact-download/server-bundle.tar", verify_job)
        self.assertIn("--expected-bundle-sha256 \"$EXPECTED_ARTIFACT_DIGEST\"", verify_job)
        self.assertIn(
            "python candidate-config/skills/_shared/"
            "verify_provider_monitor_source_catalog.py",
            verify_job,
        )
        self.assertIn(
            "python -m unittest "
            "candidate-config/skills/_shared/tests/"
            "test_provider_monitor_source_catalog.py",
            verify_job,
        )
        self.assertNotIn("working-directory: candidate-config", verify_job)
        self.assertNotIn("pip install", verify_job)
        self.assertNotIn("pytest", verify_job)
        trusted_bundle_check = verify_job.index("--server-bundle-envelope")
        candidate_executable = verify_job.index(
            "python candidate-config/skills/_shared/"
            "verify_provider_monitor_source_catalog.py"
        )
        self.assertLess(trusted_bundle_check, candidate_executable)

        self.assertNotIn("secrets.", dependabot_job)
        self.assertIn("provider contract paths are unchanged", dependabot_job)
        self.assertIn("always()", summary_job)
        self.assertIn("FETCH_RESULT", summary_job)
        self.assertIn("VERIFY_RESULT", summary_job)
        self.assertIn("DEPENDABOT_RESULT", summary_job)
        self.assertIn("rejects fork pull requests", summary_job)
        self.assertNotIn("github.actor", workflow)

    def test_trusted_workflow_inspects_pin_before_secret_fetch(self) -> None:
        workflow = TRUSTED_WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn("  inspect-candidate-trust:\n", workflow)
        inspect_job = _workflow_job(workflow, "inspect-candidate-trust")
        fetch_job = _workflow_job(workflow, "fetch-trusted-server-bundle")
        verify_job = _workflow_job(workflow, "verify-candidate-catalog")
        pin = json.loads(
            (SHARED_DIR.parents[1] / SERVER_PIN_PATH).read_text(encoding="utf-8")
        )

        self.assertEqual(
            {
                "repository": "example-org/mcp-servers",
                "schema_version": "provider-monitor-server-pin/v1",
                "source_commit": FROZEN_SERVER_SHA,
            },
            pin,
        )
        self.assertNotIn("secrets.", inspect_job)
        self.assertNotIn("environment:", inspect_job)
        self.assertIn("path: trusted-config", inspect_job)
        self.assertIn("path: candidate-config", inspect_job)
        self.assertIn(
            "candidate_revision: ${{ steps.candidate.outputs.candidate_sha }}",
            inspect_job,
        )
        self.assertIn('gh api "repos/$REPOSITORY/pulls/$PULL_NUMBER"', inspect_job)
        # REPLACED 2026-08-26, same reason as the sibling assertion in
        # scripts/test_provider_monitor_trusted_workflow.py: this pinned the retry
        # CONSTRUCT and its 30-second budget, not a property. That budget was measured
        # too short -- on #2151 and #2152 GitHub left mergeable_state "unknown" well
        # past 30s with the platform operational, so the step failed and the lane
        # cascaded off it; a plain re-run passed with no content change.
        #
        # I MISSED THIS ONE on the first pass: the variant hunt grepped
        # .github/workflows/ for the literal and never searched the test suites, so the
        # fix went green locally and red in CI on a second pin of the same string.
        # Asserted here as properties, so a future budget change does not read as a
        # regression -- while the bounded-poll and named-cause guarantees stay pinned.
        self.assertRegex(inspect_job, r"budget_seconds=\d+")
        self.assertIn('elapsed" -ge "$budget_seconds', inspect_job)
        self.assertIn("ASYNC mergeability computation", inspect_job)
        self.assertIn("API/permissions failure", inspect_job)
        self.assertNotIn("for attempt in {1..10}", inspect_job)
        self.assertIn('echo "candidate_sha=$candidate_sha" >> "$GITHUB_OUTPUT"', inspect_job)
        self.assertIn(
            "EXPECTED_CANDIDATE_SHA: ${{ steps.candidate.outputs.candidate_sha }}",
            inspect_job,
        )
        self.assertNotIn("github.event.pull_request.merge_commit_sha", inspect_job)
        self.assertIn("--inspect-candidate-trust candidate-config", inspect_job)
        self.assertIn("--trusted-config-root trusted-config", inspect_job)
        self.assertIn("server_revision", inspect_job)

        self.assertIn("needs: inspect-candidate-trust", fetch_job)
        self.assertIn(
            "MCP_SERVERS_VERIFIED_SHA: "
            "${{ needs.inspect-candidate-trust.outputs.server_revision }}",
            fetch_job,
        )
        self.assertNotIn(FROZEN_SERVER_SHA, fetch_job)
        self.assertNotIn("candidate-config", fetch_job)
        self.assertIn("refs/remotes/origin/main", fetch_job)
        self.assertIn(
            'git -C mcp-servers merge-base --is-ancestor '
            '"$MCP_SERVERS_VERIFIED_SHA" refs/remotes/origin/main',
            fetch_job,
        )
        self.assertIn(
            "MCP_SERVERS_VERIFIED_SHA: "
            "${{ needs.fetch-trusted-server-bundle.outputs.server_revision }}",
            verify_job,
        )

    def test_trusted_workflow_authenticates_envelope_before_candidate_binding(
        self,
    ) -> None:
        workflow = TRUSTED_WORKFLOW_PATH.read_text(encoding="utf-8")
        verify_job = _workflow_job(workflow, "verify-candidate-catalog")

        self.assertIn(
            "--server-bundle-envelope artifact-download/server-bundle.tar",
            verify_job,
        )
        self.assertLess(
            verify_job.index("--server-bundle-envelope"),
            verify_job.index("path: candidate-config"),
        )
        self.assertNotIn(
            "--config-root trusted-config \\\n+            --server-bundle artifact-download/server-bundle.tar",
            verify_job,
        )

    def test_trusted_catalog_checkout_is_independent_of_reviewed_floor(self) -> None:
        workflow = TRUSTED_WORKFLOW_PATH.read_text(encoding="utf-8")
        pin = json.loads(
            (SHARED_DIR.parents[1] / SERVER_PIN_PATH).read_text(encoding="utf-8")
        )
        binding = json.loads(
            (SHARED_DIR / "provider-monitor-source-bindings.v1.json").read_text(
                encoding="utf-8"
            )
        )
        reviewed_floor = binding["catalog"]["reviewed_revision"]

        self.assertEqual(
            "39f63ad3efa34dda3c6a8b9930d44aea9a44bc12",
            reviewed_floor,
        )
        self.assertNotEqual(reviewed_floor, FROZEN_SERVER_SHA)
        self.assertEqual(
            FROZEN_SERVER_SHA,
            pin["source_commit"],
        )
        self.assertNotIn(FROZEN_SERVER_SHA, workflow)
        self.assertIn("ref: ${{ env.MCP_SERVERS_VERIFIED_SHA }}", workflow)
        self.assertNotIn(f"MCP_SERVERS_VERIFIED_SHA: {reviewed_floor}", workflow)

    def test_trusted_catalog_authoritative_checkout_uses_merge_candidate(self) -> None:
        workflow = TRUSTED_WORKFLOW_PATH.read_text(encoding="utf-8")
        verify_job = _workflow_job(workflow, "verify-candidate-catalog")

        self.assertIn(
            "EXPECTED_CANDIDATE_SHA: "
            "${{ needs.fetch-trusted-server-bundle.outputs.candidate_revision }}",
            verify_job,
        )
        self.assertIn("ref: ${{ env.EXPECTED_CANDIDATE_SHA }}", verify_job)
        self.assertIn(
            'if ! [[ "$EXPECTED_CANDIDATE_SHA" =~ ^[0-9a-f]{40}$ ]]; then',
            verify_job,
        )
        self.assertIn(
            'git -C candidate-config rev-parse --verify HEAD)',
            verify_job,
        )
        self.assertIn(
            "git -C candidate-config status --porcelain=v1 --untracked-files=all",
            verify_job,
        )
        self.assertNotIn("pull_request.head.sha", verify_job)
        self.assertNotIn("github.event.pull_request.merge_commit_sha", verify_job)

    def test_candidate_config_symlinks_fail_before_content_reads(self) -> None:
        verifier = _load_verifier()
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_root = root / "claude-config"
            server_root = root / "mcp-servers"
            self._write_fixture(config_root, server_root)
            external = root / "external.json"
            external.write_text("{}", encoding="utf-8")

            for relative_path in verifier.CONFIG_INPUT_RELATIVE_PATHS:
                with self.subTest(relative_path=relative_path):
                    candidate = config_root / relative_path
                    original = candidate.read_bytes()
                    candidate.unlink()
                    try:
                        candidate.symlink_to(external)
                    except OSError as exc:
                        self.skipTest(f"symlink creation unavailable: {exc}")
                    with self.assertRaisesRegex(
                        verifier.VerificationError,
                        "config_candidate_path_unsafe",
                    ):
                        self._verify(verifier, config_root, server_root)
                    candidate.unlink()
                    candidate.write_bytes(original)

    def test_server_bundle_requires_allowlisted_files_and_reviewed_ancestry(
        self,
    ) -> None:
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_root = root / "claude-config"
            server_root = root / "mcp-servers"
            bundle_path = root / "server-bundle.tar"
            self._write_fixture(config_root, server_root)
            binding = self._read_binding(config_root)
            reviewed_revision = binding["catalog"]["reviewed_revision"]
            verified_revision = "b" * 40
            self._write_server_bundle(
                server_root,
                bundle_path,
                verified_revision=verified_revision,
                ancestor_revisions=[verified_revision, reviewed_revision],
            )
            artifact_digest = hashlib.sha256(bundle_path.read_bytes()).hexdigest()

            completed = subprocess.run(
                [
                    sys.executable,
                    str(VERIFIER_PATH),
                    "--config-root",
                    str(config_root),
                    "--server-bundle",
                    str(bundle_path),
                    "--expected-servers-sha",
                    verified_revision,
                    "--expected-bundle-sha256",
                    artifact_digest,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual("pass", json.loads(completed.stdout)["status"])

            self._write_server_bundle(
                server_root,
                bundle_path,
                verified_revision=verified_revision,
                ancestor_revisions=[verified_revision],
            )
            missing_ancestor_args = [
                *completed.args[:-1],
                hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
            ]
            missing_ancestor = subprocess.run(
                missing_ancestor_args,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, missing_ancestor.returncode)
            self.assertIn(
                "mcp_servers_reviewed_revision_not_ancestor",
                missing_ancestor.stderr,
            )

            self._write_server_bundle(
                server_root,
                bundle_path,
                verified_revision=verified_revision,
                ancestor_revisions=[verified_revision, reviewed_revision],
                extra_members=[("unexpected.txt", b"drift\n", tarfile.REGTYPE)],
            )
            unexpected_args = [
                *completed.args[:-1],
                hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
            ]
            unexpected_file = subprocess.run(
                unexpected_args,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, unexpected_file.returncode)
            self.assertIn("server_bundle_shape_mismatch", unexpected_file.stderr)

    def test_server_bundle_envelope_is_independent_of_base_binding(self) -> None:
        verifier = _load_verifier()
        self.assertTrue(hasattr(verifier, "verify_server_bundle_envelope"))
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_root = root / "claude-config"
            server_root = root / "mcp-servers"
            bundle_path = root / "server-bundle.tar"
            self._write_fixture(config_root, server_root)
            verified_revision = "b" * 40
            self._write_server_bundle(
                server_root,
                bundle_path,
                verified_revision=verified_revision,
                ancestor_revisions=[verified_revision, "a" * 40],
            )

            result = verifier.verify_server_bundle_envelope(
                server_bundle=bundle_path,
                expected_mcp_servers_revision=verified_revision,
                expected_bundle_sha256=hashlib.sha256(
                    bundle_path.read_bytes()
                ).hexdigest(),
            )

        self.assertEqual(
            {
                "ancestor_count": 2,
                "schema_version": "provider-monitor-server-bundle-envelope/v1",
                "server_revision": verified_revision,
                "status": "pass",
            },
            result,
        )

    def test_server_bundle_envelope_cli_is_binding_independent(self) -> None:
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_root = root / "claude-config"
            server_root = root / "mcp-servers"
            bundle_path = root / "server-bundle.tar"
            self._write_fixture(config_root, server_root)
            verified_revision = "b" * 40
            self._write_server_bundle(
                server_root,
                bundle_path,
                verified_revision=verified_revision,
                ancestor_revisions=[verified_revision, "a" * 40],
            )
            digest = hashlib.sha256(bundle_path.read_bytes()).hexdigest()

            completed = subprocess.run(
                [
                    sys.executable,
                    str(VERIFIER_PATH),
                    "--server-bundle-envelope",
                    str(bundle_path),
                    "--expected-servers-sha",
                    verified_revision,
                    "--expected-bundle-sha256",
                    digest,
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(
            "provider-monitor-server-bundle-envelope/v1",
            json.loads(completed.stdout)["schema_version"],
        )

    def test_server_bundle_rejects_links_traversal_duplicate_keys_and_drift(
        self,
    ) -> None:
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_root = root / "claude-config"
            server_root = root / "mcp-servers"
            bundle_path = root / "server-bundle.tar"
            self._write_fixture(config_root, server_root)
            reviewed_revision = self._read_binding(config_root)["catalog"][
                "reviewed_revision"
            ]
            verified_revision = "b" * 40

            cases = (
                (
                    "link",
                    {"extra_members": [("escape", b"", tarfile.SYMTYPE)]},
                    "server_bundle_path_unsafe",
                ),
                (
                    "traversal",
                    {"extra_members": [("../escape", b"drift", tarfile.REGTYPE)]},
                    "server_bundle_path_unsafe",
                ),
                (
                    "duplicate_manifest_key",
                    {"duplicate_manifest_key": True},
                    "duplicate_json_key",
                ),
                (
                    "payload_digest",
                    {"payload_drift_after_manifest": True},
                    "server_bundle_payload_mismatch",
                ),
                (
                    "payload_mode",
                    {"member_mode": 0o600},
                    "server_bundle_payload_mismatch",
                ),
            )
            for name, options, error_code in cases:
                with self.subTest(name=name):
                    self._write_server_bundle(
                        server_root,
                        bundle_path,
                        verified_revision=verified_revision,
                        ancestor_revisions=[verified_revision, reviewed_revision],
                        **options,
                    )
                    completed = subprocess.run(
                        [
                            sys.executable,
                            str(VERIFIER_PATH),
                            "--config-root",
                            str(config_root),
                            "--server-bundle",
                            str(bundle_path),
                            "--expected-servers-sha",
                            verified_revision,
                            "--expected-bundle-sha256",
                            hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(1, completed.returncode)
                    self.assertIn(error_code, completed.stderr)

            self._write_server_bundle(
                server_root,
                bundle_path,
                verified_revision=verified_revision,
                ancestor_revisions=[verified_revision, reviewed_revision],
            )
            artifact_digest_mismatch = subprocess.run(
                [
                    sys.executable,
                    str(VERIFIER_PATH),
                    "--config-root",
                    str(config_root),
                    "--server-bundle",
                    str(bundle_path),
                    "--expected-servers-sha",
                    verified_revision,
                    "--expected-bundle-sha256",
                    "0" * 64,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, artifact_digest_mismatch.returncode)
            self.assertIn(
                "server_bundle_artifact_digest_mismatch",
                artifact_digest_mismatch.stderr,
            )

    def test_clean_catalog_partitions_all_sources_by_provider_role(self) -> None:
        self.assertTrue(
            VERIFIER_PATH.is_file(),
            "provider-monitor source-catalog verifier is missing",
        )
        verifier = _load_verifier()

        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_root = root / "claude-config"
            server_root = root / "mcp-servers"
            self._write_fixture(config_root, server_root)

            result = verifier.verify_repository_contract(
                config_root=config_root,
                mcp_servers_root=server_root,
                repository_state=verifier.RepositoryState(
                    revision="b" * 40,
                    clean=True,
                    reviewed_revision_is_ancestor=True,
                ),
                expected_mcp_servers_revision="b" * 40,
            )

        self.assertEqual("pass", result["status"])
        self.assertEqual(4, result["source_count"])
        self.assertEqual(
            {"anthropic": 2, "openai": 2},
            result["provider_source_counts"],
        )
        self.assertEqual(
            {
                "cc-monitor": 2,
                "openai-monitor": 2,
                "enterprise-ai-monitor": 4,
            },
            result["skill_source_counts"],
        )

    def test_catalog_identity_mutations_fail_after_document_reseal(self) -> None:
        verifier = _load_verifier()
        for mutation in ("missing", "extra", "renamed", "provider_swap"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as tempdir:
                root = Path(tempdir)
                config_root = root / "claude-config"
                server_root = root / "mcp-servers"
                self._write_fixture(config_root, server_root)
                catalog_path = self._catalog_path(server_root)
                catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
                sources = catalog["sources"]
                if mutation == "missing":
                    sources[:] = [
                        source
                        for source in sources
                        if source["source_registry_id"] != "anthropic_beta"
                    ]
                elif mutation == "extra":
                    sources.append(
                        {
                            "source_registry_id": "anthropic_extra",
                            "provider": "anthropic",
                            "source_generation": catalog["source_generation"],
                        }
                    )
                elif mutation == "renamed":
                    next(
                        source
                        for source in sources
                        if source["source_registry_id"] == "anthropic_beta"
                    )["source_registry_id"] = "anthropic_renamed"
                else:
                    next(
                        source
                        for source in sources
                        if source["source_registry_id"] == "anthropic_beta"
                    )["provider"] = "openai"
                    next(
                        source
                        for source in sources
                        if source["source_registry_id"] == "openai_beta"
                    )["provider"] = "anthropic"
                catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
                self._reseal_catalog_without_partition_digest(
                    config_root, server_root
                )

                with self.assertRaisesRegex(
                    verifier.VerificationError,
                    "catalog_provider_source_set_digest_mismatch",
                ):
                    self._verify(verifier, config_root, server_root)

    def test_stale_generation_and_digest_fail_closed(self) -> None:
        verifier = _load_verifier()
        cases = ("generation", "digest")
        for mutation in cases:
            with self.subTest(mutation=mutation), TemporaryDirectory() as tempdir:
                root = Path(tempdir)
                config_root = root / "claude-config"
                server_root = root / "mcp-servers"
                self._write_fixture(config_root, server_root)
                catalog_path = self._catalog_path(server_root)
                catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
                if mutation == "generation":
                    catalog["source_generation"] = "repository-census/stale/v1"
                    for source in catalog["sources"]:
                        source["source_generation"] = catalog["source_generation"]
                else:
                    catalog["unsealed_change"] = True
                catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

                expected = (
                    "catalog_generation_mismatch"
                    if mutation == "generation"
                    else "catalog_digest_mismatch"
                )
                with self.assertRaisesRegex(verifier.VerificationError, expected):
                    self._verify(verifier, config_root, server_root)

    def test_malformed_types_and_oversized_integers_are_sanitized(self) -> None:
        verifier = _load_verifier()
        cases = (
            ("catalog_provider", "catalog_source_provider_invalid"),
            ("emitter_provider", "emitter_provider_invalid"),
            ("emitter_source_id", "emitter_source_identity_invalid"),
            ("oversized_integer", "catalog_unreadable"),
        )
        for mutation, error_code in cases:
            with self.subTest(mutation=mutation), TemporaryDirectory() as tempdir:
                root = Path(tempdir)
                config_root = root / "claude-config"
                server_root = root / "mcp-servers"
                self._write_fixture(config_root, server_root)
                self._git(server_root, "init")
                self._git(server_root, "add", ".")
                self._git(server_root, "commit", "-m", "reviewed catalog")
                reviewed_revision = self._git(
                    server_root, "rev-parse", "HEAD"
                ).strip()
                binding = self._read_binding(config_root)
                binding["catalog"]["reviewed_revision"] = reviewed_revision
                self._write_binding(config_root, binding)

                if mutation == "oversized_integer":
                    catalog_path = self._catalog_path(server_root)
                    body = catalog_path.read_text(encoding="utf-8")
                    body = body.replace(
                        '"sources":',
                        f'"oversized": {"9" * 100_000}, "sources":',
                        1,
                    )
                    catalog_path.write_text(body, encoding="utf-8")
                elif mutation == "catalog_provider":
                    catalog_path = self._catalog_path(server_root)
                    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
                    catalog["sources"][0]["provider"] = ["payload_echo_sentinel"]
                    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
                    self._reseal_catalog_documents(config_root, server_root)
                else:
                    registry_path = self._emitter_path(server_root)
                    registry = json.loads(registry_path.read_text(encoding="utf-8"))
                    field = (
                        "provider"
                        if mutation == "emitter_provider"
                        else "source_registry_id"
                    )
                    registry["emitters"][0][field] = ["payload_echo_sentinel"]
                    registry_path.write_text(json.dumps(registry), encoding="utf-8")
                    self._reseal_emitter_registry(config_root, server_root)

                with self.assertRaisesRegex(
                    verifier.VerificationError, f"^{error_code}$"
                ):
                    self._verify(verifier, config_root, server_root)

                self._git(server_root, "add", ".")
                self._git(server_root, "commit", "-m", f"mutate {mutation}")
                mutated_revision = self._git(
                    server_root, "rev-parse", "HEAD"
                ).strip()
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(VERIFIER_PATH),
                        "--config-root",
                        str(config_root),
                        "--mcp-servers",
                        str(server_root),
                        "--expected-servers-sha",
                        mutated_revision,
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(1, completed.returncode)
                self.assertEqual(
                    f"provider-monitor-source-catalog: {error_code}\n",
                    completed.stderr,
                )
                self.assertEqual("", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)
                self.assertNotIn("payload_echo_sentinel", completed.stderr)

    def test_zero_unknown_emitter_bucket_is_valid(self) -> None:
        verifier = _load_verifier()
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_root = root / "claude-config"
            server_root = root / "mcp-servers"
            self._write_fixture(config_root, server_root)

            registry_path = self._emitter_path(server_root)
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["emitters"] = [
                emitter
                for emitter in registry["emitters"]
                if emitter["provider"] != "unknown"
            ]
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            binding = self._read_binding(config_root)
            binding["emitter_registry"]["emitter_count"] = 2
            binding["emitter_registry"]["provider_emitter_counts"] = {
                "anthropic": 1,
                "openai": 1,
                "unknown": 0,
            }
            self._write_binding(config_root, binding)
            self._reseal_emitter_registry(config_root, server_root)

            result = self._verify(verifier, config_root, server_root)
            self.assertEqual("pass", result["status"])

            self._git(server_root, "init")
            self._git(server_root, "add", ".")
            self._git(server_root, "commit", "-m", "zero unknown emitter bucket")
            revision = self._git(server_root, "rev-parse", "HEAD").strip()
            binding = self._read_binding(config_root)
            binding["catalog"]["reviewed_revision"] = revision
            self._write_binding(config_root, binding)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(VERIFIER_PATH),
                    "--config-root",
                    str(config_root),
                    "--mcp-servers",
                    str(server_root),
                    "--expected-servers-sha",
                    revision,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual("pass", json.loads(completed.stdout)["status"])

    def test_skill_binding_and_marketplace_copy_drift_fail_closed(self) -> None:
        verifier = _load_verifier()
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_root = root / "claude-config"
            server_root = root / "mcp-servers"
            self._write_fixture(config_root, server_root)
            binding = self._read_binding(config_root)
            binding["skill_bindings"]["openai-monitor"]["providers"] = [
                "anthropic"
            ]
            self._write_binding(config_root, binding)
            with self.assertRaisesRegex(
                verifier.VerificationError, "skill_binding_role_mismatch"
            ):
                self._verify(verifier, config_root, server_root)

        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_root = root / "claude-config"
            server_root = root / "mcp-servers"
            self._write_fixture(config_root, server_root)
            marketplace_skill = (
                config_root
                / "marketplace/knowledge-ops/skills/openai-monitor/SKILL.md"
            )
            marketplace_skill.write_text(
                marketplace_skill.read_text(encoding="utf-8") + "drift\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                verifier.VerificationError, "marketplace_skill_copy_drift"
            ):
                self._verify(verifier, config_root, server_root)

    def test_checkout_identity_cleanliness_and_ancestry_fail_closed(self) -> None:
        verifier = _load_verifier()
        cases = (
            (
                verifier.RepositoryState("b" * 40, True, True),
                "c" * 40,
                "mcp_servers_expected_revision_mismatch",
            ),
            (
                verifier.RepositoryState("b" * 40, False, True),
                "b" * 40,
                "mcp_servers_checkout_dirty",
            ),
            (
                verifier.RepositoryState("b" * 40, True, False),
                "b" * 40,
                "mcp_servers_reviewed_revision_not_ancestor",
            ),
        )
        for state, expected_revision, error in cases:
            with self.subTest(error=error), TemporaryDirectory() as tempdir:
                root = Path(tempdir)
                config_root = root / "claude-config"
                server_root = root / "mcp-servers"
                self._write_fixture(config_root, server_root)
                with self.assertRaisesRegex(verifier.VerificationError, error):
                    verifier.verify_repository_contract(
                        config_root=config_root,
                        mcp_servers_root=server_root,
                        repository_state=state,
                        expected_mcp_servers_revision=expected_revision,
                    )

    def test_cli_binds_exact_clean_descendant_checkout(self) -> None:
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            config_root = root / "claude-config"
            server_root = root / "mcp-servers"
            self._write_fixture(config_root, server_root)
            self._git(server_root, "init")
            self._git(server_root, "add", ".")
            self._git(server_root, "commit", "-m", "reviewed catalog")
            reviewed_revision = self._git(server_root, "rev-parse", "HEAD").strip()
            binding = self._read_binding(config_root)
            binding["catalog"]["reviewed_revision"] = reviewed_revision
            self._write_binding(config_root, binding)

            (server_root / "UNRELATED.md").write_text("descendant\n", encoding="utf-8")
            self._git(server_root, "add", "UNRELATED.md")
            self._git(server_root, "commit", "-m", "unrelated descendant")
            descendant_revision = self._git(server_root, "rev-parse", "HEAD").strip()

            command = [
                sys.executable,
                str(VERIFIER_PATH),
                "--config-root",
                str(config_root),
                "--mcp-servers",
                str(server_root),
                "--expected-servers-sha",
                descendant_revision,
            ]
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual("pass", json.loads(completed.stdout)["status"])

            wrong_revision = subprocess.run(
                command[:-1] + [reviewed_revision],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, wrong_revision.returncode)
            self.assertIn(
                "mcp_servers_expected_revision_mismatch", wrong_revision.stderr
            )

            (server_root / "UNRELATED.md").write_text("dirty\n", encoding="utf-8")
            dirty = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, dirty.returncode)
            self.assertIn("mcp_servers_checkout_dirty", dirty.stderr)

    def test_committed_binding_and_marketplace_are_exact(self) -> None:
        config_root = SHARED_DIR.parents[1]
        binding_path = config_root / (
            "skills/_shared/provider-monitor-source-bindings.v1.json"
        )
        self.assertTrue(binding_path.is_file(), "committed source binding is missing")
        binding = json.loads(binding_path.read_text(encoding="utf-8"))

        self.assertEqual(
            "39f63ad3efa34dda3c6a8b9930d44aea9a44bc12",
            binding["catalog"]["reviewed_revision"],
        )
        self.assertEqual(
            "repository-census/2026-08-15/v1",
            binding["catalog"]["source_generation"],
        )
        self.assertEqual(
            "0c69f8e54e790a848b1b7078f5b0a73d8b3562a21a6cce77d78684c0198c9075",
            binding["catalog"]["document_sha256"],
        )
        self.assertEqual(61, binding["catalog"]["source_count"])
        self.assertEqual(
            {"anthropic": 42, "openai": 19},
            binding["catalog"]["provider_source_counts"],
        )
        self.assertEqual(
            "73c1b3d28d47283cda1b6d5fd8e12d6c05be14d8d462bcdbc1863ad7d0c252b5",
            binding["emitter_registry"]["document_sha256"],
        )
        self.assertEqual(63, binding["emitter_registry"]["emitter_count"])
        self.assertEqual(
            {"anthropic": 38, "openai": 24, "unknown": 1},
            binding["emitter_registry"]["provider_emitter_counts"],
        )
        self.assertEqual(
            "source_identity_and_routing_only", binding["truth_scope"]
        )
        self.assertNotIn("availability", json.dumps(binding, sort_keys=True).lower())

        marketplace_binding = (
            config_root
            / "marketplace/knowledge-ops/skills/_shared"
            / binding_path.name
        )
        self.assertEqual(binding_path.read_bytes(), marketplace_binding.read_bytes())
        for skill_name in ("cc-monitor", "openai-monitor", "enterprise-ai-monitor"):
            source_skill = config_root / "skills" / skill_name / "SKILL.md"
            marketplace_skill = (
                config_root
                / "marketplace/knowledge-ops/skills"
                / skill_name
                / "SKILL.md"
            )
            self.assertEqual(source_skill.read_bytes(), marketplace_skill.read_bytes())
            marker = (
                "../_shared/provider-monitor-source-bindings.v1.json"
                f"#skill_bindings.{skill_name}"
            )
            self.assertEqual(1, source_skill.read_text(encoding="utf-8").count(marker))

    @staticmethod
    def _write_fixture(config_root: Path, server_root: Path) -> None:
        generation = "repository-census/test/v1"
        catalog = {
            "schema_version": "provider-source-catalog/v1",
            "source_generation": generation,
            "sources": [
                {
                    "source_registry_id": "anthropic_alpha",
                    "provider": "anthropic",
                    "source_generation": generation,
                },
                {
                    "source_registry_id": "anthropic_beta",
                    "provider": "anthropic",
                    "source_generation": generation,
                },
                {
                    "source_registry_id": "openai_alpha",
                    "provider": "openai",
                    "source_generation": generation,
                },
                {
                    "source_registry_id": "openai_beta",
                    "provider": "openai",
                    "source_generation": generation,
                },
            ],
        }
        catalog_sha = _canonical_sha256(catalog)
        emitters = {
            "schema_version": "expected-emitter-registry/v1",
            "source_generation": generation,
            "source_catalog_sha256": catalog_sha,
            "emitters": [
                {
                    "emitter_registry_id": "anthropic_alpha_collector",
                    "provider": "anthropic",
                    "source_registry_id": "anthropic_alpha",
                },
                {
                    "emitter_registry_id": "openai_alpha_collector",
                    "provider": "openai",
                    "source_registry_id": "openai_alpha",
                },
                {
                    "emitter_registry_id": "unknown_route",
                    "provider": "unknown",
                    "source_registry_id": "unknown/quarantine",
                },
            ],
        }
        emitter_sha = _canonical_sha256(emitters)

        catalog_path = (
            server_root
            / "scripts/enterprise_ai_monitor/provider_source_catalog.v1.json"
        )
        emitter_path = (
            server_root
            / "scripts/enterprise_ai_monitor/expected_emitter_registry.v1.json"
        )
        catalog_path.parent.mkdir(parents=True)
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        emitter_path.write_text(json.dumps(emitters), encoding="utf-8")

        bindings = {
            "schema_version": "provider-monitor-skill-bindings/v1",
            "truth_scope": "source_identity_and_routing_only",
            "catalog": {
                "repository": "example-org/mcp-servers",
                "reviewed_revision": "a" * 40,
                "path": "scripts/enterprise_ai_monitor/provider_source_catalog.v1.json",
                "schema_version": "provider-source-catalog/v1",
                "source_generation": generation,
                "document_sha256": catalog_sha,
                "source_count": 4,
                "provider_source_counts": {"anthropic": 2, "openai": 2},
                "provider_source_set_sha256": {
                    "anthropic": _identifier_set_sha256(
                        ["anthropic_alpha", "anthropic_beta"]
                    ),
                    "openai": _identifier_set_sha256(
                        ["openai_alpha", "openai_beta"]
                    ),
                },
            },
            "emitter_registry": {
                "path": "scripts/enterprise_ai_monitor/expected_emitter_registry.v1.json",
                "schema_version": "expected-emitter-registry/v1",
                "source_generation": generation,
                "document_sha256": emitter_sha,
                "emitter_count": 3,
                "provider_emitter_counts": {
                    "anthropic": 1,
                    "openai": 1,
                    "unknown": 1,
                },
            },
            "skill_bindings": {
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
            },
        }
        binding_path = (
            config_root / "skills/_shared/provider-monitor-source-bindings.v1.json"
        )
        binding_path.parent.mkdir(parents=True)
        binding_path.write_text(json.dumps(bindings), encoding="utf-8")

        for skill_name in ("cc-monitor", "openai-monitor", "enterprise-ai-monitor"):
            marker = (
                "../_shared/provider-monitor-source-bindings.v1.json"
                f"#skill_bindings.{skill_name}"
            )
            skill_path = config_root / "skills" / skill_name / "SKILL.md"
            marketplace_path = (
                config_root
                / "marketplace/knowledge-ops/skills"
                / skill_name
                / "SKILL.md"
            )
            skill_path.parent.mkdir(parents=True)
            marketplace_path.parent.mkdir(parents=True)
            content = f"Source catalog binding: `{marker}`.\n"
            skill_path.write_text(content, encoding="utf-8")
            marketplace_path.write_text(content, encoding="utf-8")

        marketplace_binding = (
            config_root
            / "marketplace/knowledge-ops/skills/_shared"
            / binding_path.name
        )
        marketplace_binding.parent.mkdir(parents=True)
        marketplace_binding.write_bytes(binding_path.read_bytes())

    @staticmethod
    def _catalog_path(server_root: Path) -> Path:
        return (
            server_root
            / "scripts/enterprise_ai_monitor/provider_source_catalog.v1.json"
        )

    @staticmethod
    def _emitter_path(server_root: Path) -> Path:
        return (
            server_root
            / "scripts/enterprise_ai_monitor/expected_emitter_registry.v1.json"
        )

    @staticmethod
    def _binding_path(config_root: Path) -> Path:
        return config_root / "skills/_shared/provider-monitor-source-bindings.v1.json"

    @classmethod
    def _read_binding(cls, config_root: Path) -> dict:
        return json.loads(cls._binding_path(config_root).read_text(encoding="utf-8"))

    @classmethod
    def _write_binding(cls, config_root: Path, binding: dict) -> None:
        binding_path = cls._binding_path(config_root)
        binding_path.write_text(json.dumps(binding), encoding="utf-8")
        marketplace_binding = (
            config_root
            / "marketplace/knowledge-ops/skills/_shared"
            / binding_path.name
        )
        marketplace_binding.write_bytes(binding_path.read_bytes())

    @classmethod
    def _write_server_bundle(
        cls,
        server_root: Path,
        bundle_path: Path,
        *,
        verified_revision: str,
        ancestor_revisions: list[str],
        extra_members: list[tuple[str, bytes, bytes]] | None = None,
        duplicate_manifest_key: bool = False,
        payload_drift_after_manifest: bool = False,
        member_mode: int = 0o644,
    ) -> None:
        catalog_relative = Path(
            "scripts/enterprise_ai_monitor/provider_source_catalog.v1.json"
        )
        emitter_relative = Path(
            "scripts/enterprise_ai_monitor/expected_emitter_registry.v1.json"
        )
        catalog_bytes = (server_root / catalog_relative).read_bytes()
        emitter_bytes = (server_root / emitter_relative).read_bytes()
        ancestor_bytes = (
            "\n".join(ancestor_revisions).encode("ascii") + b"\n"
        )
        payloads = {
            "ancestor-revisions.txt": ancestor_bytes,
            catalog_relative.as_posix(): catalog_bytes,
            emitter_relative.as_posix(): emitter_bytes,
        }
        manifest = {
            "schema_version": "provider-monitor-server-bundle/v1",
            "repository": "example-org/mcp-servers",
            "source_commit": verified_revision,
            "ancestor_count": len(ancestor_revisions),
            "files": [
                {
                    "path": path,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size": len(content),
                    "mode": "0644",
                }
                for path, content in sorted(payloads.items())
            ],
        }
        manifest_bytes = (
            json.dumps(
                manifest,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
        if duplicate_manifest_key:
            manifest_bytes = manifest_bytes.replace(
                b'{"ancestor_count":',
                b'{"repository":"example-org/mcp-servers",'
                b'"ancestor_count":',
                1,
            )
        if payload_drift_after_manifest:
            payloads[catalog_relative.as_posix()] += b"\n"

        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(bundle_path, "w", format=tarfile.USTAR_FORMAT) as bundle:
            members = [
                ("manifest.json", manifest_bytes, tarfile.REGTYPE),
                *(
                    (path, content, tarfile.REGTYPE)
                    for path, content in sorted(payloads.items())
                ),
                *(extra_members or []),
            ]
            for name, content, member_type in members:
                info = tarfile.TarInfo(name)
                info.type = member_type
                info.mode = member_mode
                info.mtime = 0
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                if member_type == tarfile.SYMTYPE:
                    info.linkname = "../escape"
                    info.size = 0
                    bundle.addfile(info)
                else:
                    info.size = len(content)
                    bundle.addfile(info, io.BytesIO(content))

    @classmethod
    def _reseal_catalog_without_partition_digest(
        cls, config_root: Path, server_root: Path
    ) -> None:
        catalog = json.loads(
            cls._catalog_path(server_root).read_text(encoding="utf-8")
        )
        binding = cls._read_binding(config_root)
        binding["catalog"]["document_sha256"] = _canonical_sha256(catalog)
        binding["catalog"]["source_count"] = len(catalog["sources"])
        provider_counts = {"anthropic": 0, "openai": 0}
        for source in catalog["sources"]:
            provider_counts[source["provider"]] += 1
        binding["catalog"]["provider_source_counts"] = provider_counts
        cls._write_binding(config_root, binding)

        registry_path = (
            server_root
            / "scripts/enterprise_ai_monitor/expected_emitter_registry.v1.json"
        )
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["source_catalog_sha256"] = binding["catalog"]["document_sha256"]
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        binding["emitter_registry"]["document_sha256"] = _canonical_sha256(
            registry
        )
        cls._write_binding(config_root, binding)

    @classmethod
    def _reseal_catalog_documents(
        cls, config_root: Path, server_root: Path
    ) -> None:
        catalog = json.loads(
            cls._catalog_path(server_root).read_text(encoding="utf-8")
        )
        binding = cls._read_binding(config_root)
        binding["catalog"]["document_sha256"] = _canonical_sha256(catalog)
        registry_path = cls._emitter_path(server_root)
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["source_catalog_sha256"] = binding["catalog"]["document_sha256"]
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        binding["emitter_registry"]["document_sha256"] = _canonical_sha256(
            registry
        )
        cls._write_binding(config_root, binding)

    @classmethod
    def _reseal_emitter_registry(
        cls, config_root: Path, server_root: Path
    ) -> None:
        registry = json.loads(
            cls._emitter_path(server_root).read_text(encoding="utf-8")
        )
        binding = cls._read_binding(config_root)
        binding["emitter_registry"]["document_sha256"] = _canonical_sha256(
            registry
        )
        cls._write_binding(config_root, binding)

    @staticmethod
    def _verify(
        verifier: types.ModuleType, config_root: Path, server_root: Path
    ) -> dict[str, object]:
        return verifier.verify_repository_contract(
            config_root=config_root,
            mcp_servers_root=server_root,
            repository_state=verifier.RepositoryState(
                revision="b" * 40,
                clean=True,
                reviewed_revision_is_ancestor=True,
            ),
            expected_mcp_servers_revision="b" * 40,
        )

    @staticmethod
    def _git(root: Path, *args: str) -> str:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Provider Monitor Test",
                "-c",
                "user.email=provider-monitor-test@example.invalid",
                *args,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr or completed.stdout)
        return completed.stdout


if __name__ == "__main__":
    unittest.main()
