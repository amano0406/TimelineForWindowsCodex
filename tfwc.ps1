[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CommandArgs
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

function Show-Usage {
    Write-Host "TimelineForWindowsCodex PowerShell front door"
    Write-Host ""
    Write-Host "Usage:"
    Write-Host "  .\tfwc.ps1 build"
    Write-Host "  .\tfwc.ps1 up"
    Write-Host "  .\tfwc.ps1 settings init"
    Write-Host "  .\tfwc.ps1 settings status"
    Write-Host "  .\tfwc.ps1 settings inputs list"
    Write-Host "  .\tfwc.ps1 settings master show"
    Write-Host "  .\tfwc.ps1 items list --json"
    Write-Host "  .\tfwc.ps1 items refresh --json"
    Write-Host "  .\tfwc.ps1 items download --to /shared/outputs/handoff"
    Write-Host "  .\tfwc.ps1 runs list"
    Write-Host "  .\tfwc.ps1 runs show --run-id <RUN_ID>"
    Write-Host ""
    Write-Host "Advanced:"
    Write-Host "  .\tfwc.ps1 compose <docker compose args>"
    Write-Host "  .\tfwc.ps1 smoke [smoke args]"
}

if ($null -eq $CommandArgs -or $CommandArgs.Count -eq 0) {
    Show-Usage
    exit 0
}

$CommandName = $CommandArgs[0].ToLowerInvariant()
$RestArgs = @()
if ($CommandArgs.Count -gt 1) {
    $RestArgs = $CommandArgs[1..($CommandArgs.Count - 1)]
}

if ($CommandName -eq "help" -or $CommandName -eq "-h" -or $CommandName -eq "--help") {
    Show-Usage
    exit 0
}

switch ($CommandName) {
    "build" {
        & docker compose build @RestArgs
        exit $LASTEXITCODE
    }
    "up" {
        & docker compose up @RestArgs
        exit $LASTEXITCODE
    }
    "down" {
        & docker compose down @RestArgs
        exit $LASTEXITCODE
    }
    "compose" {
        & docker compose @RestArgs
        exit $LASTEXITCODE
    }
    "smoke" {
        & python tests/smoke/run_docker_compose_refresh.py @RestArgs
        exit $LASTEXITCODE
    }
    default {
        & docker compose run --rm worker @CommandArgs
        exit $LASTEXITCODE
    }
}
