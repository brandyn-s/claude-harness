"""Contracts for the managed Claude Code OTLP authentication templates."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
INTUNE = REPO / "templates" / "cui-bedrock-govcloud" / "intune"
DETECT = INTUNE / "REM051-detect.ps1"
REMEDIATE = INTUNE / "REM051-remediate.ps1"
HELPER = INTUNE / "otel-headers-helper.ps1"
WRAPPER = INTUNE / "otel-headers-helper.cmd"
READINESS = INTUNE / "otel-auth-readiness.ps1"
WINDOWS_PATH_SAFETY_TEST = REPO / "scripts" / "test-rem051-path-safety.ps1"
WINDOWS_DPAPI_TEST = REPO / "scripts" / "test-otel-helper-dpapi.ps1"
WINDOWS_ACL_PERSISTENCE_TEST = REPO / "scripts" / "test-otel-acl-persistence.ps1"
WINDOWS_READINESS_TASK_TEST = REPO / "scripts" / "test-otel-readiness-task.ps1"
WINDOWS_STANDARD_USER_TEST = REPO / "scripts" / "test-otel-standard-user-e2e.ps1"
WINDOWS_STANDARD_USER_CHILD = REPO / "scripts" / "test-otel-standard-user-child.ps1"
WINDOWS_HELPER_COLD_START_TIMEOUT_SECONDS = 60


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _installed_sha256(path: Path) -> str:
    content = _read(path).replace("\r\n", "\n").rstrip("\n") + "\n"
    return hashlib.sha256(content.encode("utf-8")).hexdigest().upper()


def test_managed_settings_use_http_dynamic_headers_without_static_header():
    """The shipped Windows source must exercise Anthropic's HTTP helper path."""

    for path in (DETECT, REMEDIATE):
        text = _read(path)
        assert "'OTEL_EXPORTER_OTLP_PROTOCOL'         = 'http/protobuf'" in text
        assert "$OtelHeadersHelperCommand = '\"' + $WrapperPath + '\"'" in text
        assert "otelHeadersHelper" in text

    remediation = _read(REMEDIATE)
    detection = _read(DETECT)
    assert "PSObject.Properties.Remove('OTEL_EXPORTER_OTLP_HEADERS')" in remediation
    assert "forbidden legacy env.OTEL_EXPORTER_OTLP_HEADERS" in detection

    assert HELPER.is_file(), "the managed helper referenced by REM051 must be shipped"
    assert WRAPPER.is_file(), "Windows shell invocation requires the shipped .cmd wrapper"


def test_machine_dpapi_backend_never_persists_or_prints_plaintext_except_as_json():
    """Compatibility auth reads an MDM-delivered LocalMachine DPAPI blob."""

    helper = _read(HELPER)
    dpapi = helper[
        helper.index("function Get-MachineDpapiToken") : helper.index(
            "function Get-BrokerMtlsToken"
        )
    ]
    credential_acl = helper[
        helper.index("function Assert-ExactCredentialAcl") : helper.index(
            "function Get-MachineDpapiToken"
        )
    ]
    assert "[System.Security.AccessControl.FileSecurity]::new(" in credential_acl
    assert "AccessControlSections]::Access" in credential_acl
    assert "AccessControlSections]::Owner" in credential_acl
    assert "Get-Acl" not in credential_acl
    # The managed wrapper deliberately invokes inbox Windows PowerShell 5.1,
    # where ProtectedData is in System.Security but is not preloaded. Loading
    # the framework assembly must precede the first type reference so the real
    # standard-user path cannot fail before its value-free error boundary.
    load_at = dpapi.index("Add-Type -AssemblyName System.Security -ErrorAction Stop")
    unprotect_at = dpapi.index("ProtectedData]::Unprotect")
    assert load_at < unprotect_at
    for value_free_acl_stage in (
        "credential-file-metadata-failed",
        "credential-acl-read-failed",
        "credential-acl-rules-read-failed",
        "credential-acl-rule-inspection-failed",
    ):
        assert f"Fail '{value_free_acl_stage}'" in credential_acl
        assert f"'{value_free_acl_stage}'" in dpapi
    for value_free_stage in (
        "credential-acl-check-failed",
        "credential-read-failed",
        "credential-envelope-invalid",
        "credential-provider-unavailable",
        "credential-decrypt-failed",
        "credential-decode-failed",
        "credential-clear-failed",
    ):
        assert f"Fail '{value_free_stage}'" in dpapi
    assert "DataProtectionScope]::LocalMachine" in helper
    assert "ProtectedData]::Unprotect" in helper
    assert "ConvertTo-Json -Compress" in helper
    assert "Write-Output $token" not in helper
    assert "Set-Content" not in helper
    assert "WriteAllText" not in helper
    assert re.search(r"Authorization\s*=\s*\('Bearer \{0\}' -f \$token\)", helper)


def test_broker_backend_is_mtls_authenticated_and_has_no_legacy_fallback():
    """Broker mode must fail closed instead of silently reusing the old token."""

    helper = _read(HELPER)
    broker_function = re.search(
        r"function Get-BrokerMtlsToken \{(?P<body>.*?)\n\}",
        helper,
        flags=re.DOTALL,
    )
    assert broker_function
    broker = broker_function.group("body")
    assert "BrokerUri" in broker
    assert "ClientCertificateThumbprint" in broker
    assert "Cert:\\LocalMachine\\My" in broker
    assert "HasPrivateKey" in broker
    assert "1.3.6.1.5.5.7.3.2" in broker  # TLS client-auth EKU
    assert "Invoke-RestMethod" in broker
    assert "-Certificate $certificate" in broker
    assert "-MaximumRedirection 0" in broker
    assert "access_token" in broker
    assert "expires_in" in broker
    assert "Get-MachineDpapiToken" not in broker

    broker_case = re.search(
        r"'broker-mtls'\s*\{(?P<body>.*?)\n\s*\}", helper, flags=re.DOTALL
    )
    assert broker_case
    assert "Get-BrokerMtlsToken" in broker_case.group("body")
    assert "Get-MachineDpapiToken" not in broker_case.group("body")


def test_broker_token_ttl_exceeds_the_managed_refresh_interval_with_skew():
    helper = _read(HELPER)
    remediation = _read(REMEDIATE)
    refresh = re.search(
        r"'CLAUDE_CODE_OTEL_HEADERS_HELPER_DEBOUNCE_MS'\s*=\s*'(\d+)'",
        remediation,
    )
    minimum_ttl = re.search(
        r"\$MinimumBrokerTokenTtlSeconds\s*=\s*(\d+)", helper
    )
    assert refresh and minimum_ttl
    refresh_seconds = int(refresh.group(1)) // 1000
    assert int(minimum_ttl.group(1)) >= refresh_seconds + 300
    assert "$expiresIn -lt $MinimumBrokerTokenTtlSeconds" in helper


def test_all_managed_templates_are_free_of_embedded_bearer_and_token_literals():
    """Scan the whole managed-template tree, not a hand-picked file list."""

    managed_tree = REPO / "templates" / "cui-bedrock-govcloud"
    bearer_value = re.compile(
        r"Authorization\s*=\s*Bearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE
    )
    quoted_token = re.compile(r"(['\"])([A-Za-z0-9_-]{32,})\1")
    token_generator = re.compile(
        r"(?:get|generate|mint)[-_ ]?(?:token|api[-_ ]?key)", re.IGNORECASE
    )
    findings: list[str] = []

    for path in sorted(p for p in managed_tree.rglob("*") if p.is_file()):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if bearer_value.search(line):
                findings.append(f"{path.relative_to(REPO)}:{number}: bearer value")
            if token_generator.search(line):
                findings.append(f"{path.relative_to(REPO)}:{number}: token generator")
            for match in quoted_token.finditer(line):
                candidate = match.group(2)
                is_env_name = candidate.upper() == candidate and "_" in candidate
                looks_random = (
                    bool(re.search(r"[A-Z]", candidate))
                    and bool(re.search(r"[a-z]", candidate))
                    and bool(re.search(r"[0-9]", candidate))
                )
                if (
                    looks_random
                    and "sha256" not in line.lower()
                    and not is_env_name
                ):
                    findings.append(
                        f"{path.relative_to(REPO)}:{number}: token-shaped literal"
                    )

    assert not findings, "\n".join(findings)


def test_remediation_migrates_existing_header_before_removing_it():
    """Existing fleet tokens move in memory to LocalMachine DPAPI, value-free."""

    remediation = _read(REMEDIATE)
    read_at = remediation.index("PSObject.Properties['OTEL_EXPORTER_OTLP_HEADERS']")
    protect_at = remediation.index("ProtectedData]::Protect")
    write_at = remediation.index("Write-VerifiedAtomicFile -TargetPath $CredentialPath")
    remove_at = remediation.index(
        "PSObject.Properties.Remove('OTEL_EXPORTER_OTLP_HEADERS')"
    )
    assert read_at < protect_at < write_at < remove_at
    assert "DataProtectionScope]::LocalMachine" in remediation
    assert "LEGACY_HEADER_INVALID" in remediation
    assert "BLOCKED:OTEL_AUTH_BOOTSTRAP_REQUIRED" in remediation
    assert "Write-Output $legacy" not in remediation
    assert "Write-Error $legacy" not in remediation


def test_system_remediation_writes_only_verified_single_link_targets_atomically():
    """SYSTEM must never follow pre-positioned links while installing auth files."""

    remediation = _read(REMEDIATE)
    detection = _read(DETECT)
    helper = _read(HELPER)

    assert "$CredentialPath = Join-Path $Dir 'otel-legacy-token.dpapi'" in remediation
    assert "$env:ProgramData" not in remediation
    assert "$env:ProgramData" not in detection
    assert "$env:ProgramData" not in helper

    required_safe_write_primitives = (
        "FILE_FLAG_OPEN_REPARSE_POINT",
        "GetFileInformationByHandle",
        "NumberOfLinks",
        "FileMode]::CreateNew",
        "MoveFileEx",
        "Test-VerifiedAdminDirectory",
        "Write-VerifiedAtomicFile",
    )
    assert all(term in remediation for term in required_safe_write_primitives)

    forbidden_direct_mutations = (
        "WriteAllText($HelperPath",
        "WriteAllText($WrapperPath",
        "WriteAllText($CredentialPath",
        "WriteAllText($Path",
        "Set-Acl -LiteralPath $HelperPath",
        "Set-Acl -LiteralPath $WrapperPath",
        "Set-Acl -LiteralPath $CredentialPath",
        "Set-Acl -LiteralPath $Path",
    )
    assert not any(term in remediation for term in forbidden_direct_mutations)


def test_auth_paths_use_os_known_folder_not_user_controlled_programfiles_env():
    known_folder = (
        "[Environment]::GetFolderPath("
        "[Environment+SpecialFolder]::ProgramFiles)"
    )
    for path in (HELPER, DETECT, REMEDIATE):
        text = _read(path)
        assert known_folder in text
        assert "$env:ProgramFiles" not in text
        assert "program-files-unavailable" in text

    dpapi_harness = _read(WINDOWS_DPAPI_TEST)
    assert "$env:ProgramFiles = $programFiles" not in dpapi_harness
    assert "forged-programfiles-env-redirected-credential" in dpapi_harness


def test_new_enrollment_fails_before_settings_change_without_auth_bootstrap():
    remediation = _read(REMEDIATE)

    blocker = remediation.index("BLOCKED:OTEL_AUTH_BOOTSTRAP_REQUIRED")
    settings_change = remediation.index(
        "$j | Add-Member -NotePropertyName otelHeadersHelper"
    )
    assert blocker < settings_change
    assert "exit 2" in remediation[blocker : blocker + 200]


def test_detection_requires_the_selected_backend_prerequisites():
    detection = _read(DETECT)

    assert "Get-OtelAuthBackend" in detection
    assert "otel-legacy-token.dpapi" in detection
    assert "auth.machine-dpapi credential" in detection
    assert "auth.broker-mtls configuration" in detection


def test_dpapi_cutover_uses_the_exact_value_free_helper_readiness_oracle():
    helper = _read(HELPER)
    wrapper = _read(WRAPPER)
    remediation = _read(REMEDIATE)
    detection = _read(DETECT)

    assert "param(" in helper and "[switch]$ReadinessProbe" in helper
    assert "OTEL_HEADERS_HELPER_READY:{0}" in helper
    assert "%*" in wrapper
    assert "Test-AuthHelperReadiness" in remediation
    assert "Test-AuthHelperReadiness" in detection
    assert "& $ReadinessPath -ExpectedBackend $ExpectedBackend" in remediation
    assert "& $ReadinessPath -ExpectedBackend $ExpectedBackend" in detection
    assert "& $WrapperPath -ReadinessProbe" not in remediation
    assert "& $WrapperPath -ReadinessProbe" not in detection

    readiness_at = remediation.index("Test-AuthHelperReadiness -ExpectedBackend $backend")
    remove_at = remediation.index(
        "PSObject.Properties.Remove('OTEL_EXPORTER_OTLP_HEADERS')"
    )
    assert readiness_at < remove_at

    exact_acl_contract = (
        "AreAccessRulesProtected",
        "S-1-5-18",
        "S-1-5-32-544",
        "S-1-5-32-545",
        "ReadAndExecute",
        "credential-acl-not-exact",
    )
    assert all(term in helper for term in exact_acl_contract)


def test_required_windows_ci_exercises_real_dpapi_readiness_failures():
    workflow = _read(REPO / ".github" / "workflows" / "validate.yml")

    assert WINDOWS_DPAPI_TEST.is_file()
    harness = _read(WINDOWS_DPAPI_TEST)
    for case in (
        "empty",
        "non-base64",
        "unprotectable",
        "plaintext-whitespace",
        "weak-acl",
        "missing-users-read",
        "valid",
    ):
        assert case in harness
    assert "OTEL_HEADERS_HELPER_READY:machine-dpapi" in harness
    assert "dpapi-value-leaked" in harness
    assert "pwsh -File scripts/test-otel-helper-dpapi.ps1" in workflow


def test_cutover_probe_runs_exact_wrapper_as_interactive_standard_user():
    remediation = _read(REMEDIATE)
    detection = _read(DETECT)
    helper = _read(HELPER)
    readiness = _read(READINESS)

    for script in (remediation, detection):
        assert "Test-AuthHelperReadiness" in script
        assert "& $ReadinessPath -ExpectedBackend $ExpectedBackend" in script

    for term in (
        "New-ScheduledTaskAction",
        "$WrapperPath",
        "-ReadinessProbe",
        "-ReadinessReceiptPath",
        "New-ScheduledTaskPrincipal",
        "-LogonType Interactive",
        "-RunLevel Limited",
        "OTEL_HEADERS_HELPER_READY:{0}:{1}:{2}:{3}",
        "RandomNumberGenerator]::Create",
        "LastTaskResult -ne 0",
        "$ReadinessTimeoutSeconds = 30",
        "Remove-Item -LiteralPath $receiptPath",
        "Test-ExactReadinessReceiptAcl",
        "FileSystemRights]::WriteData",
        "Unregister-ScheduledTask",
        "auth-readiness-no-console-user",
        "$env:ComSpec",
    ):
        assert term in readiness

    assert "[string]$ReadinessReceiptPath" in helper
    assert "[string]$ReadinessNonce" in helper
    assert "[string]$ExpectedReadinessSid" in helper
    assert "WindowsIdentity]::GetCurrent().User.Value" in helper
    assert "FILE_WRITE_DATA" in helper
    assert "FILE_FLAG_OPEN_REPARSE_POINT" in helper
    assert "NumberOfLinks" in helper
    assert "OTEL_HEADERS_HELPER_READY:{0}:{1}:{2}" in helper


def test_broker_readiness_probes_collector_after_schema_and_ttl_validation():
    helper = _read(HELPER)

    assert "$CollectorProbeUri = 'https://service.mcp.example.internal/v1/logs'" in helper
    assert "function Assert-CollectorAcceptsToken" in helper
    collector = re.search(
        r"function Assert-CollectorAcceptsToken.*?\{(?P<body>.*?)\n\}",
        helper,
        flags=re.DOTALL,
    )
    assert collector
    body = collector.group("body")
    assert "application/x-protobuf" in body
    assert "Authorization = ('Bearer {0}' -f $AccessToken)" in body
    assert "Invoke-WebRequest" in body
    assert "-MaximumRedirection 0" in body
    assert "-TimeoutSec 10" in body
    assert "collector-token-rejected" in body

    ttl_at = helper.index("$expiresIn -lt $MinimumBrokerTokenTtlSeconds")
    token_validation_at = helper.index("Fail 'credential-value-invalid'")
    collector_at = helper.index("Assert-CollectorAcceptsToken -AccessToken $token")
    ready_at = helper.rindex("Write-ReadinessReceipt -Backend $backend")
    assert ttl_at < token_validation_at < collector_at < ready_at


def test_collector_acceptance_gates_readiness_for_both_auth_backends():
    helper = _read(HELPER)

    body = helper[helper.index("if ($ReadinessProbe) {") :]
    assert "Assert-CollectorAcceptsToken -AccessToken $token" in body
    assert "if ($backend -eq 'broker-mtls')" not in body
    assert body.index("Assert-CollectorAcceptsToken") < body.index(
        "Write-ReadinessReceipt"
    )

    dpapi_harness = _read(WINDOWS_DPAPI_TEST)
    assert "collector-token-rejected" in dpapi_harness
    assert "OTEL_HELPER_SKIP_COLLECTOR_PROBE_FOR_TEST" not in helper


def test_remediation_installs_the_exact_reviewed_helper_source():
    """The self-contained Intune payload cannot drift from the reviewed helper."""

    remediation = _read(REMEDIATE)
    match = re.search(
        r"\$helperSource = @'\n(?P<body>.*?)\n'@",
        remediation,
        flags=re.DOTALL,
    )
    assert match, "REM051 must carry the helper because Intune uploads one script"
    embedded = match.group("body").replace("\r\n", "\n").rstrip("\n") + "\n"
    canonical = _read(HELPER).replace("\r\n", "\n").rstrip("\n") + "\n"
    assert embedded == canonical
    assert "Write-VerifiedAtomicFile -TargetPath $HelperPath" in remediation

    wrapper_match = re.search(
        r"\$wrapperSource = @'\n(?P<body>.*?)\n'@",
        remediation,
        flags=re.DOTALL,
    )
    assert wrapper_match
    wrapper_embedded = (
        wrapper_match.group("body").replace("\r\n", "\n").rstrip("\n") + "\n"
    )
    wrapper_canonical = _read(WRAPPER).replace("\r\n", "\n").rstrip("\n") + "\n"
    assert wrapper_embedded == wrapper_canonical
    assert "Write-VerifiedAtomicFile -TargetPath $WrapperPath" in remediation

    readiness_match = re.search(
        r"\$readinessSource = @'\n(?P<body>.*?)\n'@",
        remediation,
        flags=re.DOTALL,
    )
    assert readiness_match
    readiness_embedded = (
        readiness_match.group("body").replace("\r\n", "\n").rstrip("\n") + "\n"
    )
    readiness_canonical = _read(READINESS).replace("\r\n", "\n").rstrip("\n") + "\n"
    assert readiness_embedded == readiness_canonical
    assert "Write-VerifiedAtomicFile -TargetPath $ReadinessPath" in remediation


def test_detection_hashes_all_executable_auth_artifacts():
    detection = _read(DETECT)

    assert f"$ExpectedHelperSha256 = '{_installed_sha256(HELPER)}'" in detection
    assert f"$ExpectedWrapperSha256 = '{_installed_sha256(WRAPPER)}'" in detection
    assert f"$ExpectedReadinessSha256 = '{_installed_sha256(READINESS)}'" in detection
    assert (
        "Get-TrustedPathSnapshot -TargetPath $HelperPath `\n"
        "            -ExpectedSha256 $ExpectedHelperSha256"
    ) in detection
    assert (
        "Get-TrustedPathSnapshot -TargetPath $WrapperPath `\n"
        "            -ExpectedSha256 $ExpectedWrapperSha256"
    ) in detection
    assert (
        "Get-TrustedPathSnapshot -TargetPath $ReadinessPath `\n"
        "            -ExpectedSha256 $ExpectedReadinessSha256"
    ) in detection
    assert "otel-headers-helper.ps1 trust/hash" in detection
    assert "otel-headers-helper.cmd trust/hash" in detection
    assert "otel-auth-readiness.ps1 trust/hash" in detection


def test_detection_trusts_stable_no_follow_artifacts_before_readiness_execution():
    """SYSTEM must execute only the exact file identity it already trusted."""

    detection = _read(DETECT)
    for term in (
        "FILE_FLAG_OPEN_REPARSE_POINT",
        "GetFileInformationByHandle",
        "NumberOfLinks",
        "VolumeSerialNumber",
        "FileIndexHigh",
        "FileIndexLow",
        "Get-TrustedPathSnapshot",
        "Test-TrustedSnapshotStillCurrent",
        "Test-TrustedOwner",
        "Test-AdminWritableOnly",
    ):
        assert term in detection

    # Path-based hashing leaves a swap window; detection must hash the same
    # no-follow handle whose identity/link count it records.
    assert "Get-FileHash -LiteralPath" not in detection
    assert "ComputeHash($stream)" in detection

    readiness = re.search(
        r"function Test-AuthHelperReadiness.*?\{(?P<body>.*?)\n\}",
        detection,
        flags=re.DOTALL,
    )
    assert readiness
    body = readiness.group("body")
    revalidate_at = body.index("Test-TrustedSnapshotStillCurrent")
    execute_at = body.index("& $ReadinessPath")
    assert revalidate_at < execute_at

    # Settings, all executable artifacts, and the selected credential are
    # trust-gated before the main block can invoke readiness.
    main = detection[detection.index("try {") :]
    for path_variable in (
        "$Path",
        "$HelperPath",
        "$WrapperPath",
        "$ReadinessPath",
        "$CredentialPath",
    ):
        assert f"Get-TrustedPathSnapshot -TargetPath {path_variable}" in main
    assert main.index("Get-TrustedPathSnapshot -TargetPath $ReadinessPath") < main.index(
        "Test-AuthHelperReadiness -ExpectedBackend $backend"
    )


def test_windows_shell_executes_the_exact_quoted_wrapper_contract(tmp_path: Path):
    """Execute the exact managed JSON value through the Windows shell."""

    if sys.platform != "win32":
        return

    install = tmp_path / "Program Files" / "ClaudeCode"
    install.mkdir(parents=True)
    helper = install / HELPER.name
    wrapper = install / WRAPPER.name
    helper.write_text(_read(HELPER), encoding="utf-8")
    wrapper.write_text(_read(WRAPPER), encoding="ascii")

    managed_settings = tmp_path / "managed-settings.json"
    managed_settings.write_text(
        json.dumps({"otelHeadersHelper": f'"{wrapper}"'}),
        encoding="utf-8",
    )
    settings_value = json.loads(managed_settings.read_text(encoding="utf-8"))[
        "otelHeadersHelper"
    ]
    assert settings_value == f'"{wrapper}"'

    # otelHeadersHelper is a shell command string. Passing settings_value as
    # one element of an argv list makes Python escape its embedded quotes into
    # literal \" bytes, which is not Claude Code's Windows shell contract.
    result = subprocess.run(
        settings_value,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
        # A cold Windows runner compiles the helper's Add-Type C# block before
        # it can reach the expected missing-credential failure. Keep this
        # bounded, but leave enough headroom for the inbox compiler startup.
        timeout=WINDOWS_HELPER_COLD_START_TIMEOUT_SECONDS,
    )

    # No credential is provisioned in the test. Reaching the helper's fixed,
    # value-free failure proves cmd.exe resolved the exact settings command.
    assert result.returncode == 1
    assert "OTEL_HEADERS_HELPER_FAILED:" in result.stderr
    assert "not recognized" not in result.stderr.lower()


def test_windows_shell_timeout_covers_cold_powershell_compile():
    """Cold Windows runners must have time to compile the helper's Add-Type."""

    assert WINDOWS_HELPER_COLD_START_TIMEOUT_SECONDS >= 60


def test_required_ci_runs_the_literal_wrapper_test_on_windows():
    workflow = _read(REPO / ".github" / "workflows" / "validate.yml")

    assert "managed-otel-auth-windows:" in workflow
    assert "runs-on: windows-2022" in workflow
    assert "pytest scripts/test_managed_otel_auth.py -q" in workflow
    assert (
        "needs: [architecture-validate, managed-otel-auth-windows, "
        "provider-monitor-catalog]"
    ) in workflow


def test_windows_acl_paths_use_powershell_7_supported_extension_apis():
    """Managed Windows source and harnesses must not call removed ACL APIs."""

    paths = (
        REMEDIATE,
        WINDOWS_ACL_PERSISTENCE_TEST,
        WINDOWS_STANDARD_USER_TEST,
    )
    unsupported = re.compile(
        r"\[System\.IO\.(?:File|Directory)\]::(?:Get|Set)AccessControl\("
        r"|\$(?:stream|createdDirectory)\.SetAccessControl\("
    )
    violations = {
        str(path.relative_to(REPO)): unsupported.findall(_read(path))
        for path in paths
        if unsupported.search(_read(path))
    }
    assert violations == {}


def test_required_windows_ci_exercises_prepositioned_link_attacks():
    workflow = _read(REPO / ".github" / "workflows" / "validate.yml")

    assert WINDOWS_PATH_SAFETY_TEST.is_file()
    harness = _read(WINDOWS_PATH_SAFETY_TEST)
    assert "DirectoryJunction" in harness
    assert "SymbolicLink" in harness
    assert "HardLink" in harness
    assert "Get-Acl" in harness
    assert "target-content-changed" in harness
    assert "target-acl-changed" in harness
    assert "pwsh -File scripts/test-rem051-path-safety.ps1" in workflow


def test_path_safety_harness_executes_production_oracle_only_in_disposable_tree():
    harness = _read(WINDOWS_PATH_SAFETY_TEST)

    assert "FunctionDefinitionAst" in harness
    assert "Get-VerifiedFileInformation" in harness
    assert "Test-VerifiedAdminDirectory" in harness
    assert "Test-VerifiedRegularSingleLinkFile" in harness
    assert "Write-VerifiedAtomicFile" in harness
    assert "production-oracle-mutation-sensitivity" in harness
    assert "mutation-probe-not-live" in harness
    assert "$env:ProgramFiles =" not in harness
    assert "-File $RemediationPath" not in harness
    assert "actual-program-files-write" not in harness


def test_program_files_oracle_accepts_normal_trustedinstaller_acl_in_ci():
    remediation = _read(REMEDIATE)
    workflow = _read(REPO / ".github" / "workflows" / "validate.yml")

    trusted_installer_sid = (
        "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
    )
    assert trusted_installer_sid in remediation
    assert "[StringComparison]::OrdinalIgnoreCase" in remediation
    assert "ValidateProgramFilesOnly" in remediation
    assert "PROGRAM_FILES_PATH_ORACLE_VALID" in remediation
    assert (
        "powershell -File templates/cui-bedrock-govcloud/intune/"
        "REM051-remediate.ps1 -ValidateProgramFilesOnly"
    ) in workflow


def test_path_oracle_ignores_only_inherit_only_creator_owner_ace():
    remediation = _read(REMEDIATE)
    harness = _read(WINDOWS_PATH_SAFETY_TEST)

    assert "[System.Security.AccessControl.PropagationFlags]::InheritOnly" in remediation
    assert "S-1-3-0" in harness  # CREATOR OWNER fixture
    assert "InheritOnly" in harness
    assert "normal-program-files-acl-rejected" in harness
    assert "'S-1-3-0'" not in re.search(
        r"\$privilegedWriters\s*=\s*@\((?P<body>.*?)\n\s*\)",
        remediation,
        flags=re.DOTALL,
    ).group("body")


def test_windows_acl_oracles_normalize_synchronize_and_require_trusted_owners():
    detection = _read(DETECT)
    remediation = _read(REMEDIATE)
    helper = _read(HELPER)
    readiness = _read(READINESS)
    workflow = _read(REPO / ".github" / "workflows" / "validate.yml")

    for script in (helper, readiness):
        assert "Get-NormalizedAllowRights" in script
        assert "FileSystemRights]::Synchronize" in script
        assert "Test-TrustedOwner" in script
        assert ".GetOwner(" in script

    assert "Test-TrustedOwner" in detection
    assert "Test-VerifiedAdminDirectory" in detection
    assert "Get-TrustedPathSnapshot" in detection
    assert "Test-TrustedOwner" in remediation
    assert "Test-VerifiedAdminDirectory" in remediation
    assert "Test-VerifiedRegularSingleLinkFile" in remediation

    assert WINDOWS_ACL_PERSISTENCE_TEST.is_file()
    harness = _read(WINDOWS_ACL_PERSISTENCE_TEST)
    for term in (
        "Assert-ExactCredentialAcl",
        "Test-ExactReadinessReceiptAcl",
        "SetAccessControl",
        "GetAccessControl",
        "Synchronize",
        "credential-persist-reload",
        "receipt-persist-reload",
    ):
        assert term in harness
    assert "pwsh -File scripts/test-otel-acl-persistence.ps1" in workflow


def test_readiness_task_requires_a_distinct_post_start_invocation_and_cleans_up():
    helper = _read(HELPER)
    readiness = _read(READINESS)
    workflow = _read(REPO / ".github" / "workflows" / "validate.yml")

    assert "ReadinessInvocationId" in helper
    assert "ReadinessInvocationId" in readiness
    assert "OTEL_HEADERS_HELPER_READY:{0}:{1}:{2}:{3}" in helper
    assert "OTEL_HEADERS_HELPER_READY:{0}:{1}:{2}:{3}" in readiness
    preflight_at = readiness.index("$preStartTaskInfo = Get-ScheduledTaskInfo")
    start_at = readiness.index("Start-ScheduledTask")
    assert preflight_at < start_at
    assert "$taskInfo.LastRunTime -le $preStartTaskInfo.LastRunTime" in readiness
    assert "$startedAt.ToLocalTime()" not in readiness
    assert "Unregister-ScheduledTask" in readiness
    assert "Remove-Item -LiteralPath $receiptPath" in readiness

    assert WINDOWS_READINESS_TASK_TEST.is_file()
    harness = _read(WINDOWS_READINESS_TASK_TEST)
    for term in (
        "immediate-success-repeat",
        "task-failure-cleanup",
        "task-hang-cleanup",
        "Example-OTelAuthReadiness-",
        "Get-ScheduledTask",
        "Get-ChildItem",
    ):
        assert term in harness
    assert "pwsh -File scripts/test-otel-readiness-task.ps1" in workflow


def test_required_windows_ci_runs_both_backends_as_a_real_standard_user():
    workflow = _read(REPO / ".github" / "workflows" / "validate.yml")

    assert WINDOWS_STANDARD_USER_TEST.is_file()
    assert WINDOWS_STANDARD_USER_CHILD.is_file()
    harness = _read(WINDOWS_STANDARD_USER_TEST)
    child = _read(WINDOWS_STANDARD_USER_CHILD)
    for term in (
        "New-LocalUser",
        "Add-LocalGroupMember",
        "Start-Process",
        "-Credential",
        "Grant-StandardUserFixtureAccess",
        "Copy-Item -LiteralPath $HelperPath",
        "Copy-Item -LiteralPath $ChildPath",
        "machine-dpapi",
        "broker-mtls",
        "Remove-LocalUser",
        "STANDARD_USER_E2E_READY",
    ):
        assert term in harness
    for term in (
        "WindowsIdentity]::GetCurrent().User.Value",
        "Get-MachineDpapiToken",
        "Get-BrokerMtlsToken",
        "Assert-CollectorAcceptsToken",
        "$stage = 'machine-dpapi-token'",
        "$stage = 'collector-probe'",
        "unexpected-{0}-error",
        "STANDARD_USER_E2E_FAILED:[a-z0-9-]+",
        "STANDARD_USER_E2E_READY",
    ):
        assert term in child
    # The production request passes -UseBasicParsing as a switch. The local
    # transport intercept must accept and validate those literal invocation
    # semantics without ever printing the Authorization value.
    for transport_contract in (
        "[switch]$UseBasicParsing",
        "$Method -cne 'Post'",
        "$Uri -cne $script:CollectorProbeUri",
        "$ContentType -cne 'application/x-protobuf'",
        "$MaximumRedirection -ne 0",
        "$TimeoutSec -ne 10",
        "-not $UseBasicParsing.IsPresent",
        "$Body.Count -ne 0",
        "collector-intercept-contract-invalid",
    ):
        assert transport_contract in child
    for broker_transport_contract in (
        "function global:Invoke-RestMethod",
        "$Uri -cne 'https://broker.invalid/token'",
        "$Headers.Accept -cne 'application/json'",
        "$Body -cne '{}'",
        "broker-intercept-contract-invalid",
    ):
        assert broker_transport_contract in child
    assert "STANDARD_USER_E2E_FAILED:[a-z0-9-]+" in harness
    assert "$process.ExitCode -ne 0 -or -not (Test-Path" not in harness
    assert "Write-Output $token" not in child
    assert "Write-Host $token" not in child
    assert "pwsh -File scripts/test-otel-standard-user-e2e.ps1" in workflow


def test_runbooks_document_cutover_dependencies_and_evidence_boundaries():
    intune = _read(INTUNE / "README.md")
    security = _read(REPO / "SECURITY.md")
    workflows = _read(REPO / ".github" / "WORKFLOWS.md")
    platform = _read(REPO / "docs" / "PLATFORM_NOTES.md")
    for script in (DETECT, REMEDIATE):
        assert "REM051-ClaudeManagedSettings v15" in _read(script)

    required_intune_terms = (
        "otelHeadersHelper",
        "http/protobuf",
        "gRPC",
        "machine-dpapi",
        "broker-mtls",
        "BLOCKED:OTEL_AUTH_BOOTSTRAP_REQUIRED",
        "not per-user secrecy",
        "1200 seconds",
        "private-key ACL",
        "collector",
        "256-bit nonce",
        "LastTaskResult=0",
        "Graph",
        "source-only",
    )
    assert all(term in intune for term in required_intune_terms)
    assert "removed from current source" in security
    assert "Git history" in security
    assert "Managed OTel auth (Windows)" in workflows
    assert "not a live-deployment attestation" in platform


def test_cc_monitor_requires_backend_receipt_across_the_auth_transition():
    canonical = _read(REPO / "skills" / "cc-monitor" / "references" / "cowork-otel-forensics.md")
    published = _read(
        REPO
        / "marketplace"
        / "knowledge-ops"
        / "skills"
        / "cc-monitor"
        / "references"
        / "cowork-otel-forensics.md"
    )
    contract = "OTLP authentication transition"
    assert contract in canonical
    assert contract in published
