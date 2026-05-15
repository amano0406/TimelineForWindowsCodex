[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
Set-Location $repoRoot
$script:TfwcProductId = "timeline-for-windows-codex"
$script:TfwcDefaultApiPort = 19200

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

function Read-TfwcSettingsJson {
    $settingsPath = Get-TfwcHostSettingsPath
    if (-not (Test-Path -LiteralPath $settingsPath)) {
        return [pscustomobject]@{}
    }
    try {
        $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($null -eq $settings) { return [pscustomobject]@{} }
        return $settings
    }
    catch {
        return [pscustomobject]@{}
    }
}

function ConvertTo-TfwcSafeName {
    param([string]$Value)

    $text = ([string]$Value).Trim().ToLowerInvariant()
    $text = [System.Text.RegularExpressions.Regex]::Replace($text, "[^a-z0-9-]+", "-")
    $text = [System.Text.RegularExpressions.Regex]::Replace($text, "-{2,}", "-").Trim("-")
    return $text
}

function Get-TfwcRuntimeSettings {
    $settings = Read-TfwcSettingsJson
    $runtime = if ($null -ne $settings.PSObject.Properties["runtime"] -and $null -ne $settings.runtime) {
        $settings.runtime
    }
    else {
        [pscustomobject]@{}
    }

    $instanceName = [Environment]::GetEnvironmentVariable("TIMELINE_FOR_WINDOWS_CODEX_INSTANCE_NAME", "Process")
    if ([string]::IsNullOrWhiteSpace($instanceName) -and $null -ne $runtime.PSObject.Properties["instanceName"]) {
        $instanceName = [string]$runtime.instanceName
    }
    $instanceName = ConvertTo-TfwcSafeName -Value $instanceName

    $composeProject = [Environment]::GetEnvironmentVariable("COMPOSE_PROJECT_NAME", "Process")
    if ([string]::IsNullOrWhiteSpace($composeProject) -and -not [string]::IsNullOrWhiteSpace($instanceName)) {
        $composeProject = "$script:TfwcProductId-$instanceName"
    }
    $composeProject = ConvertTo-TfwcSafeName -Value $composeProject

    $apiPortText = [Environment]::GetEnvironmentVariable("TIMELINE_FOR_WINDOWS_CODEX_API_PORT", "Process")
    if ([string]::IsNullOrWhiteSpace($apiPortText) -and $null -ne $runtime.PSObject.Properties["apiPort"]) {
        $apiPortText = [string]$runtime.apiPort
    }
    $apiPort = $script:TfwcDefaultApiPort
    if (-not [int]::TryParse([string]$apiPortText, [ref]$apiPort) -or $apiPort -lt 1 -or $apiPort -gt 65535) {
        $apiPort = $script:TfwcDefaultApiPort
    }

    return [pscustomobject]@{
        InstanceName = $instanceName
        ComposeProject = $composeProject
        ApiPort = $apiPort
    }
}

function Initialize-TfwcRuntimeEnvironment {
    Initialize-TfwcSettingsFile
    $runtime = Get-TfwcRuntimeSettings
    if (-not [string]::IsNullOrWhiteSpace($runtime.InstanceName)) {
        Set-Item -Path "Env:TIMELINE_FOR_WINDOWS_CODEX_INSTANCE_NAME" -Value $runtime.InstanceName
    }
    if (-not [string]::IsNullOrWhiteSpace($runtime.ComposeProject)) {
        Set-Item -Path "Env:COMPOSE_PROJECT_NAME" -Value $runtime.ComposeProject
    }
    Set-Item -Path "Env:TIMELINE_FOR_WINDOWS_CODEX_API_PORT" -Value ([string]$runtime.ApiPort)
    return $runtime
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
    $outputRoot = Get-TfwcConfiguredOutputRoot
    if ($outputRoot) {
        Set-Item -Path "Env:HOST_TFWC_CONFIGURED_OUTPUT_ROOT" -Value $outputRoot
        Set-Item -Path "Env:HOST_TFWC_CONFIGURED_OUTPUT_ROOT_CONTAINER" -Value (Convert-TfwcHostPathToContainerPath -HostPath $outputRoot)
    }
}

function Get-TfwcComposeArguments {
    $arguments = [System.Collections.Generic.List[string]]::new()
    $arguments.Add("compose") | Out-Null
    $runtime = Get-TfwcRuntimeSettings
    $projectName = $runtime.ComposeProject
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

$runtime = Initialize-TfwcRuntimeEnvironment
Initialize-TfwcDockerMountEnvironment
$docker = Get-TfwcDockerCommand
$dockerInfo = Invoke-TfwcHiddenProcess -FilePath $docker -Arguments @("info") -SuppressOutput
if ($dockerInfo.ExitCode -ne 0) {
    throw "Docker Desktop is installed but the Docker engine is not ready."
}

Write-Host "Starting TimelineForWindowsCodex worker..."
Write-Host "Health API: http://localhost:$($runtime.ApiPort)/health"
$global:LASTEXITCODE = 0
$startResult = Invoke-TfwcHiddenProcess -FilePath $docker -Arguments (@(Get-TfwcComposeArguments) + @("up", "-d", "--build", "worker", "health")) -WriteOutput
if ($startResult.ExitCode -ne 0) { throw "docker compose failed." }

Write-Host ""
Write-Host "TimelineForWindowsCodex worker-1 was started."
Write-Host "CLI commands execute inside this persistent Compose service container."
Write-Host "Health check: http://localhost:$($runtime.ApiPort)/health"
Write-Host ""
Write-Host "CLI examples:"
Write-Host "  .\cli.bat settings status"
Write-Host "  .\cli.bat items list --json"
Write-Host "  .\cli.bat items refresh --json"
Write-Host "  .\cli.bat items download --to C:\TimelineData\windows-codex-downloads"
exit $startResult.ExitCode
