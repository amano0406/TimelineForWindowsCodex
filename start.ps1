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

function Get-TfwcHostSettingsPath {
    $settingsPath = [Environment]::GetEnvironmentVariable("HOST_TFWC_SETTINGS_FILE", "Process")
    if ([string]::IsNullOrWhiteSpace($settingsPath)) {
        $settingsPath = Join-Path $repoRoot "settings.json"
    }
    elseif (-not [System.IO.Path]::IsPathRooted($settingsPath)) {
        $settingsPath = Join-Path $repoRoot $settingsPath
    }
    return [System.IO.Path]::GetFullPath($settingsPath)
}

function Initialize-TfwcSettingsFile {
    $settingsPath = Get-TfwcHostSettingsPath
    if (-not (Test-Path -LiteralPath $settingsPath)) {
        $settingsDir = Split-Path -Parent $settingsPath
        if ($settingsDir -and -not (Test-Path -LiteralPath $settingsDir)) {
            New-Item -ItemType Directory -Path $settingsDir | Out-Null
        }
        Copy-Item -LiteralPath (Join-Path $repoRoot "settings.example.json") -Destination $settingsPath
    }

    $outputRoot = Get-TfwcConfiguredOutputRoot
    if ($outputRoot -and -not (Test-Path -LiteralPath $outputRoot)) {
        New-Item -ItemType Directory -Path $outputRoot | Out-Null
    }
}

function Get-TfwcConfiguredOutputRoot {
    $settingsPath = Get-TfwcHostSettingsPath
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

function Get-TfwcComposeArguments {
    $arguments = [System.Collections.Generic.List[string]]::new()
    $arguments.Add("compose") | Out-Null
    $projectName = [Environment]::GetEnvironmentVariable("COMPOSE_PROJECT_NAME", "Process")
    if (-not [string]::IsNullOrWhiteSpace($projectName)) {
        $arguments.Add("-p") | Out-Null
        $arguments.Add($projectName) | Out-Null
    }
    return $arguments.ToArray()
}

function Get-TfwcLastExitCode {
    $variable = Get-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
    if ($variable -and $null -ne $variable.Value) {
        return [int]$variable.Value
    }
    if ($?) { return 0 }
    return 1
}

function Format-TfwcProcessArgument {
    param([string]$Value)

    if ($null -eq $Value) { return '""' }
    $text = [string]$Value
    if ($text.Length -eq 0) { return '""' }
    if ($text -notmatch '[\s"]') { return $text }

    $builder = [System.Text.StringBuilder]::new()
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $text.ToCharArray()) {
        if ($character -eq '\') { $backslashes += 1; continue }
        if ($character -eq '"') {
            if ($backslashes -gt 0) { [void]$builder.Append(('\' * ($backslashes * 2))); $backslashes = 0 }
            [void]$builder.Append('\"')
            continue
        }
        if ($backslashes -gt 0) { [void]$builder.Append(('\' * $backslashes)); $backslashes = 0 }
        [void]$builder.Append($character)
    }
    if ($backslashes -gt 0) { [void]$builder.Append(('\' * ($backslashes * 2))) }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Invoke-TfwcHiddenProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [switch]$WriteOutput,
        [switch]$SuppressOutput
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = (@($Arguments) | ForEach-Object { Format-TfwcProcessArgument -Value ([string]$_) }) -join " "
    $startInfo.WorkingDirectory = $repoRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $startInfo.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)
    $fileDirectory = Split-Path -Parent $FilePath
    if ($fileDirectory) {
        $currentPath = $startInfo.EnvironmentVariables["PATH"]
        if (-not $currentPath) {
            $currentPath = $env:PATH
        }
        $updatedPath = "$fileDirectory;$currentPath"
        $startInfo.EnvironmentVariables["PATH"] = $updatedPath
        $startInfo.EnvironmentVariables["Path"] = $updatedPath
    }
    $startInfo.EnvironmentVariables["PATHEXT"] = ".COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC;.CPL"

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()

    $stdout = [string]$stdoutTask.Result
    $stderr = [string]$stderrTask.Result
    if ($WriteOutput -and -not $SuppressOutput) {
        if ($stdout.Length -gt 0) { [Console]::Out.Write($stdout) }
        if ($stderr.Length -gt 0) { [Console]::Error.Write($stderr) }
    }

    return [pscustomobject]@{
        ExitCode = [int]$process.ExitCode
        Stdout = $stdout
        Stderr = $stderr
    }
}

Initialize-TfwcSettingsFile
Initialize-TfwcDockerMountEnvironment
$docker = Get-TfwcDockerCommand
$dockerInfo = Invoke-TfwcHiddenProcess -FilePath $docker -Arguments @("info") -SuppressOutput
if ($dockerInfo.ExitCode -ne 0) {
    throw "Docker Desktop is installed but the Docker engine is not ready."
}

Write-Host "Starting TimelineForWindowsCodex worker..."
$global:LASTEXITCODE = 0
$startResult = Invoke-TfwcHiddenProcess -FilePath $docker -Arguments (@(Get-TfwcComposeArguments) + @("up", "-d", "--build", "worker")) -WriteOutput
if ($startResult.ExitCode -ne 0) { throw "docker compose failed." }

Write-Host ""
Write-Host "TimelineForWindowsCodex worker-1 was started."
Write-Host "CLI commands execute inside this persistent Compose service container."
Write-Host ""
Write-Host "CLI examples:"
Write-Host "  .\cli.bat settings status"
Write-Host "  .\cli.bat items list --json"
Write-Host "  .\cli.bat items refresh --json"
Write-Host "  .\cli.bat items download --to C:\TimelineData\windows-codex-downloads"
exit $startResult.ExitCode
