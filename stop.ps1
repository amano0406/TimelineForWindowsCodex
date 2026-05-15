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

function Get-TfwcLastExitCode {
    $variable = Get-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
    if ($variable -and $null -ne $variable.Value) {
        return [int]$variable.Value
    }
    if ($?) { return 0 }
    return 1
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

$runtime = Initialize-TfwcRuntimeEnvironment
$docker = Get-TfwcDockerCommand
$dockerInfo = Invoke-TfwcHiddenProcess -FilePath $docker -Arguments @("info") -SuppressOutput
if ($dockerInfo.ExitCode -ne 0) {
    throw "Docker Desktop is installed but the Docker engine is not ready."
}

$stopResult = Invoke-TfwcHiddenProcess -FilePath $docker -Arguments (@(Get-TfwcComposeArguments) + @("stop", "worker", "health")) -WriteOutput
exit $stopResult.ExitCode
