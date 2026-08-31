<#
.SYNOPSIS
  Windows acceptance tests for REM051's production path-safety functions.

.DESCRIPTION
  Loads the exact native declarations and function ASTs from the production
  remediation, then invokes them only in disposable trees. The fixture never
  redirects ProgramFiles and never executes the full remediation, so it cannot
  install or overwrite managed files on a developer endpoint.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$RemediationPath = Join-Path $RepositoryRoot `
    'templates\cui-bedrock-govcloud\intune\REM051-remediate.ps1'
$remediationSource = [System.IO.File]::ReadAllText($RemediationPath)

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
    if ($errors.Count -ne 0) { throw 'production-oracle-parse-failed' }
    $source = New-Object System.Collections.Generic.List[string]
    foreach ($name in $Names) {
        $function = $ast.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
        }, $true) | Where-Object Name -CEQ $name | Select-Object -First 1
        if (-not $function) { throw ('production-oracle-function-missing:{0}' -f $name) }
        $source.Add($function.Extent.Text)
    }
    return [scriptblock]::Create(($source -join "`n`n"))
}

$nativeMatch = [regex]::Match(
    $remediationSource,
    "Add-Type -TypeDefinition @'\r?\n(?<source>.*?)\r?\n'@",
    [System.Text.RegularExpressions.RegexOptions]::Singleline
)
if (-not $nativeMatch.Success) { throw 'production-native-oracle-missing' }
if (-not ('Example.Otel.SafeFileNative' -as [type])) {
    Add-Type -TypeDefinition $nativeMatch.Groups['source'].Value
}

. (Get-NamedFunctionScriptBlock -SourcePath $RemediationPath -Names @(
    'Test-TrustedOwner',
    'Test-AdminWritableOnly',
    'Get-VerifiedFileInformation',
    'Test-VerifiedAdminDirectory',
    'Test-VerifiedRegularSingleLinkFile',
    'Write-VerifiedAtomicFile'
))

function New-AdminOwnedDirectoryAcl {
    $inherit = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
               [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner(
        [System.Security.Principal.SecurityIdentifier]'S-1-5-32-544'
    )
    foreach ($sid in 'S-1-5-18','S-1-5-32-544') {
        $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
            [System.Security.Principal.SecurityIdentifier]$sid,
            'FullControl', $inherit,
            [System.Security.AccessControl.PropagationFlags]::None, 'Allow'
        ))
    }
    $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
        [System.Security.Principal.SecurityIdentifier]'S-1-5-32-545',
        'ReadAndExecute', $inherit,
        [System.Security.AccessControl.PropagationFlags]::None, 'Allow'
    ))
    return $acl
}

function New-AdminOwnedFileAcl {
    $acl = New-Object System.Security.AccessControl.FileSecurity
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner(
        [System.Security.Principal.SecurityIdentifier]'S-1-5-32-544'
    )
    foreach ($sid in 'S-1-5-18','S-1-5-32-544') {
        $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
            [System.Security.Principal.SecurityIdentifier]$sid,
            'FullControl', 'Allow'
        ))
    }
    $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
        [System.Security.Principal.SecurityIdentifier]'S-1-5-32-545',
        'ReadAndExecute', 'Allow'
    ))
    return $acl
}

function Set-AdminOwnedDirectory([string]$Path) {
    $directory = [System.IO.Directory]::CreateDirectory($Path)
    [System.IO.FileSystemAclExtensions]::SetAccessControl(
        $directory, (New-AdminOwnedDirectoryAcl)
    )
}

function Remove-FixtureTree([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
        } | Sort-Object FullName -Descending | Remove-Item -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
}

function Test-NormalProgramFilesAclFixture {
    $fixtureRoot = Join-Path ([System.IO.Path]::GetTempPath()) `
        ('rem051-normal-acl-{0}' -f [Guid]::NewGuid().ToString('N'))
    try {
        $programFiles = Join-Path $fixtureRoot 'Program Files'
        $acl = New-AdminOwnedDirectoryAcl
        $inherit = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
                   [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
        $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
            [System.Security.Principal.SecurityIdentifier]'S-1-3-0',
            'FullControl', $inherit,
            [System.Security.AccessControl.PropagationFlags]::InheritOnly,
            'Allow'
        ))
        $directory = [System.IO.Directory]::CreateDirectory($programFiles)
        [System.IO.FileSystemAclExtensions]::SetAccessControl($directory, $acl)

        $script:ProgramFilesRoot = $programFiles
        if (-not (Test-VerifiedAdminDirectory $programFiles)) {
            throw 'normal-program-files-acl-rejected'
        }
    }
    finally { Remove-FixtureTree $fixtureRoot }
}

function Invoke-LinkAttackFixture([string]$LinkKind) {
    $fixtureRoot = Join-Path ([System.IO.Path]::GetTempPath()) `
        ('rem051-path-safety-{0}' -f [Guid]::NewGuid().ToString('N'))
    $programFiles = Join-Path $fixtureRoot 'Program Files'
    $managedDirectory = Join-Path $programFiles 'ClaudeCode'
    $externalDirectory = Join-Path $fixtureRoot 'external-target'
    $externalFile = Join-Path $externalDirectory 'privileged-target.txt'
    $credentialPath = Join-Path $managedDirectory 'otel-legacy-token.dpapi'

    try {
        Set-AdminOwnedDirectory $programFiles
        New-Item -ItemType Directory -Path $externalDirectory | Out-Null
        [System.IO.File]::WriteAllText($externalFile, 'unchanged-sentinel')
        [System.IO.FileSystemAclExtensions]::SetAccessControl(
            [System.IO.FileInfo]::new($externalFile), (New-AdminOwnedFileAcl)
        )
        $script:ProgramFilesRoot = $programFiles

        switch ($LinkKind) {
            'DirectoryJunction' {
                $command = 'mklink /J "{0}" "{1}"' -f `
                    $managedDirectory, $externalDirectory
                & $env:ComSpec /d /c $command | Out-Null
                if ($LASTEXITCODE -ne 0) { throw 'junction-fixture-creation-failed' }
            }
            'SymbolicLink' {
                Set-AdminOwnedDirectory $managedDirectory
                New-Item -ItemType SymbolicLink -Path $credentialPath `
                    -Target $externalFile -ErrorAction Stop | Out-Null
            }
            'HardLink' {
                Set-AdminOwnedDirectory $managedDirectory
                New-Item -ItemType HardLink -Path $credentialPath `
                    -Target $externalFile -ErrorAction Stop | Out-Null
            }
            default { throw 'unknown-link-fixture' }
        }

        $contentBefore = [System.IO.File]::ReadAllText($externalFile)
        $fileAclBefore = (Get-Acl -LiteralPath $externalFile).Sddl
        $directoryAclBefore = (Get-Acl -LiteralPath $externalDirectory).Sddl
        $accepted = $true
        try {
            Write-VerifiedAtomicFile -TargetPath $credentialPath `
                -Content 'value-free-replacement' `
                -Encoding ([System.Text.UTF8Encoding]::new($false)) `
                -AclObject (New-AdminOwnedFileAcl)
        }
        catch { $accepted = $false }

        if ($accepted) { throw 'unsafe-link-was-accepted' }
        if ([System.IO.File]::ReadAllText($externalFile) -cne $contentBefore) {
            throw 'target-content-changed'
        }
        if ((Get-Acl -LiteralPath $externalFile).Sddl -cne $fileAclBefore) {
            throw 'target-acl-changed'
        }
        if ((Get-Acl -LiteralPath $externalDirectory).Sddl -cne $directoryAclBefore) {
            throw 'target-acl-changed'
        }
    }
    finally { Remove-FixtureTree $fixtureRoot }
}

function Test-ProductionOracleMutationSensitivity {
    # production-oracle-mutation-sensitivity: prove the hard-link fixture would
    # fail if the exact NumberOfLinks guard were removed from production.
    $fixtureRoot = Join-Path ([System.IO.Path]::GetTempPath()) `
        ('rem051-mutation-{0}' -f [Guid]::NewGuid().ToString('N'))
    try {
        $programFiles = Join-Path $fixtureRoot 'Program Files'
        $managedDirectory = Join-Path $programFiles 'ClaudeCode'
        $target = Join-Path $fixtureRoot 'target.txt'
        $link = Join-Path $managedDirectory 'linked.dpapi'
        Set-AdminOwnedDirectory $programFiles
        Set-AdminOwnedDirectory $managedDirectory
        [System.IO.File]::WriteAllText($target, 'sentinel')
        [System.IO.FileSystemAclExtensions]::SetAccessControl(
            [System.IO.FileInfo]::new($target), (New-AdminOwnedFileAcl)
        )
        New-Item -ItemType HardLink -Path $link -Target $target | Out-Null
        $script:ProgramFilesRoot = $programFiles
        if (Test-VerifiedRegularSingleLinkFile $link) {
            throw 'canonical-hard-link-oracle-accepted'
        }

        $tokens = $null
        $errors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile(
            $RemediationPath, [ref]$tokens, [ref]$errors
        )
        $function = $ast.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -ceq 'Test-VerifiedRegularSingleLinkFile'
        }, $true) | Select-Object -First 1
        $mutated = $function.Extent.Text.Replace(
            'function Test-VerifiedRegularSingleLinkFile',
            'function Test-MutatedVerifiedRegularSingleLinkFile'
        ).Replace(
            '$information.NumberOfLinks -eq 1 -and',
            '$true -and'
        )
        if ($mutated -ceq $function.Extent.Text) { throw 'mutation-probe-not-live' }
        . ([scriptblock]::Create($mutated))
        if (-not (Test-MutatedVerifiedRegularSingleLinkFile $link)) {
            throw 'mutation-probe-not-live'
        }
    }
    finally { Remove-FixtureTree $fixtureRoot }
}

foreach ($linkKind in 'DirectoryJunction','SymbolicLink','HardLink') {
    Invoke-LinkAttackFixture $linkKind
}
Test-NormalProgramFilesAclFixture
Test-ProductionOracleMutationSensitivity

Write-Output 'REM051_PATH_SAFETY_TESTS_PASSED'
