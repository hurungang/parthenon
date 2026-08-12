#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Start the MCP Demo App locally

.DESCRIPTION
    Starts the MCP Demo App using uvicorn on port 7001.
    Checks prerequisites and provides health verification.

.EXAMPLE
    .\start.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Platform detection
$IsWindowsEnv = $IsWindows -or (-not (Test-Path Variable:IsWindows))
$IsMacOSEnv = $IsMacOS

# Find a Python 3.11+ interpreter
$pythonCmd = $null
$candidates = if ($IsWindowsEnv) { @("python") } else { @("python3.11", "python3") }
foreach ($c in $candidates) {
    try {
        $versionOutput = & $c --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $versionOutput -match 'Python (\d+)\.(\d+)') {
            $major = [int]$matches[1]
            $minor = [int]$matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) {
                $pythonCmd = $c
                break
            }
        }
    } catch {}
}
if (-not $pythonCmd) {
    Write-Host "❌ Python 3.11+ is required but not found" -ForegroundColor Red
    Write-Host "   Install Python 3.11+ from https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

Write-Host "🚀 Starting MCP Demo App..." -ForegroundColor Cyan
Write-Host ""

# Check if already running
Write-Host "Checking if port 7001 is already in use..." -ForegroundColor Yellow
if ($IsMacOSEnv) {
    $existingProcess = lsof -ti :7001 2>$null
} else {
    $existingProcess = netstat -ano 2>$null | Select-String ":7001.*LISTEN"
}
if ($existingProcess) {
    Write-Host "⚠️  Port 7001 is already in use" -ForegroundColor Yellow
    Write-Host "Run .\stop.ps1 first to stop the existing instance" -ForegroundColor Yellow
    exit 1
}

# Check if .env exists
if (-not (Test-Path ".env")) {
    Write-Host "❌ Missing .env file" -ForegroundColor Red
    Write-Host ""
    Write-Host "🚀 Quick Setup:" -ForegroundColor Cyan
    Write-Host "   Run the initialization script to auto-configure Keycloak:" -ForegroundColor Yellow
    Write-Host "   .\init.ps1" -ForegroundColor Green
    Write-Host ""
    Write-Host "📝 Manual Setup:" -ForegroundColor Cyan
    Write-Host "   1. Copy .env.example to .env:" -ForegroundColor Yellow
    Write-Host "      cp .env.example .env" -ForegroundColor Green
    Write-Host "   2. Configure your settings:" -ForegroundColor Yellow
    Write-Host "      - KEYCLOAK_CLIENT_SECRET (get from Keycloak admin)" -ForegroundColor Gray
    Write-Host "      - HUB_API_TOKEN (get from Parthenon backend)" -ForegroundColor Gray
    Write-Host ""
    exit 1
}

# Check if virtual environment exists
if (-not (Test-Path ".venv")) {
    Write-Host "📦 Creating virtual environment..." -ForegroundColor Yellow
    & $pythonCmd -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Failed to create virtual environment" -ForegroundColor Red
        exit 1
    }
}

# Activate virtual environment and install dependencies
Write-Host "📦 Installing dependencies..." -ForegroundColor Yellow
$venvActivate = if ($IsWindowsEnv) { ".\.venv\Scripts\Activate.ps1" } else { ".\.venv\bin\Activate.ps1" }
& $venvActivate
& $pythonCmd -m pip install --upgrade pip -q
& $pythonCmd -m pip install -e .
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to install dependencies" -ForegroundColor Red
    exit 1
}

# Check prerequisites
Write-Host ""
Write-Host "Checking prerequisites..." -ForegroundColor Yellow

# Check Keycloak
try {
    $kc = Invoke-WebRequest -Uri "http://localhost:8082/health/ready" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
    if ($kc.StatusCode -eq 200) {
        Write-Host "  ✅ Keycloak is ready" -ForegroundColor Green
    }
} catch {
    Write-Host "  ⚠️  Keycloak not responding on port 8082" -ForegroundColor Yellow
    Write-Host "     Start it with: docker compose up keycloak -d" -ForegroundColor Gray
}

# Check Backend
try {
    $be = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
    if ($be.StatusCode -eq 200) {
        Write-Host "  ✅ Backend is ready" -ForegroundColor Green
    }
} catch {
    Write-Host "  ⚠️  Backend not responding on port 8000" -ForegroundColor Yellow
    Write-Host "     Start it with: cd backend && $pythonCmd -m uvicorn app.main:app --reload" -ForegroundColor Gray
}

Write-Host ""
Write-Host "Starting MCP Demo App on port 7001..." -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host ""

# Start the server
try {
    uvicorn app.main:app --host 0.0.0.0 --port 7001 --reload
} catch {
    Write-Host ""
    Write-Host "❌ Server stopped" -ForegroundColor Red
    exit 1
}
