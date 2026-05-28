# Check platform_users table
Write-Host "Checking platform_users..." -ForegroundColor Cyan

# Get database password
$dbPass = "parthenon_dev_pwd"  
$connStr = "Host=localhost;Port=5432;Database=parthenon_dev;Username=parthenon_user;Password=$dbPass"

# Load Npgsql (PostgreSQL driver)
Add-Type -Path "C:\Program Files\dotnet\shared\Microsoft.NETCore.App\9.0.1\System.Data.Common.dll" -ErrorAction SilentlyContinue

# Query using psql
$query = @"
SELECT id, email, sub, created_at 
FROM platform_users 
ORDER BY created_at DESC 
LIMIT 10;
"@

Write-Host "`nRecent platform_users:" -ForegroundColor Yellow
docker exec parthenon-db-1 psql -U parthenon_user -d parthenon_dev -c "$query"
