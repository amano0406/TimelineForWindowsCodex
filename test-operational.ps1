[CmdletBinding()]
param(
    [switch]$SkipCliSmoke,
    [switch]$SkipLauncherSmoke,
    [switch]$SkipDockerSmoke,
    [switch]$PreserveOutput
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
Set-Location $repoRoot

function Get-TfwcPythonInvocation {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        return [pscustomobject]@{ FilePath = $python.Source; PrefixArgs = @() }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return [pscustomobject]@{ FilePath = $python.Source; PrefixArgs = @() }
    }

    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        return [pscustomobject]@{ FilePath = $py.Source; PrefixArgs = @("-3") }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return [pscustomobject]@{ FilePath = $py.Source; PrefixArgs = @("-3") }
    }

    throw "Python was not found. Install Python 3 and retry."
}

function Invoke-TfwcPython {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    Write-Host ""
    Write-Host "== $Name =="
    $allArgs = @($script:PythonInvocation.PrefixArgs) + @($Arguments)
    & $script:PythonInvocation.FilePath @allArgs
    $exitCode = if ($null -ne $global:LASTEXITCODE) { [int]$global:LASTEXITCODE } else { 0 }
    if ($exitCode -ne 0) {
        throw "$Name failed with exit code $exitCode."
    }
}

function Set-TfwcTempEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )

    if (-not $script:PreviousEnvironment.ContainsKey($Name)) {
        $script:PreviousEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
    }
    Set-Item -Path "Env:$Name" -Value $Value
}

function Restore-TfwcEnvironment {
    foreach ($name in $script:PreviousEnvironment.Keys) {
        $value = $script:PreviousEnvironment[$name]
        if ($null -eq $value) {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        }
        else {
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

$script:PythonInvocation = Get-TfwcPythonInvocation
$script:PreviousEnvironment = @{}

try {
    Set-TfwcTempEnvironment -Name "PYTHONDONTWRITEBYTECODE" -Value "1"

    if (-not $SkipCliSmoke) {
        Invoke-TfwcPython -Name "cli.ps1 download smoke test" -Arguments @(
            (Join-Path $repoRoot "tests\smoke\run_cli_ps1_download.py")
        )
    }

    if (-not $SkipLauncherSmoke) {
        $launcherArgs = @((Join-Path $repoRoot "tests\smoke\run_windows_launcher_flow.py"))
        if ($PreserveOutput) {
            $launcherArgs += "--preserve-output"
        }
        Invoke-TfwcPython -Name "Windows launcher operational smoke test" -Arguments $launcherArgs
    }

    if (-not $SkipDockerSmoke) {
        $dockerArgs = @(
            (Join-Path $repoRoot "tests\smoke\run_docker_compose_refresh.py"),
            "--source-root",
            (Join-Path $repoRoot "tests\fixtures\codex-home-min"),
            "--source-root",
            (Join-Path $repoRoot "tests\fixtures\archived-root-min"),
            "--runs",
            "2"
        )
        if ($PreserveOutput) {
            $dockerArgs += "--preserve-output"
        }
        Invoke-TfwcPython -Name "Docker Compose production-like smoke test" -Arguments $dockerArgs
    }

    Write-Host ""
    Write-Host "TimelineForWindowsCodex operational checks completed."
}
finally {
    Restore-TfwcEnvironment
}
