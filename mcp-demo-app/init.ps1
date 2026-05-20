#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Initialize MCP Demo App - Keycloak client setup

.DESCRIPTION
    Idempotent initialization script that:
    - Checks Keycloak connectivity
    - Verifies ai_agents realm exists
    - Creates mcp-demo-app client if it doesn't exist
    - Updates .env with client credentials
    
    Safe to run multiple times - will skip steps that are already complete.

.PARAMETER KeycloakUrl
    Base URL of Keycloak instance (default: http://localhost:8082)

.PARAMETER Realm
    Keycloak realm name (default: ai_agents)

.PARAMETER AdminUser
    Keycloak admin username (default: admin)

.PARAMETER AdminPassword
    Keycloak admin password (default: admin)

.PARAMETER HubApiToken
    Optional Hub API token to write to .env (default: prompts user if not in .env)

.PARAMETER Force
    Force recreation of .env file even if it exists

.EXAMPLE
    .\init.ps1

.EXAMPLE
    .\init.ps1 -KeycloakUrl "http://keycloak:8080" -HubApiToken "my-token"

.EXAMPLE
    .\init.ps1 -Force
#>

[CmdletBinding()]
param(
    [string]$KeycloakUrl = "http://localhost:8082",
    [string]$Realm = "ai_agents",
    [string]$AdminUser = "admin",
    [string]$AdminPassword = "admin",
    [string]$HubApiToken = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host "🚀 Initializing MCP Demo App" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
Write-Host ""

# ── Step 1: Check Keycloak availability ──────────────────────────────────────
Write-Host "[1/6] Checking Keycloak availability..." -ForegroundColor Yellow
try {
    $health = Invoke-WebRequest -Uri "$KeycloakUrl/health/ready" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    if ($health.StatusCode -eq 200) {
        Write-Host "      ✅ Keycloak is ready at $KeycloakUrl" -ForegroundColor Green
    }
} catch {
    Write-Host "      ❌ Keycloak is not responding at $KeycloakUrl" -ForegroundColor Red
    Write-Host "      💡 Start Keycloak with: docker compose up keycloak -d" -ForegroundColor Gray
    exit 1
}

# ── Step 2: Verify realm exists ──────────────────────────────────────────────
Write-Host "[2/6] Verifying realm '$Realm'..." -ForegroundColor Yellow
try {
    $realmCheck = Invoke-RestMethod -Uri "$KeycloakUrl/realms/$Realm" -ErrorAction Stop
    Write-Host "      ✅ Realm '$Realm' exists" -ForegroundColor Green
} catch {
    Write-Host "      ❌ Realm '$Realm' not found" -ForegroundColor Red
    Write-Host "      💡 Create the ai_agents realm in Keycloak admin console first" -ForegroundColor Gray
    exit 1
}

# ── Step 3: Authenticate as admin ────────────────────────────────────────────
Write-Host "[3/6] Authenticating as Keycloak admin..." -ForegroundColor Yellow
try {
    $tokenResponse = Invoke-RestMethod -Uri "$KeycloakUrl/realms/master/protocol/openid-connect/token" `
        -Method POST `
        -ContentType "application/x-www-form-urlencoded" `
        -Body "grant_type=password&client_id=admin-cli&username=$AdminUser&password=$AdminPassword" `
        -ErrorAction Stop
    
    $adminToken = $tokenResponse.access_token
    Write-Host "      ✅ Admin authentication successful" -ForegroundColor Green
} catch {
    Write-Host "      ❌ Admin authentication failed" -ForegroundColor Red
    Write-Host "      💡 Check admin credentials (default: admin/admin)" -ForegroundColor Gray
    Write-Host "      Error: $_" -ForegroundColor DarkGray
    exit 1
}

$headers = @{
    Authorization = "Bearer $adminToken"
    "Content-Type" = "application/json"
}

# ── Step 4: Check/Create client ──────────────────────────────────────────────
Write-Host "[4/6] Checking mcp-demo-app client..." -ForegroundColor Yellow

$clientCreated = $false
try {
    $existingClients = Invoke-RestMethod -Uri "$KeycloakUrl/admin/realms/$Realm/clients?clientId=mcp-demo-app" `
        -Headers $headers `
        -ErrorAction Stop
    
    if ($existingClients.Count -gt 0) {
        Write-Host "      ✅ Client 'mcp-demo-app' already exists" -ForegroundColor Green
        $clientUUID = $existingClients[0].id
    } else {
        Write-Host "      ⚙️  Creating client 'mcp-demo-app'..." -ForegroundColor Cyan
        
        $clientConfig = @{
            clientId = "mcp-demo-app"
            name = "MCP Demo App"
            description = "Demo MCP server for agent identity propagation"
            enabled = $true
            serviceAccountsEnabled = $true
            clientAuthenticatorType = "client-secret"
            standardFlowEnabled = $false
            directAccessGrantsEnabled = $false
            publicClient = $false
            protocol = "openid-connect"
            attributes = @{
                "client.secret.creation.time" = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds().ToString()
            }
        } | ConvertTo-Json -Depth 10
        
        try {
            Invoke-RestMethod -Uri "$KeycloakUrl/admin/realms/$Realm/clients" `
                -Method POST `
                -Headers $headers `
                -Body $clientConfig `
                -ErrorAction Stop | Out-Null
            
            Write-Host "      ✅ Client created successfully" -ForegroundColor Green
            $clientCreated = $true
            
            # Retrieve the newly created client's UUID
            Start-Sleep -Milliseconds 500  # Brief pause to ensure client is fully created
            $existingClients = Invoke-RestMethod -Uri "$KeycloakUrl/admin/realms/$Realm/clients?clientId=mcp-demo-app" `
                -Headers $headers `
                -ErrorAction Stop
            $clientUUID = $existingClients[0].id
        } catch {
            Write-Host "      ❌ Failed to create client" -ForegroundColor Red
            Write-Host "      Error: $_" -ForegroundColor DarkGray
            exit 1
        }
    }
} catch {
    Write-Host "      ❌ Failed to query clients" -ForegroundColor Red
    Write-Host "      Error: $_" -ForegroundColor DarkGray
    exit 1
}

# ── Step 5: Retrieve client secret ───────────────────────────────────────────
Write-Host "[5/6] Retrieving client secret..." -ForegroundColor Yellow
try {
    $secretResponse = Invoke-RestMethod -Uri "$KeycloakUrl/admin/realms/$Realm/clients/$clientUUID/client-secret" `
        -Headers $headers `
        -ErrorAction Stop
    
    $clientSecret = $secretResponse.value
    Write-Host "      ✅ Client secret retrieved" -ForegroundColor Green
} catch {
    Write-Host "      ❌ Failed to retrieve client secret" -ForegroundColor Red
    Write-Host "      Error: $_" -ForegroundColor DarkGray
    exit 1
}

# ── Step 6: Update .env file ─────────────────────────────────────────────────
Write-Host "[6/6] Updating configuration..." -ForegroundColor Yellow

$envExists = Test-Path ".env"
$shouldUpdateEnv = $Force -or -not $envExists -or $clientCreated

if ($shouldUpdateEnv) {
    # Read existing HUB_API_TOKEN if .env exists
    if ($envExists -and -not $HubApiToken) {
        try {
            $existingContent = Get-Content ".env" -Raw -ErrorAction SilentlyContinue
            if ($existingContent -match 'HUB_API_TOKEN=(.+)') {
                $existingToken = $matches[1].Trim()
                if ($existingToken -and $existingToken -ne "demo-token-change-me" -and $existingToken -ne "change-me") {
                    $HubApiToken = $existingToken
                    Write-Host "      📋 Preserving existing HUB_API_TOKEN" -ForegroundColor Gray
                }
            }
        } catch {
            # Silently continue if we can't read existing token
        }
    }
    
    # Prompt for HUB_API_TOKEN if still not set
    if (-not $HubApiToken) {
        Write-Host ""
        Write-Host "      ⚠️  HUB_API_TOKEN not set" -ForegroundColor Yellow
        Write-Host "      You'll need to update .env with a valid Hub API token before starting the app." -ForegroundColor Gray
        $HubApiToken = "demo-token-change-me"
    }

    $envContent = @"
# ── Keycloak Configuration ─────────────────────────────────────────────────
# Base URL of the Keycloak instance (no trailing slash)
KEYCLOAK_URL=$KeycloakUrl

# Name of the Keycloak realm that issues agent identities
KEYCLOAK_REALM=$Realm

# Client ID registered in the ai_agents realm for this demo app
KEYCLOAK_CLIENT_ID=mcp-demo-app

# Client secret for the above client (keep secret, do not commit)
KEYCLOAK_CLIENT_SECRET=$clientSecret

# ── Parthenon MCP Hub ──────────────────────────────────────────────────────
# Base URL of the Parthenon backend (no trailing slash)
HUB_BASE_URL=http://localhost:8000

# Bearer token used when calling Hub registration APIs
# In compose this can be a service-account token or a static dev token
HUB_API_TOKEN=$HubApiToken

# ── This App ───────────────────────────────────────────────────────────────
# Publicly reachable base URL of this service (used when registering with Hub)
# In docker-compose this should be the internal service name, e.g. http://mcp-demo-app:7001
APP_BASE_URL=http://localhost:7001

# Port to bind on
APP_PORT=7001

# MCP server slug registered with the Hub (must be unique)
APP_SLUG=demo
"@

    try {
        Set-Content -Path ".env" -Value $envContent -ErrorAction Stop
        if ($envExists) {
            Write-Host "      ✅ .env file updated" -ForegroundColor Green
        } else {
            Write-Host "      ✅ .env file created" -ForegroundColor Green
        }
    } catch {
        Write-Host "      ❌ Failed to write .env file" -ForegroundColor Red
        Write-Host "      Error: $_" -ForegroundColor DarkGray
        exit 1
    }
} else {
    Write-Host "      ⏭️  .env already configured (use -Force to regenerate)" -ForegroundColor Gray
}

# ── Summary ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
Write-Host "✅ Initialization complete!" -ForegroundColor Green
Write-Host ""

if ($clientCreated) {
    Write-Host "📝 New client created:" -ForegroundColor Cyan
    Write-Host "   Client ID:     mcp-demo-app" -ForegroundColor Gray
    Write-Host "   Client Secret: $clientSecret" -ForegroundColor Gray
    Write-Host ""
}

if ($HubApiToken -eq "demo-token-change-me") {
    Write-Host "⚠️  Next steps:" -ForegroundColor Yellow
    Write-Host "   1. Edit .env and set HUB_API_TOKEN to a valid token from the Parthenon backend" -ForegroundColor Gray
    Write-Host "   2. Run .\start.ps1 to start the MCP Demo App" -ForegroundColor Gray
} else {
    Write-Host "✅ Ready to start!" -ForegroundColor Green
    Write-Host "   Run: .\start.ps1" -ForegroundColor Gray
}
Write-Host ""
