# Run only after a successful authenticated Leaguepedia probe using the same files.
[CmdletBinding()]
param(
    [string]$UserFile = "$PSScriptRoot/../../artifacts/leaguepedia-bot-user.txt",
    [string]$PasswordFile = "$PSScriptRoot/../../artifacts/leaguepedia-bot-password.txt",
    [string]$TargetConfig = "$PSScriptRoot/target.local.psd1"
)
$ErrorActionPreference = 'Stop'
foreach ($path in @($UserFile, $PasswordFile)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Both credential files must exist' }
    if ([string]::IsNullOrWhiteSpace([IO.File]::ReadAllText((Resolve-Path -LiteralPath $path)))) {
        throw 'Credential files must not be empty'
    }
}
& "$PSScriptRoot/preflight.ps1" -TargetConfig $TargetConfig
if ($LASTEXITCODE -ne 0) { throw 'Preflight failed' }
$targetSettings = Import-PowerShellDataFile -LiteralPath $TargetConfig
$sshOptions = @('-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=yes', '-o', 'ForwardAgent=no')
& ssh @sshOptions $targetSettings.SshTarget 'if docker secret inspect rift_leaguepedia_bot_user_v1 >/dev/null 2>&1 || docker secret inspect rift_leaguepedia_bot_password_v1 >/dev/null 2>&1; then exit 1; fi'
if ($LASTEXITCODE -ne 0) { throw 'Secrets already exist or the check failed; inspect privately before retrying' }
$secrets = @(
    @{ Name = 'rift_leaguepedia_bot_user_v1'; File = $UserFile },
    @{ Name = 'rift_leaguepedia_bot_password_v1'; File = $PasswordFile }
)
foreach ($secret in $secrets) {
    # Only the fixed secret name enters argv. The value travels over SSH stdin.
    $value = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $secret.File)).Trim()
    try {
        $value | & ssh @sshOptions $targetSettings.SshTarget "docker secret create $($secret.Name) - >/dev/null"
        if ($LASTEXITCODE -ne 0) { throw 'Secret provisioning failed; preserve any created secret and inspect privately' }
    } finally {
        Remove-Variable value
    }
}
Write-Output 'Leaguepedia secrets provisioned. Live mode has not been enabled.'
