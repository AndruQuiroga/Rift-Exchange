[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^ghcr\.io/andruquiroga/rift-api@sha256:[a-f0-9]{64}$')][string]$ApiImage,
    [Parameter(Mandatory)][ValidatePattern('^ghcr\.io/andruquiroga/rift-web@sha256:[a-f0-9]{64}$')][string]$WebImage,
    [Parameter(Mandatory)][ValidatePattern('^[a-f0-9]{7,40}-[0-9]{8}T[0-9]{6}Z$')][string]$ReleaseId,
    [string]$TargetConfig = "$PSScriptRoot/target.local.psd1",
    [ValidateSet('mock', 'live')][string]$LeaguepediaMode
)
$ErrorActionPreference = 'Stop'
& "$PSScriptRoot/preflight.ps1" -TargetConfig $TargetConfig
if ($LASTEXITCODE -ne 0) { throw 'Preflight failed' }
$targetSettings = Import-PowerShellDataFile -LiteralPath $TargetConfig
$sshOptions = @('-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=yes', '-o', 'ForwardAgent=no')
$targetEnv = @(
    "EXPECTED_HOST='$($targetSettings.ExpectedHost)'",
    "EXPECTED_USER='$($targetSettings.ExpectedUser)'",
    "EXPECTED_SWARM_ID='$($targetSettings.ExpectedSwarmId)'",
    "DATA_NODE='$($targetSettings.DataNode)'",
    "BACKUP_NODE='$($targetSettings.BackupNode)'",
    "INGRESS_NETWORK='$($targetSettings.IngressNetwork)'",
    "INGRESS_ORIGIN='$($targetSettings.IngressOrigin)'"
) -join "`n"
$encodedConfig = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($targetEnv + "`n"))
$remote = "rift-exchange/releases/$ReleaseId"
& ssh @sshOptions $targetSettings.SshTarget "umask 077; mkdir -p $remote; echo $encodedConfig | base64 -d > $remote/target.env"
if ($LASTEXITCODE -ne 0) { throw 'Cannot create release directory' }
& scp @sshOptions "$PSScriptRoot/stack.yml" "$PSScriptRoot/leaguepedia-live.yml" "$PSScriptRoot/backup.sh" "$PSScriptRoot/deploy.sh" "$($targetSettings.SshTarget):$remote/"
if ($LASTEXITCODE -ne 0) { throw 'Cannot upload reviewed release files' }
& ssh @sshOptions $targetSettings.SshTarget "sed -i 's/\r$//' $remote/deploy.sh $remote/backup.sh; sh $remote/deploy.sh $ApiImage $WebImage $ReleaseId '$LeaguepediaMode'"
if ($LASTEXITCODE -ne 0) { throw 'Release failed; inspect task state. No automatic database rollback is performed.' }
