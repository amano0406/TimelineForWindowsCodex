[CmdletBinding()]
param()

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

function Initialize-TfwcSettingsFile {
    $settingsPath = Join-Path $repoRoot "settings.json"
    if (-not (Test-Path -LiteralPath $settingsPath)) {
        Copy-Item -LiteralPath (Join-Path $repoRoot "settings.example.json") -Destination $settingsPath
    }
}

function Get-TfwcLastExitCode {
    $variable = Get-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
    if ($variable -and $null -ne $variable.Value) {
        return [int]$variable.Value
    }
    if ($?) { return 0 }
    return 1
}

Initialize-TfwcSettingsFile
$docker = Get-TfwcDockerCommand
& $docker info *> $null
if (-not $?) {
    throw "Docker Desktop is installed but the Docker engine is not ready."
}

Write-Host "Starting TimelineForWindowsCodex worker..."
& $docker compose up -d --build worker
if (-not $?) { throw "docker compose failed." }

Write-Host ""
Write-Host "TimelineForWindowsCodex worker-1 was started."
Write-Host "CLI commands execute inside this persistent Compose service container."
Write-Host ""
Write-Host "CLI examples:"
Write-Host "  .\cli.ps1 settings status"
Write-Host "  .\cli.ps1 items list --json"
Write-Host "  .\cli.ps1 items refresh --json"
Write-Host "  .\cli.ps1 items download --to /shared/downloads"
exit (Get-TfwcLastExitCode)
