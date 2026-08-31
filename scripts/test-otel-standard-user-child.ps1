param(
    [Parameter(Mandatory = $true)][ValidateSet('machine-dpapi','broker-mtls')]
    [string]$Backend,
    [Parameter(Mandatory = $true)][string]$HelperPath,
    [Parameter(Mandatory = $true)][string]$CredentialPath,
    [string]$ExpectedUserSid,
    [string]$BrokerFixturePath,
    [Parameter(Mandatory = $true)][string]$ResultPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$stage = 'initialize'

try {
    $stage = 'identity-context'
    $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    if ([string]::IsNullOrWhiteSpace($ExpectedUserSid) -or
        $currentSid -cne $ExpectedUserSid -or
        ([System.Security.Principal.WindowsPrincipal]::new(
            [System.Security.Principal.WindowsIdentity]::GetCurrent()
        )).IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'standard-user-context-invalid'
    }

    $stage = 'helper-read'
    $source = [System.IO.File]::ReadAllText($HelperPath)
    $tokens = $null
    $errors = $null
    $stage = 'helper-parse'
    $ast = [System.Management.Automation.Language.Parser]::ParseInput(
        $source, [ref]$tokens, [ref]$errors
    )
    if ($errors.Count -ne 0) { throw 'helper-parse-failed' }
    foreach ($name in @(
        'Fail',
        'Test-TrustedOwner',
        'Get-NormalizedAllowRights',
        'Assert-ExactCredentialAcl',
        'Get-MachineDpapiToken',
        'Get-BrokerMtlsToken',
        'Assert-CollectorAcceptsToken'
    )) {
        $stage = 'helper-function-load'
        $function = $ast.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
        }, $true) | Where-Object Name -CEQ $name | Select-Object -First 1
        if (-not $function) { throw ('helper-function-missing:{0}' -f $name) }
        . ([scriptblock]::Create($function.Extent.Text))
    }

    # Fixture calls stay value-free and local. The DPAPI path exercises the
    # canonical decrypt/ACL function; broker mode exercises the canonical
    # schema/TTL branch with a standard-user-readable certificate object and
    # intercepted transport. Collector acceptance is intercepted only in this
    # child process; the production helper contains no bypass.
    $stage = 'fixture-configure'
    $script:CredentialPath = $CredentialPath
    $script:MinimumBrokerTokenTtlSeconds = 1200
    $script:CollectorProbeUri = 'https://collector.invalid/v1/logs'
    function global:Invoke-WebRequest {
        param($Method, $Uri, $Headers, $ContentType, $Body, $MaximumRedirection,
            $TimeoutSec, [switch]$UseBasicParsing, $ErrorAction)
        $authorization = [string]$Headers.Authorization
        if ($Method -cne 'Post' -or
            $Uri -cne $script:CollectorProbeUri -or
            $ContentType -cne 'application/x-protobuf' -or
            $MaximumRedirection -ne 0 -or
            $TimeoutSec -ne 10 -or
            -not $UseBasicParsing.IsPresent -or
            [string]$ErrorAction -cne 'Stop' -or
            $Body -isnot [byte[]] -or $Body.Count -ne 0 -or
            $authorization -cnotmatch '^Bearer [^\x00-\x20\x7f]{20,}$') {
            throw 'collector-intercept-contract-invalid'
        }
        $authorization = $null
        return [pscustomobject]@{ StatusCode = 200 }
    }

    if ($Backend -ceq 'machine-dpapi') {
        $stage = 'machine-dpapi-token'
        $token = Get-MachineDpapiToken
    }
    else {
        $stage = 'broker-fixture-configure'
        if ([string]::IsNullOrWhiteSpace($BrokerFixturePath)) {
            throw 'broker-fixture-missing'
        }
        $script:ConfigPath = 'TestRegistry:\OTelAuth'
        function global:Test-Path {
            param($LiteralPath, $PathType)
            if ($LiteralPath -ceq $script:ConfigPath) { return $true }
            return Microsoft.PowerShell.Management\Test-Path @PSBoundParameters
        }
        function global:Get-ItemProperty {
            param($LiteralPath, $ErrorAction)
            if ($LiteralPath -ceq $script:ConfigPath) {
                return [pscustomobject]@{
                    BrokerUri = 'https://broker.invalid/token'
                    ClientCertificateThumbprint = 'A' * 40
                }
            }
            return Microsoft.PowerShell.Management\Get-ItemProperty @PSBoundParameters
        }
        function global:Get-Item {
            param($LiteralPath, $Force, $ErrorAction)
            if ($LiteralPath -like 'Cert:\LocalMachine\My\*') {
                $eku = [System.Security.Cryptography.OidCollection]::new()
                $null = $eku.Add([System.Security.Cryptography.Oid]::new(
                    '1.3.6.1.5.5.7.3.2'
                ))
                $extension = [System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]::new(
                    $eku, $false
                )
                return [pscustomobject]@{
                    HasPrivateKey = $true
                    NotBefore = [DateTime]::UtcNow.AddMinutes(-5)
                    NotAfter = [DateTime]::UtcNow.AddHours(2)
                    Extensions = @($extension)
                }
            }
            return Microsoft.PowerShell.Management\Get-Item @PSBoundParameters
        }
        function global:Invoke-RestMethod {
            param($Method, $Uri, $Certificate, $Headers, $ContentType, $Body,
                $MaximumRedirection, $TimeoutSec, $ErrorAction)
            if ($Method -cne 'Post' -or
                $Uri -cne 'https://broker.invalid/token' -or
                -not $Certificate.HasPrivateKey -or
                $Headers.Accept -cne 'application/json' -or
                $ContentType -cne 'application/json' -or
                $Body -cne '{}' -or
                $MaximumRedirection -ne 0 -or
                $TimeoutSec -ne 10 -or
                [string]$ErrorAction -cne 'Stop') {
                throw 'broker-intercept-contract-invalid'
            }
            return [pscustomobject]@{
                access_token = ('B' * 52)
                token_type = 'Bearer'
                expires_in = 2400
            }
        }
        $stage = 'broker-token'
        $token = Get-BrokerMtlsToken
    }

    $stage = 'token-validation'
    if ([string]::IsNullOrWhiteSpace($token) -or $token.Length -lt 20 -or
        $token -match '[\x00-\x20\x7f]') {
        throw 'credential-value-invalid'
    }
    $stage = 'collector-probe'
    Assert-CollectorAcceptsToken -AccessToken $token
    $token = $null
    $stage = 'result-write'
    [System.IO.File]::WriteAllText(
        $ResultPath,
        ('STANDARD_USER_E2E_READY:{0}:{1}' -f $Backend, $currentSid),
        [System.Text.Encoding]::ASCII
    )
    exit 0
}
catch {
    $failureCode = [string]$_.Exception.Message
    if ($failureCode -cnotmatch '^[a-z0-9-]+$') {
        $failureCode = 'unexpected-{0}-error' -f $stage
    }
    $failureReceipt = 'STANDARD_USER_E2E_FAILED:{0}' -f $failureCode
    if ($failureReceipt -cnotmatch '^STANDARD_USER_E2E_FAILED:[a-z0-9-]+$') {
        $failureReceipt = 'STANDARD_USER_E2E_FAILED:unexpected-receipt-error'
    }
    [System.IO.File]::WriteAllText(
        $ResultPath,
        $failureReceipt,
        [System.Text.Encoding]::ASCII
    )
    exit 1
}
finally { $token = $null }
