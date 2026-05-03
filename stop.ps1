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

$docker = Get-TfwcDockerCommand
$dockerInfo = Invoke-TfwcHiddenProcess -FilePath $docker -Arguments @("info") -SuppressOutput
if ($dockerInfo.ExitCode -ne 0) {
    throw "Docker Desktop is installed but the Docker engine is not ready."
}

$stopResult = Invoke-TfwcHiddenProcess -FilePath $docker -Arguments @("compose", "stop", "worker") -WriteOutput
exit $stopResult.ExitCode
