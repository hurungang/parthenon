#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Stop the Agent Client demo app.

.DESCRIPTION
    Stops any running instance of the Agent Client demo app on port 7002.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$port = if ($env:PORT) { [int]$env:PORT } else { 7002 }
$IsWindowsEnv = $IsWindows -or (-not (Test-Path Variable:IsWindows))
$IsMacOSEnv = $IsMacOS

Write-Host "🛑 Stopping Agent Client Demo (port $port)..." -ForegroundColor Cyan

if ($IsMacOSEnv) { $pid = lsof -ti :$port 2>$null }
else {
    $processInfo = netstat -ano 2>$null | Select-String ":$port.*LISTEN"
    $pid = if ($processInfo) { ($processInfo.ToString() -split '\s+')[-1] } else { $null }
}

if (-not $pid) {
    Write-Host "✅ Agent Client Demo is not running on port $port" -ForegroundColor Green
    exit 0
}

Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
Write-Host "✅ Agent Client Demo stopped" -ForegroundColor Green
