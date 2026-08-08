#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Stop the MCP Demo App

.DESCRIPTION
    Stops any running instance of the MCP Demo App on port 7001.

.EXAMPLE
    .\stop.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

# Platform detection
$IsWindowsEnv = $IsWindows -or (-not (Test-Path Variable:IsWindows))
$IsMacOSEnv = $IsMacOS

Write-Host "🛑 Stopping MCP Demo App..." -ForegroundColor Cyan
Write-Host ""

# Find process on port 7001
if ($IsMacOSEnv) {
    $pid = lsof -ti :7001 2>$null
} else {
    $processInfo = netstat -ano 2>$null | Select-String ":7001.*LISTEN"
    $pid = if ($processInfo) { ($processInfo.ToString() -split '\s+')[-1] } else { $null }
}

if (-not $pid) {
    Write-Host "✅ No process found on port 7001" -ForegroundColor Green
    Write-Host "MCP Demo App is not running" -ForegroundColor Gray
    exit 0
}

try {
    Write-Host "Found process PID: $pid" -ForegroundColor Yellow
    Stop-Process -Id $pid -Force -ErrorAction Stop
    Start-Sleep -Seconds 1
    
    # Verify it stopped
    if ($IsMacOSEnv) {
        $stillRunning = lsof -ti :7001 2>$null
    } else {
        $stillRunning = netstat -ano 2>$null | Select-String ":7001.*LISTEN"
    }
    if (-not $stillRunning) {
        Write-Host "✅ MCP Demo App stopped successfully" -ForegroundColor Green
    } else {
        Write-Host "⚠️  Process may still be running" -ForegroundColor Yellow
    }
} catch {
    Write-Host "❌ Failed to stop process: $_" -ForegroundColor Red
    exit 1
}
