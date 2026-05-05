# Test MCP initialization with Supabase
# Get the OAuth token from the session and test initialize

# Get auth token
$body = "grant_type=password&client_id=parthenon-api-ui&username=admin&password=admin&scope=openid"
$token = (Invoke-RestMethod -Uri "http://localhost:8082/realms/parthenon/protocol/openid-connect/token" -Method POST -ContentType "application/x-www-form-urlencoded" -Body $body).access_token
$h = @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" }

# Get the Supabase server and session
Write-Host "Fetching Supabase server..."
$servers = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/mcp/servers" -Method GET -Headers $h
$supabaseServer = $servers | Where-Object { $_.name -like "*supabase*" }

if (-not $supabaseServer) {
    Write-Host "ERROR: No Supabase server found" -ForegroundColor Red
    exit 1
}

Write-Host "Server ID: $($supabaseServer.id)"
Write-Host "Base URL: $($supabaseServer.base_url)"

# Get the OAuth session
Write-Host "`nFetching OAuth session..."
$sessions = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/mcp/servers/$($supabaseServer.id)/sessions" -Method GET -Headers $h
$oauthSession = $sessions | Where-Object { $_.auth_type -eq "oauth2" } | Select-Object -First 1

if (-not $oauthSession) {
    Write-Host "ERROR: No OAuth session found" -ForegroundColor Red
    exit 1
}

Write-Host "Session ID: $($oauthSession.id)"
Write-Host "Session Name: $($oauthSession.name)"
Write-Host "Created: $($oauthSession.created_at)"

# Now trigger the sync to see detailed logs
Write-Host "`nTriggering sync..."
Write-Host "Check backend logs for detailed error information"

try {
    $result = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/mcp/servers/$($supabaseServer.id)/sync" -Method POST -Headers $h
    Write-Host "`n✅ SUCCESS!" -ForegroundColor Green
    $result | ConvertTo-Json
} catch {
    Write-Host "`n❌ FAILED" -ForegroundColor Red
    Write-Host $_.Exception.Message
    if ($_.ErrorDetails.Message) {
        Write-Host $_.ErrorDetails.Message
    }
}
