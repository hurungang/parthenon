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

Write-Host "🛑 Stopping MCP Demo App..." -ForegroundColor Cyan
Write-Host ""

# Find process on port 7001
$processInfo = netstat -ano | Select-String ":7001.*LISTEN"

if (-not $processInfo) {
    Write-Host "✅ No process found on port 7001" -ForegroundColor Green
    Write-Host "MCP Demo App is not running" -ForegroundColor Gray
    exit 0
}

# Extract PID
$pid = ($processInfo.ToString() -split '\s+')[-1]

if ($pid) {
    try {
        Write-Host "Found process PID: $pid" -ForegroundColor Yellow
        Stop-Process -Id $pid -Force -ErrorAction Stop
        Start-Sleep -Seconds 1
        
        # Verify it stopped
        $stillRunning = netstat -ano | Select-String ":7001.*LISTEN"
        if (-not $stillRunning) {
            Write-Host "✅ MCP Demo App stopped successfully" -ForegroundColor Green
        } else {
            Write-Host "⚠️  Process may still be running" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "❌ Failed to stop process: $_" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "❌ Could not determine process ID" -ForegroundColor Red
    exit 1
}
