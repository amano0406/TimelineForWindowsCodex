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

function Show-TfwcUsage {
    Write-Host "TimelineForWindowsCodex CLI"
    Write-Host ""
    Write-Host "Usage:"
    Write-Host "  .\cli.bat settings status"
    Write-Host "  .\cli.bat settings init"
    Write-Host "  .\cli.bat settings master show"
    Write-Host "  .\cli.bat items list --json"
    Write-Host "  .\cli.bat items list --page 2 --page-size 50 --json"
    Write-Host "  .\cli.bat items list --all --json"
    Write-Host "  .\cli.bat items refresh --json"
    Write-Host "  .\cli.bat items download --to C:\TimelineData\windows-codex-downloads"
}

function Get-TfwcLastExitCode {
    $variable = Get-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
    if ($variable -and $null -ne $variable.Value) {
        return [int]$variable.Value
    }
    if ($?) { return 0 }
    return 1
}

function Convert-TfwcHostPathToContainerPath {
    param([Parameter(Mandatory = $true)][string]$HostPath)

    $fullPath = [System.IO.Path]::GetFullPath($HostPath)
    if ($fullPath.Length -ge 3 -and $fullPath[1] -eq ':' -and ($fullPath[2] -eq '\' -or $fullPath[2] -eq '/')) {
        $drive = ([string]$fullPath[0]).ToLowerInvariant()
        $rest = $fullPath.Substring(3).Replace('\', '/')
        return "/mnt/$drive/$rest"
    }
    return $fullPath.Replace('\', '/')
}

function Start-TfwcWorker {
    param(
        [Parameter(Mandatory = $true)][string]$Docker,
        [switch]$ForceRecreate
    )

    $global:LASTEXITCODE = 0
    $upArgs = @("compose", "up", "-d", "--no-build", "--remove-orphans")
    if ($ForceRecreate) {
        $upArgs += "--force-recreate"
    }
    $upArgs += "worker"
    & $Docker @upArgs
    $composeExitCode = Get-TfwcLastExitCode
    if ($composeExitCode -ne 0) {
        Write-Error "TimelineForWindowsCodex worker image is not available or Docker could not start it. Run .\start.bat once, then retry the CLI command."
        exit $composeExitCode
    }
}

function Test-TfwcContainerPathExists {
    param(
        [Parameter(Mandatory = $true)][string]$Docker,
        [Parameter(Mandatory = $true)][string]$ContainerPath
    )

    & $Docker compose exec -T worker test -d $ContainerPath *> $null
    return [bool]$?
}

function Ensure-TfwcConfiguredMount {
    param([Parameter(Mandatory = $true)][string]$Docker)

    $outputRoot = Get-TfwcConfiguredOutputRoot
    if (-not $outputRoot) {
        return
    }

    $containerOutputRoot = Convert-TfwcHostPathToContainerPath -HostPath $outputRoot
    if (Test-TfwcContainerPathExists -Docker $Docker -ContainerPath $containerOutputRoot) {
        return
    }

    Start-TfwcWorker -Docker $Docker -ForceRecreate
    if (Test-TfwcContainerPathExists -Docker $Docker -ContainerPath $containerOutputRoot) {
        return
    }

    throw "Configured outputRoot is not mounted in the Docker worker: $outputRoot -> $containerOutputRoot"
}

function Invoke-TfwcWithFileLock {
    param(
        [Parameter(Mandatory = $true)][string]$LockName,
        [Parameter(Mandatory = $true)][scriptblock]$ScriptBlock
    )

    $generatedDir = Join-Path $repoRoot ".docker"
    New-Item -ItemType Directory -Path $generatedDir -Force | Out-Null
    $lockPath = Join-Path $generatedDir $LockName
    $lockStream = $null
    for ($attempt = 1; $attempt -le 300; $attempt += 1) {
        try {
            $lockStream = [System.IO.File]::Open(
                $lockPath,
                [System.IO.FileMode]::OpenOrCreate,
                [System.IO.FileAccess]::ReadWrite,
                [System.IO.FileShare]::None
            )
            break
        }
        catch [System.IO.IOException] {
            Start-Sleep -Milliseconds 100
        }
    }
    if (-not $lockStream) {
        throw "Timed out waiting for lock: $lockPath"
    }

    try {
        & $ScriptBlock
    }
    finally {
        if ($lockStream) {
            $lockStream.Dispose()
        }
    }
}

if ($null -eq $CliArgs -or $CliArgs.Count -eq 0) {
    Show-TfwcUsage
    exit 0
}

Initialize-TfwcSettingsFile
Initialize-TfwcDockerMountEnvironment
$docker = Get-TfwcDockerCommand
& $docker info *> $null
if (-not $?) {
    throw "Docker Desktop is installed but the Docker engine is not ready."
}

$script:TfwcCliExitCode = 0
Invoke-TfwcWithFileLock -LockName "docker-compose.lock" -ScriptBlock {
    Start-TfwcWorker -Docker $docker
    Ensure-TfwcConfiguredMount -Docker $docker
    & $docker compose exec -T worker python -m timeline_for_windows_codex_worker @CliArgs
    $script:TfwcCliExitCode = Get-TfwcLastExitCode
}
exit $script:TfwcCliExitCode
