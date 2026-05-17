[CmdletBinding()]
param(
    [Alias("SkipCliSmoke")]
    [switch]$SkipApiSmoke,
    [switch]$SkipFidelityAudit,
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

function Invoke-TfwcApiSmoke {
    $manifestPath = Join-Path $repoRoot "timeline-product.json"
    $baseUrl = "http://127.0.0.1:19200"
    if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
        try {
            $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($manifest.api.defaultBaseUrl) {
                $baseUrl = ([string]$manifest.api.defaultBaseUrl).TrimEnd("/")
            }
        }
        catch {
        }
    }

    Write-Host ""
    Write-Host "== local API smoke test =="
    $health = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri "$baseUrl/health"
    if ($health.StatusCode -lt 200 -or $health.StatusCode -ge 300) {
        throw "Health endpoint returned HTTP $($health.StatusCode)."
    }
    if (([string]$health.Content).Trim() -eq "false") {
        throw "Health endpoint returned false."
    }

    $emptyBody = "{}"
    $settings = Invoke-RestMethod -UseBasicParsing -TimeoutSec 30 -Uri "$baseUrl/settings/status" -Method Post -ContentType "application/json" -Body $emptyBody
    if ($null -eq $settings) {
        throw "settings/status returned no payload."
    }

    $items = Invoke-RestMethod -UseBasicParsing -TimeoutSec 30 -Uri "$baseUrl/items/list" -Method Post -ContentType "application/json" -Body '{"page":1,"pageSize":1}'
    if ($null -eq $items) {
        throw "items/list returned no payload."
    }
}

$script:PythonInvocation = Get-TfwcPythonInvocation
$script:PreviousEnvironment = @{}

try {
    Set-TfwcTempEnvironment -Name "PYTHONDONTWRITEBYTECODE" -Value "1"

    if (-not $SkipApiSmoke) {
        Invoke-TfwcApiSmoke
    }

    if (-not $SkipFidelityAudit) {
        Write-Warning "Fidelity audit smoke is retired because worker CLI entrypoints have been removed. Use the local API smoke and worker unit tests instead."
    }

    if (-not $SkipLauncherSmoke) {
        Write-Warning "Launcher smoke is retired because host launchers have been removed. start.bat and stop.bat are covered by manual product startup checks."
    }

    if (-not $SkipDockerSmoke) {
        Write-Warning "Docker Compose smoke is retired because worker CLI entrypoints have been removed. Use start.ps1 plus the local API smoke instead."
    }

    Write-Host ""
    Write-Host "TimelineForWindowsCodex operational checks completed."
}
finally {
    Restore-TfwcEnvironment
}
