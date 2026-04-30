# Complete Permission System Test
Write-Host "=== Permission System End-to-End Test ===" -ForegroundColor Cyan

# Login as admin
Write-Host "`n[1] Login as admin..." -ForegroundColor Yellow
$tokenResp = Invoke-RestMethod -Uri "http://localhost:8082/realms/parthenon/protocol/openid-connect/token" `
    -Method Post -Body "grant_type=password&client_id=parthenon-api-ui&username=admin&password=admin" `
    -ContentType "application/x-www-form-urlencoded"
$adminToken = $tokenResp.access_token
Write-Host "✓ Admin logged in" -ForegroundColor Green

# Test 1: List roles (should succeed)
Write-Host "`n[2] Test: Admin can list roles" -ForegroundColor Yellow
$roles = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/user-roles" `
    -Headers @{Authorization="Bearer $adminToken"}
Write-Host "✓ Success: Found $($roles.Count) role(s)" -ForegroundColor Green
$systemRole = $roles | Where-Object {$_.role_type -eq 'system'}
Write-Host "  System Role: $($systemRole.name) (is_system=$($systemRole.is_system))" -ForegroundColor Magenta

# Test 2: Create a user-defined role (should succeed)
Write-Host "`n[3] Test: Admin can create user-defined role" -ForegroundColor Yellow
try {
    $newRole = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/user-roles" `
        -Method Post `
        -Headers @{Authorization="Bearer $adminToken"; "Content-Type"="application/json"} `
        -Body '{"name":"test_role","description":"Test role for verification"}'
    Write-Host "✓ Success: Created role '$($newRole.name)' (id=$($newRole.id))" -ForegroundColor Green
    $testRoleId = $newRole.id
} catch {
    Write-Host "✗ Failed: $($_.Exception.Message)" -ForegroundColor Red
}

# Test 3: Try to edit system role (should fail with 403)
Write-Host "`n[4] Test: Editing system role should be forbidden" -ForegroundColor Yellow
try {
    $updated = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/user-roles/$($systemRole.id)" `
        -Method Patch `
        -Headers @{Authorization="Bearer $adminToken"; "Content-Type"="application/json"} `
        -Body '{"description":"Trying to modify system role"}'
    Write-Host "✗ FAILED: System role was modified (should have been rejected!)" -ForegroundColor Red
} catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 403) {
        Write-Host "✓ Success: System role modification blocked (403)" -ForegroundColor Green
    } else {
        Write-Host "✗ Unexpected error: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# Test 4: Try to delete system role (should fail with 403)
Write-Host "`n[5] Test: Deleting system role should be forbidden" -ForegroundColor Yellow
try {
    Invoke-RestMethod -Uri "http://localhost:8000/api/v1/user-roles/$($systemRole.id)" `
        -Method Delete `
        -Headers @{Authorization="Bearer $adminToken"}
    Write-Host "✗ FAILED: System role was deleted (should have been rejected!)" -ForegroundColor Red
} catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 403) {
        Write-Host "✓ Success: System role deletion blocked (403)" -ForegroundColor Green
    } else {
        Write-Host "✗ Unexpected error: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# Test 5: Delete user-defined role (should succeed)
Write-Host "`n[6] Test: Admin can delete user-defined role" -ForegroundColor Yellow
try {
    Invoke-RestMethod -Uri "http://localhost:8000/api/v1/user-roles/$testRoleId" `
        -Method Delete `
        -Headers @{Authorization="Bearer $adminToken"}
    Write-Host "✓ Success: User-defined role deleted" -ForegroundColor Green
} catch {
    Write-Host "✗ Failed: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n=== All Tests Complete ===" -ForegroundColor Cyan
