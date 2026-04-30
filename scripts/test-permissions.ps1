# Test permission-based access control
Write-Host "Testing Permission-Based Access Control..." -ForegroundColor Cyan

# Step 1: Login
Write-Host "`n[1] Logging in as admin..." -ForegroundColor Yellow
$tokenResp = Invoke-RestMethod -Uri "http://localhost:8082/realms/parthenon/protocol/openid-connect/token" `
    -Method Post `
    -Body "grant_type=password&client_id=parthenon-api-ui&username=admin&password=admin" `
    -ContentType "application/x-www-form-urlencoded"

$token = $tokenResp.access_token
Write-Host "✓ Got JWT token" -ForegroundColor Green

# Step 2: Test user-roles endpoint
Write-Host "`n[2] Testing /api/v1/user-roles endpoint..." -ForegroundColor Yellow
try {
    $roles = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/user-roles" `
        -Headers @{Authorization="Bearer $token"}
    
    Write-Host "✅ SUCCESS! Accessed roles API" -ForegroundColor Green
    Write-Host "`nFound $($roles.Count) role(s):" -ForegroundColor Cyan
    
    $roles | ForEach-Object {
        $typeLabel = if ($_.is_system) { "[SYSTEM]" } else { "[USER]" }
        $color = if ($_.is_system) { "Magenta" } else { "White" }
        Write-Host "  $typeLabel $($_.name) - $($_.description)" -ForegroundColor $color
    }
    
    # Step 3: Verify system role properties
    $systemRole = $roles | Where-Object { $_.is_system -eq $true }
    if ($systemRole) {
        Write-Host "`n[3] System Role Verification:" -ForegroundColor Yellow
        Write-Host "  ✓ Name: $($systemRole.name)" -ForegroundColor Green
        Write-Host "  ✓ Type: $($systemRole.role_type)" -ForegroundColor Green
        Write-Host "  ✓ is_system: $($systemRole.is_system)" -ForegroundColor Green
    }
    
} catch {
    Write-Host "❌ FAILED: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.ErrorDetails) {
        Write-Host "Details: $($_.ErrorDetails.Message)" -ForegroundColor Red
    }
}

Write-Host "`n✅ Test Complete!" -ForegroundColor Green
