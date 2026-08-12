#!/usr/bin/env pwsh
# Test script: verify SSL truststore fix in OAuth token exchange
# Run from: c:\Users\rhu\source\personal\coding-workspace\Parthenon

$ErrorActionPreference = "Stop"
$supabaseId = "21ecd54e-f89a-42df-bd70-f3a37b910956"

Write-Host "=== OAuth SSL Fix Verification ===" -ForegroundColor Cyan

# 1. Get auth token
Write-Host "`n[1] Getting Keycloak token..."
$body = "grant_type=password&client_id=parthenon-api-ui&username=admin&password=admin&scope=openid"
$token = (Invoke-RestMethod -Uri "http://localhost:8082/realms/parthenon/protocol/openid-connect/token" -Method POST -ContentType "application/x-www-form-urlencoded" -Body $body).access_token
Write-Host "    Token acquired (length: $($token.Length))" -ForegroundColor Green

$headers = @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" }

# 2. Initiate OAuth authorize
Write-Host "`n[2] Initiating OAuth authorize for Supabase server ($supabaseId)..."
$oaResp = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/mcp/servers/$supabaseId/oauth/authorize" -Method POST -Headers $headers -Body '{}'
$authUrl = $oaResp.authorization_url
# State is embedded in the URL query string, not a top-level field
Add-Type -AssemblyName System.Web
$state = [System.Web.HttpUtility]::ParseQueryString(([Uri]$authUrl).Query)["state"]
Write-Host "    State: $state" -ForegroundColor Green
Write-Host "    Auth URL (first 80): $($authUrl.Substring(0, [Math]::Min(80, $authUrl.Length)))..." -ForegroundColor Green

# 3. Call callback with fake code (triggers token exchange -> SSL path)
Write-Host "`n[3] Calling callback with fake code to trigger token exchange SSL path..."
try {
    $cbResp = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/mcp/oauth/callback?code=fake-ssl-test&state=$state" -Method GET -Headers @{ Authorization = "Bearer $token" }
    Write-Host "    UNEXPECTED SUCCESS: $cbResp" -ForegroundColor Yellow
} catch {
    $errBody = $_.ErrorDetails.Message | ConvertFrom-Json -ErrorAction SilentlyContinue
    $httpCode = $_.Exception.Response.StatusCode.value__
    Write-Host "    HTTP $httpCode (expected failure)" -ForegroundColor Yellow
    Write-Host "    Error detail: $($errBody.detail)" -ForegroundColor Yellow
    if ($errBody.detail -match "Token exchange failed") {
        Write-Host "    -> Token exchange was reached and FAILED at Supabase (fake code rejected)" -ForegroundColor Green
        Write-Host "    -> This means SSL handshake SUCCEEDED (no SSL errors)" -ForegroundColor Green
    } elseif ($errBody.detail -match "Invalid or expired") {
        Write-Host "    -> State expired/invalid - try re-running immediately" -ForegroundColor Red
    } else {
        Write-Host "    -> Detail: $($errBody.detail)" -ForegroundColor Red
    }
}

# 4. Check recent logs for SSL messages
Write-Host "`n[4] Checking backend logs for SSL/truststore messages..."
$logFile = "c:\Users\rhu\source\personal\coding-workspace\Parthenon\backend\logs\otel.log"
$recentLogs = Get-Content $logFile -Tail 50 | Where-Object { $_ -match "truststore|CERTIFICATE_VERIFY|ssl_verify|SSL verification|token exchange" }
if ($recentLogs) {
    foreach ($line in $recentLogs) {
        $color = if ($line -match "ERROR|CERTIFICATE_VERIFY_FAILED") { "Red" } elseif ($line -match "WARN|disabled") { "Yellow" } else { "Green" }
        Write-Host "    $line" -ForegroundColor $color
    }
} else {
    Write-Host "    (No SSL/truststore log entries found in last 50 lines)" -ForegroundColor Gray
}

Write-Host "`n=== Code Verification ===" -ForegroundColor Cyan
$fix = Select-String -Path "backend\app\services\mcp_oauth_service.py" -Pattern "Using truststore for token exchange" -Context 2,2
if ($fix) {
    Write-Host "    Fix confirmed in code at line $($fix.LineNumber)" -ForegroundColor Green
    $fix | Format-List
} else {
    Write-Host "    FIX NOT FOUND in code!" -ForegroundColor Red
}
