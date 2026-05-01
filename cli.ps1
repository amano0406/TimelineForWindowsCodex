[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs
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

function Initialize-TfwcSettingsFile {
    $settingsPath = Join-Path $repoRoot "settings.json"
    if (-not (Test-Path -LiteralPath $settingsPath)) {
        Copy-Item -LiteralPath (Join-Path $repoRoot "settings.example.json") -Destination $settingsPath
    }
}

function Show-TfwcUsage {
    Write-Host "TimelineForWindowsCodex CLI"
    Write-Host ""
    Write-Host "Usage:"
    Write-Host "  .\cli.ps1 settings status"
    Write-Host "  .\cli.ps1 settings init"
    Write-Host "  .\cli.ps1 settings inputs list"
    Write-Host "  .\cli.ps1 settings master show"
    Write-Host "  .\cli.ps1 items list --json"
    Write-Host "  .\cli.ps1 items refresh --json"
    Write-Host "  .\cli.ps1 items download --to /shared/downloads"
}

function Get-TfwcLastExitCode {
    $variable = Get-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
    if ($variable -and $null -ne $variable.Value) {
        return [int]$variable.Value
    }
    if ($?) { return 0 }
    return 1
}

if ($null -eq $CliArgs -or $CliArgs.Count -eq 0) {
    Show-TfwcUsage
    exit 0
}

Initialize-TfwcSettingsFile
$docker = Get-TfwcDockerCommand
& $docker info *> $null
if (-not $?) {
    throw "Docker Desktop is installed but the Docker engine is not ready."
}

& $docker compose run --rm worker @CliArgs
exit (Get-TfwcLastExitCode)
