# Decode JWT to see what's inside
Write-Host "Getting JWT token..." -ForegroundColor Cyan

$tokenResp = Invoke-RestMethod -Uri "http://localhost:8082/realms/parthenon/protocol/openid-connect/token" `
    -Method Post `
    -Body "grant_type=password&client_id=parthenon-api-ui&username=admin&password=admin" `
    -ContentType "application/x-www-form-urlencoded"

$token = $tokenResp.access_token

# Decode JWT (it's base64 encoded)
$parts = $token.Split('.')
$payload = $parts[1]

# Pad base64 string if needed
while ($payload.Length % 4 -ne 0) {
    $payload += '='
}

# Decode
$bytes = [System.Convert]::FromBase64String($payload)
$json = [System.Text.Encoding]::UTF8.GetString($bytes)
$decoded = $json | ConvertFrom-Json

Write-Host "`n=== JWT Payload ===" -ForegroundColor Yellow
Write-Host "sub: $($decoded.sub)"
Write-Host "email: $($decoded.email)"
Write-Host "roles: $($decoded.roles -join ', ')"
Write-Host "realm_access.roles: $($decoded.realm_access.roles -join ', ')"

Write-Host "`n=== Full Payload ===" -ForegroundColor Yellow
$json | ConvertFrom-Json | ConvertTo-Json -Depth 10
