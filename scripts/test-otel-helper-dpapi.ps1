<#
.SYNOPSIS
  Windows acceptance tests for value-free LocalMachine-DPAPI readiness.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$CanonicalHelper = Join-Path $RepositoryRoot `
    'templates\cui-bedrock-govcloud\intune\otel-headers-helper.ps1'
$CanonicalWrapper = Join-Path $RepositoryRoot `
    'templates\cui-bedrock-govcloud\intune\otel-headers-helper.cmd'

function New-ExactCredentialAcl([switch]$WeakAcl, [switch]$MissingUsersRead) {
    $acl = New-Object System.Security.AccessControl.FileSecurity
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner(
        [System.Security.Principal.SecurityIdentifier]'S-1-5-32-544'
    )
    foreach ($sid in 'S-1-5-18','S-1-5-32-544') {
        $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
            [System.Security.Principal.SecurityIdentifier]$sid,
            'FullControl',
            'Allow'
        ))
    }
    if (-not $MissingUsersRead) {
        $rights = if ($WeakAcl) { 'Modify' } else { 'ReadAndExecute' }
        $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
            [System.Security.Principal.SecurityIdentifier]'S-1-5-32-545',
            $rights,
            'Allow'
        ))
    }
    return $acl
}

function Protect-TestValue([string]$Value) {
    $plain = [System.Text.Encoding]::UTF8.GetBytes($Value)
    $protected = $null
    try {
        $protected = [System.Security.Cryptography.ProtectedData]::Protect(
            $plain,
            $null,
            [System.Security.Cryptography.DataProtectionScope]::LocalMachine
        )
        return [Convert]::ToBase64String($protected)
    }
    finally {
        if ($plain) { [Array]::Clear($plain, 0, $plain.Length) }
        if ($protected) { [Array]::Clear($protected, 0, $protected.Length) }
    }
}

function Invoke-DpapiCase([string]$CaseName) {
    $fixtureRoot = Join-Path ([System.IO.Path]::GetTempPath()) `
        ('otel-helper-dpapi-{0}' -f [Guid]::NewGuid().ToString('N'))
    $programFiles = Join-Path $fixtureRoot 'Program Files'
    $install = Join-Path $programFiles 'ClaudeCode'
    $helper = Join-Path $install 'otel-headers-helper.ps1'
    $wrapper = Join-Path $install 'otel-headers-helper.cmd'
    $credential = Join-Path $install 'otel-legacy-token.dpapi'
    $originalProgramFiles = [Environment]::GetEnvironmentVariable('ProgramFiles', 'Process')
    $testToken = ('D' * 20) + ([Guid]::NewGuid().ToString('N'))

    try {
        New-Item -ItemType Directory -Path $install -Force | Out-Null
        Copy-Item -LiteralPath $CanonicalHelper -Destination $helper
        Copy-Item -LiteralPath $CanonicalWrapper -Destination $wrapper

        $content = switch ($CaseName) {
            'empty' { '' }
            'non-base64' { 'not base64!' }
            'unprotectable' { [Convert]::ToBase64String([byte[]](1,2,3,4,5,6,7,8)) }
            'plaintext-whitespace' { Protect-TestValue ($testToken + "`n") }
            default { Protect-TestValue $testToken }
        }
        [System.IO.File]::WriteAllText($credential, $content)
        $weakAcl = $CaseName -eq 'weak-acl'
        $missingRead = $CaseName -eq 'missing-users-read'
        [System.IO.FileSystemAclExtensions]::SetAccessControl(
            [System.IO.FileInfo]::new($credential),
            (New-ExactCredentialAcl -WeakAcl:$weakAcl -MissingUsersRead:$missingRead)
        )

        # DPAPI acceptance tests exercise the helper's decryption/value/ACL
        # functions directly after parsing the canonical script. Collector
        # acceptance has a separate bounded request contract test and there is
        # no test-only bypass in shipped production code.
        $helperText = [System.IO.File]::ReadAllText($helper)
        $functionPrefix = $helperText.Substring(0, $helperText.IndexOf("`ntry {"))
        [Environment]::SetEnvironmentVariable('ProgramFiles', $programFiles, 'Process')
        $helperDefinitions = [scriptblock]::Create($functionPrefix)
        . $helperDefinitions
        if ($CredentialPath.StartsWith($programFiles, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'forged-programfiles-env-redirected-credential'
        }
        $CredentialPath = $credential
        $output = @()
        try {
            $token = Get-MachineDpapiToken
            if ([string]::IsNullOrWhiteSpace($token) -or $token.Length -gt 4096 -or
                $token -match '[\x00-\x20\x7f]') {
                throw [InvalidOperationException]::new('credential-value-invalid')
            }
            $output = @('OTEL_HEADERS_HELPER_READY:machine-dpapi')
            $exitCode = 0
        }
        catch {
            $output = @('OTEL_HEADERS_HELPER_FAILED:{0}' -f $_.Exception.Message)
            $exitCode = 1
        }
        $rendered = $output -join "`n"
        if ($rendered.Contains($testToken)) { throw 'dpapi-value-leaked' }

        if ($CaseName -eq 'valid') {
            if ($exitCode -ne 0 -or $output.Count -ne 1 -or
                [string]$output[0] -cne 'OTEL_HEADERS_HELPER_READY:machine-dpapi') {
                throw 'valid-dpapi-readiness-rejected'
            }
        }
        elseif ($exitCode -eq 0 -or
            $rendered -notmatch 'OTEL_HEADERS_HELPER_FAILED:[a-z0-9-]+') {
            throw ('invalid-dpapi-readiness-accepted:{0}' -f $CaseName)
        }
    }
    finally {
        [Environment]::SetEnvironmentVariable('ProgramFiles', $originalProgramFiles, 'Process')
        $testToken = $null
        if (Test-Path -LiteralPath $fixtureRoot) {
            Remove-Item -LiteralPath $fixtureRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

foreach ($caseName in @(
    'empty',
    'non-base64',
    'unprotectable',
    'plaintext-whitespace',
    'weak-acl',
    'missing-users-read',
    'valid'
)) {
    Invoke-DpapiCase $caseName
}

# A valid DPAPI value is still not ready when the collector rejects it; the
# production helper has no bypass and reports collector-token-rejected.

Write-Output 'OTEL_HELPER_DPAPI_TESTS_PASSED'
