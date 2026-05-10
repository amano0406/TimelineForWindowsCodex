[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [Parameter()]
    [string]$OutputDir = ".\release"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Normalize-Version {
    param([string]$Value)

    $trimmed = $Value.Trim()
    if ($trimmed.StartsWith("v")) {
        $trimmed = $trimmed.Substring(1)
    }

    if ($trimmed -notmatch '^\d+\.\d+\.\d+$') {
        throw "Version must look like 0.3.0 or v0.3.0."
    }

    return @{
        SemVer = $trimmed
        Tag = "v$trimmed"
    }
}

function Resolve-GitCommand {
    $command = Get-Command git -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:GIT_EXE)) {
        $candidates += $env:GIT_EXE
    }

    $candidates += @(
        "C:\Program Files\Git\cmd\git.exe",
        "C:\Program Files\Git\bin\git.exe",
        "C:\Program Files (x86)\Git\cmd\git.exe",
        "C:\Program Files (x86)\Git\bin\git.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    throw "Git for Windows was not found. Install Git or set GIT_EXE to git.exe."
}

function Invoke-Git {
    param([string[]]$Arguments)

    $global:LASTEXITCODE = 0
    $output = & $script:GitCommand @Arguments 2>&1
    $exitCode = $global:LASTEXITCODE
    if ($exitCode -ne 0) {
        $joined = $Arguments -join " "
        throw "git $joined failed: $output"
    }

    return $output
}

function Resolve-FullPath {
    param(
        [string]$BasePath,
        [string]$PathValue
    )

    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $PathValue))
}

$normalized = Normalize-Version -Value $Version
$semVer = $normalized.SemVer
$tag = $normalized.Tag

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
$repoName = Split-Path -Leaf $repoRoot
$script:GitCommand = Resolve-GitCommand

Invoke-Git -Arguments @("-C", $repoRoot, "rev-parse", "--is-inside-work-tree") | Out-Null
Invoke-Git -Arguments @("-C", $repoRoot, "rev-parse", "--verify", "refs/tags/$tag^{commit}") | Out-Null

$outputRootBase = Resolve-FullPath -BasePath $repoRoot -PathValue $OutputDir
$outputRoot = Join-Path $outputRootBase $tag
$zipName = "$repoName-windows-local.zip"
$zipPath = Join-Path $outputRoot $zipName
$checksumPath = Join-Path $outputRoot "SHA256SUMS.txt"
$prefix = "$repoName-$tag/"

if (-not (Test-Path -LiteralPath $outputRoot)) {
    New-Item -ItemType Directory -Path $outputRoot | Out-Null
}

if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

if (Test-Path -LiteralPath $checksumPath) {
    Remove-Item -LiteralPath $checksumPath -Force
}

Invoke-Git -Arguments @(
    "-C",
    $repoRoot,
    "archive",
    "--format=zip",
    "--output=$zipPath",
    "--prefix=$prefix",
    $tag
) | Out-Null

$zipCreated = $false
for ($index = 0; $index -lt 20; $index++) {
    if (Test-Path -LiteralPath $zipPath) {
        $zipCreated = $true
        break
    }

    Start-Sleep -Milliseconds 100
}

if (-not $zipCreated) {
    throw "Release ZIP was not created: $zipPath"
}

$hashResult = $null
for ($index = 0; $index -lt 50; $index++) {
    try {
        $hashResult = Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
        break
    }
    catch {
        Start-Sleep -Milliseconds 100
    }
}

if ($null -eq $hashResult) {
    throw "Release ZIP could not be read for SHA256: $zipPath"
}

$hash = $hashResult.Hash.ToLowerInvariant()
Set-Content -LiteralPath $checksumPath -Value "$hash  $zipName" -Encoding ASCII

Write-Host "Release bundle created:"
Write-Host "  Version: $semVer"
Write-Host "  Tag:     $tag"
Write-Host "  ZIP:     $zipPath"
Write-Host "  SHA256:  $checksumPath"
