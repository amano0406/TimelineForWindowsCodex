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

    $outputRoot = Get-TfwcConfiguredOutputRoot
    if ($outputRoot -and -not (Test-Path -LiteralPath $outputRoot)) {
        New-Item -ItemType Directory -Path $outputRoot | Out-Null
    }
}

function Get-TfwcConfiguredOutputRoot {
    $settingsPath = Join-Path $repoRoot "settings.json"
    if (-not (Test-Path -LiteralPath $settingsPath)) {
        return $null
    }
    $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
    $outputRoot = [string]$settings.outputRoot
    if ([string]::IsNullOrWhiteSpace($outputRoot)) {
        return $null
    }
    if (-not [System.IO.Path]::IsPathRooted($outputRoot)) {
        $outputRoot = Join-Path $repoRoot $outputRoot
    }
    return [System.IO.Path]::GetFullPath($outputRoot)
}

function Set-TfwcDefaultEnvironmentValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $currentValue = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ([string]::IsNullOrWhiteSpace($currentValue)) {
        Set-Item -Path "Env:$Name" -Value $Value
    }
}

function Initialize-TfwcDockerMountEnvironment {
    Set-TfwcDefaultEnvironmentValue -Name "HOST_TIMELINE_DATA" -Value "C:\TimelineData"
    Set-TfwcDefaultEnvironmentValue -Name "HOST_CODEX_HOME" -Value (Join-Path $env:USERPROFILE ".codex")
    Set-TfwcDefaultEnvironmentValue -Name "HOST_CODEX_BACKUP_HOME" -Value "C:\Codex\archive\migration-backup-2026-03-27\codex-home"
    Set-TfwcDefaultEnvironmentValue -Name "HOST_CODEX_ROOT" -Value "C:\Codex"
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
Initialize-TfwcDockerMountEnvironment
$docker = Get-TfwcDockerCommand
& $docker info *> $null
if (-not $?) {
    throw "Docker Desktop is installed but the Docker engine is not ready."
}

Write-Host "Starting TimelineForWindowsCodex worker..."
$global:LASTEXITCODE = 0
& $docker compose up -d --build worker
if ((Get-TfwcLastExitCode) -ne 0) { throw "docker compose failed." }

Write-Host ""
Write-Host "TimelineForWindowsCodex worker-1 was started."
Write-Host "CLI commands execute inside this persistent Compose service container."
Write-Host ""
Write-Host "CLI examples:"
Write-Host "  .\cli.bat settings status"
Write-Host "  .\cli.bat items list --json"
Write-Host "  .\cli.bat items refresh --json"
Write-Host "  .\cli.bat items download --to C:\TimelineData\windows-codex-downloads"
exit (Get-TfwcLastExitCode)
