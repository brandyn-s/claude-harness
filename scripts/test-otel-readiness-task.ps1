<#
.SYNOPSIS
  Windows acceptance tests for the OTel readiness Task Scheduler oracle.

.DESCRIPTION
  Runs a disposable copy of the production readiness script with a deterministic
  value-free wrapper. It exercises repeated immediate completion, explicit
  failure, and timeout cleanup without reading or changing Program Files,
  credentials, registry configuration, collector state, or Intune.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$CanonicalReadiness = Join-Path $RepositoryRoot `
    'templates\cui-bedrock-govcloud\intune\otel-auth-readiness.ps1'
$WindowsPowerShell = Join-Path $env:SystemRoot `
    'System32\WindowsPowerShell\v1.0\powershell.exe'
$fixtureRoot = Join-Path ([System.IO.Path]::GetTempPath()) `
    ('otel-readiness-task-{0}' -f [Guid]::NewGuid().ToString('N'))

function Assert-ReadinessCleanup([string]$CaseName) {
    $tasks = @(Get-ScheduledTask -TaskName 'Example-OTelAuthReadiness-Test-*' `
        -ErrorAction SilentlyContinue)
    if ($tasks.Count -ne 0) { throw ('{0}:task-failure-cleanup' -f $CaseName) }
    $receipts = @(Get-ChildItem -LiteralPath $fixtureRoot `
        -Filter '.otel-readiness-*.receipt' -Force -ErrorAction SilentlyContinue)
    if ($receipts.Count -ne 0) { throw ('{0}:task-hang-cleanup' -f $CaseName) }
}

function Invoke-ReadinessCase {
    param(
        [Parameter(Mandatory = $true)][string]$CaseName,
        [Parameter(Mandatory = $true)][ValidateSet('success','failure','hang')]
        [string]$Mode,
        [Parameter(Mandatory = $true)][int]$ExpectedExit
    )
    [System.IO.File]::WriteAllText((Join-Path $fixtureRoot 'mode.txt'), $Mode)
    $output = @(& $WindowsPowerShell -NoLogo -NoProfile -NonInteractive `
        -ExecutionPolicy Bypass -File (Join-Path $fixtureRoot 'otel-auth-readiness.ps1') `
        -ExpectedBackend machine-dpapi 2>&1)
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne $ExpectedExit) {
        throw ('{0}:unexpected-exit:{1}' -f $CaseName, $exitCode)
    }
    $expectedOutput = if ($ExpectedExit -eq 0) {
        'OTEL_AUTH_READINESS_VALID:machine-dpapi'
    }
    else { 'OTEL_AUTH_READINESS_INVALID' }
    if ($output.Count -ne 1 -or [string]$output[0] -cne $expectedOutput) {
        throw ('{0}:unexpected-output' -f $CaseName)
    }
    Assert-ReadinessCleanup $CaseName
}

try {
    New-Item -ItemType Directory -Path $fixtureRoot | Out-Null
    $readinessSource = [System.IO.File]::ReadAllText($CanonicalReadiness)
    if (-not $readinessSource.Contains('$ReadinessTimeoutSeconds = 30')) {
        throw 'readiness-timeout-contract-missing'
    }
    $readinessSource = $readinessSource.Replace(
        '$ReadinessTimeoutSeconds = 30',
        '$ReadinessTimeoutSeconds = 2'
    )
    $readinessSource = $readinessSource.Replace(
        "'Example-OTelAuthReadiness-{0}'",
        "'Example-OTelAuthReadiness-Test-{0}'"
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot 'otel-auth-readiness.ps1'), $readinessSource,
        [System.Text.UTF8Encoding]::new($false)
    )

    $wrapper = @'
@echo off
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0test-readiness-helper.ps1" %*
exit /b %ERRORLEVEL%
'@
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot 'otel-headers-helper.cmd'), $wrapper,
        [System.Text.Encoding]::ASCII
    )
    $helper = @'
param(
    [switch]$ReadinessProbe,
    [string]$ReadinessReceiptPath,
    [string]$ReadinessNonce,
    [string]$ExpectedReadinessSid,
    [string]$ReadinessInvocationId
)
$mode = [System.IO.File]::ReadAllText((Join-Path $PSScriptRoot 'mode.txt')).Trim()
if ($mode -ceq 'hang') { Start-Sleep -Seconds 60; exit 9 }
if ($mode -ceq 'failure') { exit 7 }
if (-not $ReadinessProbe) { exit 8 }
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if ($sid -cne $ExpectedReadinessSid) { exit 6 }
$receipt = 'OTEL_HEADERS_HELPER_READY:{0}:{1}:{2}:{3}' -f `
    'machine-dpapi', $sid, $ReadinessNonce, $ReadinessInvocationId
[System.IO.File]::WriteAllText($ReadinessReceiptPath, $receipt)
exit 0
'@
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot 'test-readiness-helper.ps1'), $helper,
        [System.Text.UTF8Encoding]::new($false)
    )

    foreach ($iteration in 1..3) {
        Invoke-ReadinessCase -CaseName ('immediate-success-repeat-{0}' -f $iteration) `
            -Mode success -ExpectedExit 0
    }
    Invoke-ReadinessCase -CaseName 'task-failure-cleanup' `
        -Mode failure -ExpectedExit 1
    Invoke-ReadinessCase -CaseName 'task-hang-cleanup' `
        -Mode hang -ExpectedExit 1

    Write-Output 'OTEL_READINESS_TASK_TESTS_PASSED'
}
finally {
    Get-ScheduledTask -TaskName 'Example-OTelAuthReadiness-Test-*' `
        -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false `
        -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $fixtureRoot) {
        Remove-Item -LiteralPath $fixtureRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
