[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$KeepAppData,
    [switch]$KeepSettings
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
Set-Location $repoRoot

function Get-TfwcDockerCommand {
    $dockerExe = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"
    if (Test-Path -LiteralPath $dockerExe) { return $dockerExe }
    $docker = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($docker) { return $docker.Source }
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($docker) { return $docker.Source }
    throw "docker.exe was not found. Install or start Docker Desktop."
}

function Get-TfwcLastExitCode {
    $variable = Get-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
    if ($variable -and $null -ne $variable.Value) {
        return [int]$variable.Value
    }
    if ($?) { return 0 }
    return 1
}

function Confirm-TfwcAction {
    param([Parameter(Mandatory = $true)][string]$Prompt)

    if ($Yes) {
        return $true
    }
    $answer = Read-Host $Prompt
    return $answer -match '^(y|yes)$'
}

function Remove-TfwcVolumeIfExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$VolumeName
    )

    $volumeNames = @(& $docker volume ls --format "{{.Name}}")
    if ($volumeNames -notcontains $VolumeName) {
        return
    }
    & $docker volume rm $VolumeName > $null
    if ((Get-TfwcLastExitCode) -ne 0) {
        throw "Failed to remove Docker volume: $VolumeName"
    }
    Write-Host "Removed Docker volume: $VolumeName"
}

$docker = Get-TfwcDockerCommand
$composeProject = "timeline-for-windows-codex"
$appDataVolume = "${composeProject}_app-data"

Write-Host ""
Write-Host "TimelineForWindowsCodex uninstall"
Write-Host ""
Write-Host "This will remove Docker containers, local images, and the project network."
Write-Host "It will not delete Codex source history, outputs, or downloads."
if (-not $KeepAppData) {
    Write-Host "Optional: saved app data volume: $appDataVolume"
}
if (-not $KeepSettings -and (Test-Path -LiteralPath (Join-Path $repoRoot "settings.json"))) {
    Write-Host "Optional: local settings.json."
}
Write-Host ""

if (-not (Confirm-TfwcAction "Continue with uninstall? (y/n)")) {
    Write-Host "Uninstall canceled."
    exit 1
}

Write-Host "Stopping and removing Docker resources..."
& $docker compose down --rmi local --remove-orphans
if (-not $?) {
    throw "Docker cleanup failed."
}

if (-not $KeepAppData) {
    Write-Host ""
    Write-Host "Saved app data volume:"
    Write-Host "  $appDataVolume"
    Write-Host "This contains container-side application state only."
    if (Confirm-TfwcAction "Delete saved app data too? (y/n)") {
        Remove-TfwcVolumeIfExists -VolumeName $appDataVolume
    }
    else {
        Write-Host "Kept saved app data volume: $appDataVolume"
    }
}
else {
    Write-Host "Kept saved app data volume: $appDataVolume"
}

$settingsPath = Join-Path $repoRoot "settings.json"
if (-not $KeepSettings -and (Test-Path -LiteralPath $settingsPath)) {
    Write-Host ""
    Write-Host "Local settings file:"
    Write-Host "  $settingsPath"
    Write-Host "This includes source roots and the master output root."
    if (Confirm-TfwcAction "Delete settings.json too? (y/n)") {
        Remove-Item -LiteralPath $settingsPath -Force
        Write-Host "Deleted settings.json"
    }
    else {
        Write-Host "Kept settings.json"
    }
}
elseif ($KeepSettings -and (Test-Path -LiteralPath $settingsPath)) {
    Write-Host "Kept settings.json"
}

Write-Host ""
Write-Host "Uninstall completed."
exit 0
