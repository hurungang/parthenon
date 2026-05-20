#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Setup Keycloak client for MCP Demo App

.DESCRIPTION
    Creates the mcp-demo-app client in Keycloak ai_agents realm,
    retrieves the client secret, and updates the .env file.

.EXAMPLE
    .\setup-keycloak.ps1
#>

[CmdletBinding()]
param(
    [string]$KeycloakUrl = "http://localhost:8082",
    [string]$Realm = "ai_agents",
    [string]$AdminUser = "admin",
    [string]$AdminPassword = "admin"
)

$ErrorActionPreference = "Stop"

Write-Host "🔧 Setting up Keycloak client for MCP Demo App" -ForegroundColor Cyan
Write-Host ""

# Step 1: Check if Keycloak is reachable
Write-Host "Checking Keycloak availability..." -ForegroundColor Yellow
try {
    $health = Invoke-WebRequest -Uri "$KeycloakUrl/health/ready" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    if ($health.StatusCode -eq 200) {
        Write-Host "  ✅ Keycloak is ready" -ForegroundColor Green
    }
} catch {
    Write-Host "  ❌ Keycloak is not responding on $KeycloakUrl" -ForegroundColor Red
    Write-Host "     Make sure Keycloak is running: docker compose up keycloak -d" -ForegroundColor Yellow
    exit 1
}

# Step 2: Check if ai_agents realm exists
Write-Host "Checking if '$Realm' realm exists..." -ForegroundColor Yellow
try {
    $realmCheck = Invoke-RestMethod -Uri "$KeycloakUrl/realms/$Realm" -ErrorAction Stop
    Write-Host "  ✅ Realm '$Realm' exists" -ForegroundColor Green
} catch {
    Write-Host "  ❌ Realm '$Realm' does not exist" -ForegroundColor Red
    Write-Host "     Please create the ai_agents realm first" -ForegroundColor Yellow
    exit 1
}

# Step 3: Get admin token
Write-Host "Authenticating as Keycloak admin..." -ForegroundColor Yellow
try {
    $tokenResponse = Invoke-RestMethod -Uri "$KeycloakUrl/realms/master/protocol/openid-connect/token" `
        -Method POST `
        -ContentType "application/x-www-form-urlencoded" `
        -Body "grant_type=password&client_id=admin-cli&username=$AdminUser&password=$AdminPassword" `
        -ErrorAction Stop
    
    $adminToken = $tokenResponse.access_token
    Write-Host "  ✅ Admin authentication successful" -ForegroundColor Green
} catch {
    Write-Host "  ❌ Failed to authenticate as admin" -ForegroundColor Red
    Write-Host "     Error: $_" -ForegroundColor Yellow
    exit 1
}

# Step 4: Check if client already exists
Write-Host "Checking if mcp-demo-app client exists..." -ForegroundColor Yellow
$headers = @{
    Authorization = "Bearer $adminToken"
    "Content-Type" = "application/json"
}

try {
    $existingClients = Invoke-RestMethod -Uri "$KeycloakUrl/admin/realms/$Realm/clients?clientId=mcp-demo-app" `
        -Headers $headers `
        -ErrorAction Stop
    
    if ($existingClients.Count -gt 0) {
        Write-Host "  ✅ Client already exists" -ForegroundColor Green
        $clientUUID = $existingClients[0].id
    } else {
        # Step 5: Create the client
        Write-Host "Creating mcp-demo-app client..." -ForegroundColor Yellow
        
        $clientConfig = @{
            clientId = "mcp-demo-app"
            name = "MCP Demo App"
            description = "Demo MCP server for validating agent identity propagation"
            enabled = $true
            serviceAccountsEnabled = $true
            clientAuthenticatorType = "client-secret"
            standardFlowEnabled = $false
            directAccessGrantsEnabled = $false
            publicClient = $false
            protocol = "openid-connect"
        } | ConvertTo-Json -Depth 10
        
        try {
            Invoke-RestMethod -Uri "$KeycloakUrl/admin/realms/$Realm/clients" `
                -Method POST `
                -Headers $headers `
                -Body $clientConfig `
                -ErrorAction Stop
            
            Write-Host "  ✅ Client created successfully" -ForegroundColor Green
            
            # Get the newly created client's UUID
            $existingClients = Invoke-RestMethod -Uri "$KeycloakUrl/admin/realms/$Realm/clients?clientId=mcp-demo-app" `
                -Headers $headers `
                -ErrorAction Stop
            $clientUUID = $existingClients[0].id
        } catch {
            Write-Host "  ❌ Failed to create client" -ForegroundColor Red
            Write-Host "     Error: $_" -ForegroundColor Yellow
            exit 1
        }
    }
} catch {
    Write-Host "  ❌ Failed to check for existing client" -ForegroundColor Red
    Write-Host "     Error: $_" -ForegroundColor Yellow
    exit 1
}

# Step 6: Get the client secret
Write-Host "Retrieving client secret..." -ForegroundColor Yellow
try {
    $secretResponse = Invoke-RestMethod -Uri "$KeycloakUrl/admin/realms/$Realm/clients/$clientUUID/client-secret" `
        -Headers $headers `
        -ErrorAction Stop
    
    $clientSecret = $secretResponse.value
    Write-Host "  ✅ Client secret retrieved" -ForegroundColor Green
} catch {
    Write-Host "  ❌ Failed to retrieve client secret" -ForegroundColor Red
    Write-Host "     Error: $_" -ForegroundColor Yellow
    exit 1
}

# Step 7: Update .env file
Write-Host "Updating .env file..." -ForegroundColor Yellow

$envContent = @"
# Keycloak Configuration
KEYCLOAK_URL=$KeycloakUrl
KEYCLOAK_REALM=$Realm
KEYCLOAK_CLIENT_ID=mcp-demo-app
KEYCLOAK_CLIENT_SECRET=$clientSecret

# Parthenon MCP Hub
HUB_BASE_URL=http://localhost:8000
HUB_API_TOKEN=demo-token-change-me

# This App
APP_BASE_URL=http://localhost:7001
APP_PORT=7001
APP_SLUG=demo
"@

try {
    Set-Content -Path ".env" -Value $envContent -ErrorAction Stop
    Write-Host "  ✅ .env file updated" -ForegroundColor Green
} catch {
    Write-Host "  ❌ Failed to update .env file" -ForegroundColor Red
    Write-Host "     Error: $_" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "✅ Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Edit .env and set HUB_API_TOKEN to a valid token from the Parthenon backend" -ForegroundColor Yellow
Write-Host "  2. Run .\start.ps1 to start the MCP Demo App" -ForegroundColor Yellow
Write-Host ""
Write-Host "Client credentials:" -ForegroundColor Gray
Write-Host "  Client ID: mcp-demo-app" -ForegroundColor Gray
Write-Host "  Client Secret: $clientSecret" -ForegroundColor Gray
