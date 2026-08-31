<#
.SYNOPSIS
  Windows acceptance tests for persisted OTel credential and readiness ACLs.

.DESCRIPTION
  Loads the exact production ACL functions from the canonical helper scripts,
  persists descriptors to disposable files, reloads them from NTFS, and proves
  Windows' automatic Allow/Synchronize normalization does not create a false
  rejection. No managed path, registry key, credential, or Intune state is
  read or changed.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$HelperPath = Join-Path $RepositoryRoot `
    'templates\cui-bedrock-govcloud\intune\otel-headers-helper.ps1'
$ReadinessPath = Join-Path $RepositoryRoot `
    'templates\cui-bedrock-govcloud\intune\otel-auth-readiness.ps1'

function Get-NamedFunctionScriptBlock {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string[]]$Names
    )
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $SourcePath, [ref]$tokens, [ref]$errors
    )
    if ($errors.Count -ne 0) { throw 'production-function-parse-failed' }
    $source = New-Object System.Collections.Generic.List[string]
    foreach ($name in $Names) {
        $function = $ast.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
        }, $true) | Where-Object Name -CEQ $name | Select-Object -First 1
        if (-not $function) { throw ('production-function-missing:{0}' -f $name) }
        $source.Add($function.Extent.Text)
    }
    return [scriptblock]::Create(($source -join "`n`n"))
}

function New-ExactFileAcl {
    param(
        [Parameter(Mandatory = $true)][string]$ReaderSid,
        [Parameter(Mandatory = $true)]
        [System.Security.AccessControl.FileSystemRights]$ReaderRights
    )
    $acl = New-Object System.Security.AccessControl.FileSecurity
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner(
        [System.Security.Principal.SecurityIdentifier]'S-1-5-32-544'
    )
    foreach ($sid in 'S-1-5-18','S-1-5-32-544') {
        $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
            [System.Security.Principal.SecurityIdentifier]$sid,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            [System.Security.AccessControl.AccessControlType]::Allow
        ))
    }
    $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
        [System.Security.Principal.SecurityIdentifier]$ReaderSid,
        $ReaderRights,
        [System.Security.AccessControl.AccessControlType]::Allow
    ))
    return $acl
}

. (Get-NamedFunctionScriptBlock -SourcePath $HelperPath -Names @(
    'Fail',
    'Test-TrustedOwner',
    'Get-NormalizedAllowRights',
    'Assert-ExactCredentialAcl'
))

$fixtureRoot = Join-Path ([System.IO.Path]::GetTempPath()) `
    ('otel-acl-persistence-{0}' -f [Guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $fixtureRoot | Out-Null

    $credential = Join-Path $fixtureRoot 'credential-persist-reload.dpapi'
    [System.IO.File]::WriteAllText($credential, 'value-free-fixture')
    $credentialAcl = New-ExactFileAcl -ReaderSid 'S-1-5-32-545' `
        -ReaderRights ([System.Security.AccessControl.FileSystemRights]::ReadAndExecute)
    $credentialInfo = [System.IO.FileInfo]::new($credential)
    [System.IO.FileSystemAclExtensions]::SetAccessControl(
        $credentialInfo, $credentialAcl
    )
    $persistedCredentialAcl = [System.IO.FileSystemAclExtensions]::GetAccessControl(
        $credentialInfo
    )
    if (-not $persistedCredentialAcl.AreAccessRulesProtected) {
        throw 'credential-persist-reload-unprotected'
    }
    Assert-ExactCredentialAcl $credential

    . (Get-NamedFunctionScriptBlock -SourcePath $ReadinessPath -Names @(
        'Get-RegularSingleLinkInformation',
        'Test-TrustedOwner',
        'Get-NormalizedAllowRights',
        'Test-ExactReadinessReceiptAcl'
    ))

    $expectedSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $receipt = Join-Path $fixtureRoot 'receipt-persist-reload.receipt'
    [System.IO.File]::WriteAllText($receipt, '')
    $receiptAcl = New-ExactFileAcl -ReaderSid $expectedSid `
        -ReaderRights ([System.Security.AccessControl.FileSystemRights]::WriteData)
    $receiptInfo = [System.IO.FileInfo]::new($receipt)
    [System.IO.FileSystemAclExtensions]::SetAccessControl($receiptInfo, $receiptAcl)
    $persistedReceiptAcl = [System.IO.FileSystemAclExtensions]::GetAccessControl(
        $receiptInfo
    )
    $receiptRule = $persistedReceiptAcl.GetAccessRules(
        $true, $true, [System.Security.Principal.SecurityIdentifier]
    ) | Where-Object {
        $_.IdentityReference.Value -ceq $expectedSid
    } | Select-Object -First 1
    if (-not $receiptRule -or
        -not ([int]$receiptRule.FileSystemRights -band
            [int][System.Security.AccessControl.FileSystemRights]::Synchronize)) {
        throw 'receipt-persist-reload-did-not-materialize-synchronize'
    }
    if (-not (Test-ExactReadinessReceiptAcl -TargetPath $receipt `
        -ExpectedSid $expectedSid)) {
        throw 'receipt-persist-reload-rejected'
    }

    Write-Output 'OTEL_ACL_PERSISTENCE_TESTS_PASSED'
}
finally {
    if (Test-Path -LiteralPath $fixtureRoot) {
        Remove-Item -LiteralPath $fixtureRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
