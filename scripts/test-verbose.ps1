# Test with verbose output
$url = "http://localhost:8000/api/v1/user-roles"

Write-Host "Login..." -ForegroundColor Cyan
$tokenResp = Invoke-RestMethod -Uri "http://localhost:8082/realms/parthenon/protocol/openid-connect/token" `
    -Method Post `
    -Body "grant_type=password&client_id=parthenon-api-ui&username=admin&password=admin" `
    -ContentType "application/x-www-form-urlencoded"

$token = $tokenResp.access_token
Write-Host "✓ Got token" -ForegroundColor Green

Write-Host "`nTesting URL: $url" -ForegroundColor Yellow
Write-Host "With Authorization: Bearer ${token.Substring(0, 20)}..." -ForegroundColor Yellow

try {
    $response = Invoke-WebRequest -Uri $url `
        -Headers @{Authorization="Bearer $token"} `
        -Verbose
    Write-Host "`n✅ Success: $($response.StatusCode)" -ForegroundColor Green
    $response.Content
} catch {
    Write-Host "`n❌ Error: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Status: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
    Write-Host "Response Body:" -ForegroundColor Yellow
    $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
    $reader.BaseStream.Position = 0
    $reader.ReadToEnd()
}
