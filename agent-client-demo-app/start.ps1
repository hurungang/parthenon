#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Start the Agent Client demo app.

.DESCRIPTION
    Starts the Agent Client demo app using uvicorn on port 7002 (override with $env:PORT).

.EXAMPLE
    .\start.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$port = if ($env:PORT) { [int]$env:PORT } else { 7002 }
$IsWindowsEnv = $IsWindows -or (-not (Test-Path Variable:IsWindows))
$IsMacOSEnv = $IsMacOS

$pythonCmd = $null
$candidates = if ($IsWindowsEnv) { @("python") } else { @("python3.11", "python3") }
foreach ($c in $candidates) {
    try {
        $versionOutput = & $c --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $versionOutput -match 'Python (\d+)\.(\d+)') {
            $major = [int]$matches[1]; $minor = [int]$matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) { $pythonCmd = $c; break }
        }
    } catch {}
}
if (-not $pythonCmd) {
    Write-Host "❌ Python 3.11+ is required but not found" -ForegroundColor Red
    exit 1
}

Write-Host "🚀 Starting Agent Client Demo on port $port..." -ForegroundColor Cyan

if ($IsMacOSEnv) { $existing = lsof -ti :$port 2>$null }
else { $existing = netstat -ano 2>$null | Select-String ":$port.*LISTEN" }
if ($existing) {
    Write-Host "⚠️  Port $port is already in use. Run .\stop.ps1 first." -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path ".venv")) {
    Write-Host "📦 Creating virtual environment…" -ForegroundColor Yellow
    & $pythonCmd -m venv .venv
}
$venvActivate = if ($IsWindowsEnv) { ".\.venv\Scripts\Activate.ps1" } else { ".\.venv\bin\Activate.ps1" }
& $venvActivate
& $pythonCmd -m pip install -q --upgrade pip
& $pythonCmd -m pip install -q -e .

Write-Host "Open http://localhost:$port" -ForegroundColor Green
uvicorn demo_app.main:app --host 0.0.0.0 --port $port --reload
