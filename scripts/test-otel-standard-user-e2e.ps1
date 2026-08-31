<#
.SYNOPSIS
  Hosted-Windows standard-user E2E fixtures for both managed auth backends.

.DESCRIPTION
  Creates a temporary local Users-only account and launches the canonical auth
  functions through a child PowerShell process under that credential. Network,
  broker, collector, and certificate transport are locally intercepted in the
  child; DPAPI and NTFS ACLs are real. No token is printed or stored in output.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$HelperPath = Join-Path $RepositoryRoot `
    'templates\cui-bedrock-govcloud\intune\otel-headers-helper.ps1'
$ChildPath = Join-Path $RepositoryRoot 'scripts\test-otel-standard-user-child.ps1'
$PowerShell = Join-Path $env:SystemRoot `
    'System32\WindowsPowerShell\v1.0\powershell.exe'
$fixtureRoot = Join-Path ([System.IO.Path]::GetTempPath()) `
    ('otel-standard-user-{0}' -f [Guid]::NewGuid().ToString('N'))
$userName = 'oteltest{0}' -f ([Guid]::NewGuid().ToString('N').Substring(0, 10))
$passwordText = '{0}aA1!' -f ([Guid]::NewGuid().ToString('N'))
$password = ConvertTo-SecureString $passwordText -AsPlainText -Force
$credential = [pscredential]::new('.\' + $userName, $password)
$createdUser = $false
$FixtureHelperPath = Join-Path $fixtureRoot 'otel-headers-helper.ps1'
$FixtureChildPath = Join-Path $fixtureRoot 'test-otel-standard-user-child.ps1'

function Grant-StandardUserFixtureAccess([string]$UserSid) {
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
        [System.Security.Principal.SecurityIdentifier]$UserSid,
        'Modify', $inherit,
        [System.Security.AccessControl.PropagationFlags]::None, 'Allow'
    ))
    [System.IO.FileSystemAclExtensions]::SetAccessControl(
        [System.IO.DirectoryInfo]::new($fixtureRoot), $acl
    )
}

function New-ExactCredentialAcl([string]$UserSid) {
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

function Protect-TestValue([string]$Value) {
    $plain = [System.Text.Encoding]::UTF8.GetBytes($Value)
    $protected = $null
    try {
        $protected = [System.Security.Cryptography.ProtectedData]::Protect(
            $plain, $null,
            [System.Security.Cryptography.DataProtectionScope]::LocalMachine
        )
        return [Convert]::ToBase64String($protected)
    }
    finally {
        if ($plain) { [Array]::Clear($plain, 0, $plain.Length) }
        if ($protected) { [Array]::Clear($protected, 0, $protected.Length) }
    }
}

function Invoke-Backend([string]$Backend, [string]$UserSid) {
    $resultPath = Join-Path $fixtureRoot ('{0}.result' -f $Backend)
    $credentialPath = Join-Path $fixtureRoot 'credential.dpapi'
    $brokerFixturePath = Join-Path $fixtureRoot 'broker.json'
    $arguments = @(
        '-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
        '-File',('"{0}"' -f $FixtureChildPath),
        '-Backend',$Backend,
        '-HelperPath',('"{0}"' -f $FixtureHelperPath),
        '-CredentialPath',('"{0}"' -f $credentialPath),
        '-ExpectedUserSid',$UserSid,
        '-BrokerFixturePath',('"{0}"' -f $brokerFixturePath),
        '-ResultPath',('"{0}"' -f $resultPath)
    ) -join ' '
    $process = Start-Process -FilePath $PowerShell -ArgumentList $arguments `
        -Credential $credential -LoadUserProfile -PassThru -Wait -WindowStyle Hidden
    $resultExists = Test-Path -LiteralPath $resultPath -PathType Leaf
    $result = if ($resultExists) {
        [System.IO.File]::ReadAllText($resultPath)
    }
    else { '' }
    if ($process.ExitCode -ne 0) {
        if ($result -cnotmatch '^STANDARD_USER_E2E_FAILED:[a-z0-9-]+$') {
            throw ('standard-user-backend-failed:{0}:diagnostic-missing' -f $Backend)
        }
        $failureCode = $result.Substring('STANDARD_USER_E2E_FAILED:'.Length)
        throw ('standard-user-backend-failed:{0}:{1}' -f $Backend, $failureCode)
    }
    if (-not $resultExists) {
        throw ('standard-user-backend-failed:{0}:result-missing' -f $Backend)
    }
    $expected = 'STANDARD_USER_E2E_READY:{0}:{1}' -f $Backend, $UserSid
    if ($result -cne $expected) {
        throw ('standard-user-backend-result-invalid:{0}' -f $Backend)
    }
}

try {
    New-Item -ItemType Directory -Path $fixtureRoot | Out-Null
    New-LocalUser -Name $userName -Password $password `
        -AccountNeverExpires -PasswordNeverExpires | Out-Null
    $createdUser = $true
    $user = Get-LocalUser -Name $userName
    $userSid = $user.SID.Value
    # Explicitly add only the built-in Users role; never Administrators. Some
    # Windows builds add it during account creation, so tolerate that exact
    # already-member state without masking any other error.
    $isUserMember = Get-LocalGroupMember -SID 'S-1-5-32-545' |
        Where-Object { $_.SID.Value -ceq $userSid }
    if (-not $isUserMember) {
        Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $userName
    }
    Grant-StandardUserFixtureAccess $userSid
    Copy-Item -LiteralPath $HelperPath -Destination $FixtureHelperPath
    Copy-Item -LiteralPath $ChildPath -Destination $FixtureChildPath

    $credentialPath = Join-Path $fixtureRoot 'credential.dpapi'
    $token = ('D' * 20) + [Guid]::NewGuid().ToString('N')
    [System.IO.File]::WriteAllText($credentialPath, (Protect-TestValue $token))
    [System.IO.FileSystemAclExtensions]::SetAccessControl(
        [System.IO.FileInfo]::new($credentialPath),
        (New-ExactCredentialAcl $userSid)
    )
    $token = $null

    # The child builds a value-free certificate-shaped fixture and never calls
    # a live broker. This verifies standard-user execution of the canonical
    # broker validation/schema/TTL path; live PKI remains an activation gate.
    $certificateFixture = [ordered]@{
        HasPrivateKey = $true
        NotBefore = [DateTime]::UtcNow.AddMinutes(-5)
        NotAfter = [DateTime]::UtcNow.AddHours(2)
        Extensions = @([ordered]@{
            Oid = [ordered]@{ Value = '2.5.29.37' }
            EnhancedKeyUsages = @([ordered]@{ Value = '1.3.6.1.5.5.7.3.2' })
        })
    }
    [System.IO.File]::WriteAllText(
        (Join-Path $fixtureRoot 'broker.json'),
        ($certificateFixture | ConvertTo-Json -Depth 6)
    )

    Invoke-Backend -Backend machine-dpapi -UserSid $userSid
    Invoke-Backend -Backend broker-mtls -UserSid $userSid
    Write-Output 'STANDARD_USER_E2E_READY'
}
finally {
    $passwordText = $null
    $password = $null
    $credential = $null
    if ($createdUser) {
        Remove-LocalUser -Name $userName -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $fixtureRoot) {
        Remove-Item -LiteralPath $fixtureRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
