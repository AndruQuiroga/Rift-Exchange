# Read-only workstation -> Docker manager checks. Target inventory stays local.
[CmdletBinding()]
param([string]$TargetConfig = "$PSScriptRoot/target.local.psd1")
$ErrorActionPreference = 'Stop'
$targetSettings = Import-PowerShellDataFile -LiteralPath $TargetConfig
foreach ($key in @('SshTarget', 'ExpectedHost', 'ExpectedUser', 'ExpectedSwarmId', 'DataNode', 'BackupNode', 'BackupSshTarget', 'IngressNetwork')) {
    if ($targetSettings[$key] -notmatch '^[a-zA-Z0-9][a-zA-Z0-9._-]*$') { throw "Invalid target configuration: $key" }
}
if ($targetSettings.IngressOrigin -notmatch '^https?://[a-zA-Z0-9.:_-]+$') { throw 'Invalid ingress origin' }
if ($targetSettings.DataNode -ne $targetSettings.ExpectedHost) { throw 'Release manager must own the database for local snapshot checks' }
if ($targetSettings.DataNode -eq $targetSettings.BackupNode) { throw 'Backups must use a separate node' }
$remoteScript = @"
set -eu
printf 'host=%s\n' "`$(hostname)"
printf 'user=%s\n' "`$(id -un)"
printf 'manager=%s\n' "`$(docker info --format '{{.Swarm.ControlAvailable}}')"
printf 'swarm_id=%s\n' "`$(docker info --format '{{.Swarm.Cluster.ID}}')"
printf 'ingress=%s\n' "`$(docker network inspect '`$1' --format '{{.Driver}}/{{.Scope}}')"
docker node ls --format 'node={{.Hostname}}|{{.Status}}|{{.Availability}}|{{.ManagerStatus}}'
docker stack ls --format 'stack={{.Name}}'
df -Pk / | awk 'NR==2 {printf "root_free_kib=%s\n", `$4}'
awk '/MemAvailable:/ {printf "memory_available_kib=%s\n", `$2}' /proc/meminfo
"@
# Substitute a validated network name, without adding shell syntax.
$remoteScript = $remoteScript.Replace("'`$1'", "'$($targetSettings.IngressNetwork)'")
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remoteScript.Replace("`r`n", "`n")))
$output = @(& ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes -o ForwardAgent=no $targetSettings.SshTarget "echo $encoded | base64 -d | sh")
if ($LASTEXITCODE -ne 0) { throw 'Read-only SSH preflight failed; check private network and existing SSH identity' }
$fields = @{}
$nodes = @()
$stacks = @()
foreach ($line in $output) {
    $parts = ([string]$line) -split '=', 2
    if ($parts.Count -ne 2) { throw 'Unexpected remote preflight output' }
    switch ($parts[0]) {
        'node' { $nodes += $parts[1] }
        'stack' { $stacks += $parts[1] }
        default { $fields[$parts[0]] = $parts[1].Trim() }
    }
}
if ($fields['host'] -cne $targetSettings.ExpectedHost -or $fields['user'] -cne $targetSettings.ExpectedUser) { throw 'SSH host/account mismatch' }
if ($fields['manager'] -ne 'true' -or $fields['swarm_id'] -cne $targetSettings.ExpectedSwarmId) { throw 'Unexpected Swarm manager/cluster' }
if ($fields['ingress'] -ne 'overlay/swarm') { throw 'Ingress network is not a Swarm overlay' }
if ($nodes.Count -eq 0) { throw 'No Swarm nodes returned' }
foreach ($node in $nodes) {
    $state = $node -split '\|', 4
    if ($state.Count -ne 4 -or $state[1] -ne 'Ready' -or $state[2] -ne 'Active' -or $state[3] -notin @('Leader', 'Reachable')) {
        throw 'Swarm node readiness/manager membership needs private review'
    }
}
[pscustomobject]@{
    ObservedUtc = [DateTime]::UtcNow.ToString('o')
    ExpectedTargetVerified = $true
    ReadyManagers = $nodes.Count
    RootFreeKiB = [long]$fields['root_free_kib']
    MemoryAvailableKiB = [long]$fields['memory_available_kib']
    RiftStackExists = ($stacks -contains 'rift-exchange')
    Scope = 'Read-only infrastructure reachability; application readiness and ownership not verified'
} | ConvertTo-Json
