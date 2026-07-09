<#
.SYNOPSIS
    Parthenon Application Manager - Start, stop, and manage the Parthenon stack

.DESCRIPTION
    Standalone script to manage the Parthenon application stack.
    Controls infrastructure (Keycloak, PostgreSQL, Redis), backend API, and frontend dev server.

.PARAMETER Action
    Action to perform: start, stop, restart, status, logs

.PARAMETER Services
    Comma-separated list of services: infra, control-center, agent-runtime, communication-hub, frontend, backend, all (default: all)
    - backend: All services except infrastructure (control-center, agent-runtime, communication-hub, frontend)
    - all: All services including infrastructure
    For logs command: control-center, agent-runtime, communication-hub, all

.PARAMETER Force
    Force restart without confirmation if service is already running

.PARAMETER Lines
    Number of log lines to display (default: 50, used with logs command)

.PARAMETER Follow
    Follow log output in real-time (used with logs command)

.PARAMETER LogLevel
    Set the log level for backend services: DEBUG, INFO (default), WARNING, ERROR, CRITICAL

.EXAMPLE
    .\parthenon.ps1 start
    Start all services

.EXAMPLE
    .\parthenon.ps1 start -Services backend -RunSetup
    Run setup then start all services except infrastructure (assumes infra is running)

.EXAMPLE
    .\parthenon.ps1 start -Services control-center,frontend
    Start only Control Center and frontend

.EXAMPLE
    .\parthenon.ps1 stop -Services backend
    Stop only the backend

.EXAMPLE
    .\parthenon.ps1 restart -Services all -Force
    Force restart all services without confirmation

.EXAMPLE
    .\parthenon.ps1 status
    Show status of all services

.EXAMPLE
    .\parthenon.ps1 logs -Services control-center
    View Control Center logs (last 50 lines)

.EXAMPLE
    .\parthenon.ps1 logs -Services all -Lines 100
    View logs from all backend services (last 100 lines)

.EXAMPLE
    .\parthenon.ps1 logs -Services agent-runtime -Follow
    Follow Agent Runtime logs in real-time

.EXAMPLE
    .\parthenon.ps1 start -LogLevel DEBUG
    Start all services with DEBUG-level logging

.EXAMPLE
    .\parthenon.ps1 init
    Initialize local development environment (Keycloak realm, admin user, database)
#>

[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [ValidateSet('start', 'stop', 'restart', 'status', 'logs', 'init')]
    [string]$Action = 'status',
    
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$Services = 'all',
    
    [Parameter()]
    [switch]$Force,
    
    [Parameter()]
    [int]$Lines = 50,
    
    [Parameter()]
    [switch]$Follow,

    [Parameter()]
    [ValidateSet('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')]
    [string]$LogLevel = 'INFO',

    [Parameter()]
    [switch]$RunSetup
)

# Script configuration
$Script:ProjectRoot = $PSScriptRoot
$Script:BackendDir = Join-Path $ProjectRoot "backend"
$Script:FrontendDir = Join-Path $ProjectRoot "frontend"

# Set SSL CA bundle env vars so every spawned service process inherits them.
# Must be called before any Start-Process for backend services.
function Set-SslCaBundle {
    $caBundlePath = Join-Path $Script:ProjectRoot "ca-bundle.crt"
    $cacertPath   = Join-Path $Script:ProjectRoot "cacert.pem"
    if (Test-Path -Path $caBundlePath) {
        Write-Host "  SSL: using ca-bundle.crt" -ForegroundColor Cyan
        $env:REQUESTS_CA_BUNDLE = $caBundlePath
        $env:SSL_CERT_FILE      = $caBundlePath
        $env:CURL_CA_BUNDLE     = $caBundlePath
    } elseif (Test-Path -Path $cacertPath) {
        Write-Host "  SSL: using cacert.pem" -ForegroundColor Cyan
        $env:REQUESTS_CA_BUNDLE = $cacertPath
        $env:SSL_CERT_FILE      = $cacertPath
        $env:CURL_CA_BUNDLE     = $cacertPath
    } elseif ($env:REQUESTS_CA_BUNDLE) {
        Write-Host "  SSL: using existing REQUESTS_CA_BUNDLE=$env:REQUESTS_CA_BUNDLE" -ForegroundColor Cyan
        $env:SSL_CERT_FILE  = $env:REQUESTS_CA_BUNDLE
        $env:CURL_CA_BUNDLE = $env:REQUESTS_CA_BUNDLE
    } else {
        Write-Host "  SSL: no CA bundle found — corporate firewall certs may cause SSL errors" -ForegroundColor Yellow
        Write-Host "       Copy ca-bundle.crt to the project root or set REQUESTS_CA_BUNDLE" -ForegroundColor DarkYellow
    }
}

# Service definitions
$Script:ServiceConfig = @{
    infra = @{
        Name = "Infrastructure (Docker)"
        Port = 5432  # Postgres port as indicator
        CheckCommand = { (docker ps --filter "name=parthenon-postgres" --format "{{.Names}}") -ne $null }
        StartCommand = { 
            Write-Host "Starting infrastructure containers (PostgreSQL, Redis, Keycloak, OTEL)..." -ForegroundColor Cyan
            docker compose -f docker-compose-infra.yml up -d
            Start-Sleep -Seconds 5
            
            # Wait for Keycloak to be healthy
            Write-Host "Waiting for Keycloak to be healthy (max 90s)..." -ForegroundColor Cyan
            $elapsed = 0
            do {
                Start-Sleep -Seconds 5
                $elapsed += 5
                $status = docker inspect parthenon-keycloak --format '{{.State.Health.Status}}' 2>$null
                Write-Host "  ${elapsed}s: Keycloak status = $status"
            } while ($status -ne "healthy" -and $elapsed -lt 90)
            
            if ($status -eq "healthy") {
                Write-Host "✅ Infrastructure is ready" -ForegroundColor Green
            } else {
                Write-Host "⚠️ Keycloak did not become healthy within 90s" -ForegroundColor Yellow
            }
        }
        StopCommand = {
            Write-Host "Stopping infrastructure containers..." -ForegroundColor Cyan
            docker compose -f docker-compose-infra.yml stop
        }
    }
    
    'control-center' = @{
        Name = "Control Center"
        Port = 8000
        HealthUrl = "http://localhost:8000/health"
        LogFile = "backend\logs\control-center.log"
        CheckCommand = { (netstat -ano | Select-String ":8000 .*LISTEN") -ne $null }
        StartCommand = {
            Write-Host "Starting Control Center (port 8000)..." -ForegroundColor Cyan
            $startScript = Join-Path $Script:ProjectRoot "start-service.ps1"
            $logPath = Join-Path $Script:ProjectRoot "backend\logs\control-center.log"

            # Start using helper script
            Start-Process -FilePath "pwsh.exe" -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$startScript`"", "-Service", "control-center", "-LogLevel", "$LogLevel"
            
            # Wait for service to be ready with better health checking
            Write-Host "  Waiting for Control Center to be ready (max 60s)..." -ForegroundColor Cyan
            $ready = $false
            $logShown = $false
            for ($i = 0; $i -lt 30; $i++) {
                Start-Sleep -Seconds 2
                
                # Check health endpoint
                try {
                    $response = Invoke-WebRequest "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
                    if ($response.StatusCode -eq 200) {
                        $ready = $true
                        break
                    }
                } catch {
                    # Show log tail on first failure to help diagnose issues
                    if (-not $logShown -and (Test-Path $logPath)) {
                        Write-Host "  Current log tail:" -ForegroundColor DarkGray
                        Get-Content $logPath -Tail 3 -ErrorAction SilentlyContinue | ForEach-Object {
                            Write-Host "    $_" -ForegroundColor DarkGray
                        }
                        $logShown = $true
                    }
                }
            }
            
            if ($ready) {
                Write-Host "✅ Control Center ready at http://localhost:8000" -ForegroundColor Green
                Write-Host "   Log: $logPath" -ForegroundColor DarkGray
            } else {
                Write-Host "⚠️ Control Center health check timeout" -ForegroundColor Yellow
                Write-Host "   Check logs: $logPath" -ForegroundColor Yellow
                if (Test-Path $logPath) {
                    Write-Host "   Recent errors:" -ForegroundColor Yellow
                    Get-Content $logPath -Tail 10 -ErrorAction SilentlyContinue | Select-String "ERROR|CRITICAL" | ForEach-Object {
                        Write-Host "   $_" -ForegroundColor Red
                    }
                }
            }
        }
        StopCommand = {
            Write-Host "Stopping Control Center..." -ForegroundColor Cyan
            $pids = netstat -ano | Select-String ":8000 .*LISTEN" | ForEach-Object {
                ($_.ToString().Trim() -split '\s+')[-1]
            } | Select-Object -Unique
            
            foreach ($processId in $pids) {
                Write-Host "  Killing process tree $processId..."
                # Use taskkill /F /T to kill entire process tree (parent + children)
                taskkill /F /T /PID $processId >$null 2>&1
            }
            
            # Wait a moment and verify port is actually free
            Start-Sleep -Milliseconds 500
            $stillRunning = netstat -ano | Select-String ":8000 .*LISTEN"
            if ($stillRunning) {
                Write-Host "  Warning: Port 8000 still in use after stop" -ForegroundColor Yellow
            } else {
                Write-Host "  ✓ Port 8000 is now free" -ForegroundColor Green
            }
        }
    }

    'agent-runtime' = @{
        Name = "Agent Runtime"
        Port = 8001
        HealthUrl = "http://localhost:8001/health"
        LogFile = "backend\logs\agent-runtime.log"
        DependsOn = @('control-center')
        CheckCommand = { (netstat -ano | Select-String ":8001 .*LISTEN") -ne $null }
        StartCommand = {
            Write-Host "Starting Agent Runtime (port 8001)..." -ForegroundColor Cyan
            
            # Verify Control Center is accessible first
            Write-Host "  Checking Control Center dependency..." -ForegroundColor Cyan
            try {
                $ccResponse = Invoke-WebRequest "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
                Write-Host "  ✓ Control Center is accessible" -ForegroundColor Green
            } catch {
                Write-Host "  ✗ Control Center not accessible - Agent Runtime may fail to start properly" -ForegroundColor Yellow
            }
            
            $startScript = Join-Path $Script:ProjectRoot "start-service.ps1"
            $logPath = Join-Path $Script:ProjectRoot "backend\logs\agent-runtime.log"
            Start-Process -FilePath "pwsh.exe" -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$startScript`"", "-Service", "agent-runtime", "-LogLevel", "$LogLevel"
            
            Write-Host "  Waiting for Agent Runtime to be ready (max 60s)..." -ForegroundColor Cyan
            $ready = $false
            $logShown = $false
            for ($i = 0; $i -lt 30; $i++) {
                Start-Sleep -Seconds 2
                try {
                    $response = Invoke-WebRequest "http://localhost:8001/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
                    if ($response.StatusCode -eq 200) {
                        $ready = $true
                        break
                    }
                } catch {
                    if (-not $logShown -and (Test-Path $logPath)) {
                        Write-Host "  Current log tail:" -ForegroundColor DarkGray
                        Get-Content $logPath -Tail 3 -ErrorAction SilentlyContinue | ForEach-Object {
                            Write-Host "    $_" -ForegroundColor DarkGray
                        }
                        $logShown = $true
                    }
                }
            }
            
            if ($ready) {
                Write-Host "✅ Agent Runtime ready at http://localhost:8001" -ForegroundColor Green
                Write-Host "   Log: $logPath" -ForegroundColor DarkGray
            } else {
                Write-Host "⚠️ Agent Runtime health check timeout" -ForegroundColor Yellow
                Write-Host "   Check logs: $logPath" -ForegroundColor Yellow
                if (Test-Path $logPath) {
                    Write-Host "   Recent errors:" -ForegroundColor Yellow
                    Get-Content $logPath -Tail 10 -ErrorAction SilentlyContinue | Select-String "ERROR|CRITICAL" | ForEach-Object {
                        Write-Host "   $_" -ForegroundColor Red
                    }
                }
            }
        }
        StopCommand = {
            Write-Host "Stopping Agent Runtime..." -ForegroundColor Cyan
            $pids = netstat -ano | Select-String ":8001 .*LISTEN" | ForEach-Object {
                ($_.ToString().Trim() -split '\s+')[-1]
            } | Select-Object -Unique
            
            foreach ($processId in $pids) {
                Write-Host "  Killing process tree $processId..."
                # Use taskkill /F /T to kill entire process tree (parent + children)
                taskkill /F /T /PID $processId >$null 2>&1
            }
            
            # Wait a moment and verify port is actually free
            Start-Sleep -Milliseconds 500
            $stillRunning = netstat -ano | Select-String ":8001 .*LISTEN"
            if ($stillRunning) {
                Write-Host "  Warning: Port 8001 still in use after stop" -ForegroundColor Yellow
            } else {
                Write-Host "  ✓ Port 8001 is now free" -ForegroundColor Green
            }
        }
    }

    'communication-hub' = @{
        Name = "Communication Hub"
        Port = 8002
        HealthUrl = "http://localhost:8002/health"
        LogFile = "backend\logs\communication-hub.log"
        DependsOn = @('control-center')
        CheckCommand = { (netstat -ano | Select-String ":8002 .*LISTEN") -ne $null }
        StartCommand = {
            Write-Host "Starting Communication Hub (port 8002)..." -ForegroundColor Cyan
            
            # Verify Control Center is accessible first
            Write-Host "  Checking Control Center dependency..." -ForegroundColor Cyan
            try {
                $ccResponse = Invoke-WebRequest "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
                Write-Host "  ✓ Control Center is accessible" -ForegroundColor Green
            } catch {
                Write-Host "  ✗ Control Center not accessible - Communication Hub may fail to start properly" -ForegroundColor Yellow
            }
            
            $startScript = Join-Path $Script:ProjectRoot "start-service.ps1"
            $logPath = Join-Path $Script:ProjectRoot "backend\logs\communication-hub.log"
            Start-Process -FilePath "pwsh.exe" -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$startScript`"", "-Service", "communication-hub", "-LogLevel", "$LogLevel"
            
            Write-Host "  Waiting for Communication Hub to be ready (max 60s)..." -ForegroundColor Cyan
            $ready = $false
            $logShown = $false
            for ($i = 0; $i -lt 30; $i++) {
                Start-Sleep -Seconds 2
                try {
                    $response = Invoke-WebRequest "http://localhost:8002/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
                    if ($response.StatusCode -eq 200) {
                        $ready = $true
                        break
                    }
                } catch {
                    if (-not $logShown -and (Test-Path $logPath)) {
                        Write-Host "  Current log tail:" -ForegroundColor DarkGray
                        Get-Content $logPath -Tail 3 -ErrorAction SilentlyContinue | ForEach-Object {
                            Write-Host "    $_" -ForegroundColor DarkGray
                        }
                        $logShown = $true
                    }
                }
            }
            
            if ($ready) {
                Write-Host "✅ Communication Hub ready at http://localhost:8002" -ForegroundColor Green
                Write-Host "   Log: $logPath" -ForegroundColor DarkGray
            } else {
                Write-Host "⚠️ Communication Hub health check timeout" -ForegroundColor Yellow
                Write-Host "   Check logs: $logPath" -ForegroundColor Yellow
                if (Test-Path $logPath) {
                    Write-Host "   Recent errors:" -ForegroundColor Yellow
                    Get-Content $logPath -Tail 10 -ErrorAction SilentlyContinue | Select-String "ERROR|CRITICAL" | ForEach-Object {
                        Write-Host "   $_" -ForegroundColor Red
                    }
                }
            }
        }
        StopCommand = {
            Write-Host "Stopping Communication Hub..." -ForegroundColor Cyan
            $pids = netstat -ano | Select-String ":8002 .*LISTEN" | ForEach-Object {
                ($_.ToString().Trim() -split '\s+')[-1]
            } | Select-Object -Unique
            
            foreach ($processId in $pids) {
                Write-Host "  Killing process tree $processId..."
                # Use taskkill /F /T to kill entire process tree (parent + children)
                taskkill /F /T /PID $processId >$null 2>&1
            }
            
            # Wait a moment and verify port is actually free
            Start-Sleep -Milliseconds 500
            $stillRunning = netstat -ano | Select-String ":8002 .*LISTEN"
            if ($stillRunning) {
                Write-Host "  Warning: Port 8002 still in use after stop" -ForegroundColor Yellow
            } else {
                Write-Host "  ✓ Port 8002 is now free" -ForegroundColor Green
            }
        }
    }
    
    frontend = @{
        Name = "Frontend Dev Server"
        Port = 5173
        HealthUrl = "http://localhost:5173"
        LogFile = $null  # Logs to console only
        CheckCommand = { (netstat -ano | Select-String ":5173 .*LISTEN") -ne $null }
        StartCommand = {
            Write-Host "Starting frontend dev server..." -ForegroundColor Cyan
            $frontendPath = Join-Path $Script:ProjectRoot "frontend"
            Start-Process -FilePath "pwsh.exe" -ArgumentList "-NoExit", "-Command", "Set-Location '$frontendPath'; npm run dev"
            
            # Wait for frontend to be ready
            Write-Host "  Waiting for frontend to be ready (max 30s)..." -ForegroundColor Cyan
            $ready = $false
            for ($i = 0; $i -lt 15; $i++) {
                Start-Sleep -Seconds 2
                try {
                    $response = Invoke-WebRequest "http://localhost:5173" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
                    if ($response.StatusCode -lt 500) {
                        $ready = $true
                        break
                    }
                } catch {
                    # It's normal for Vite to respond with redirect or other non-200 codes
                    if ($_.Exception.Response.StatusCode) {
                        $ready = $true
                        break
                    }
                }
            }
            
            if ($ready) {
                Write-Host "✅ Frontend is ready at http://localhost:5173" -ForegroundColor Green
            } else {
                Write-Host "⚠️ Frontend health check timeout" -ForegroundColor Yellow
                Write-Host "   Check the terminal window for Vite output" -ForegroundColor Yellow
            }
        }
        StopCommand = {
            Write-Host "Stopping frontend dev server..." -ForegroundColor Cyan
            $pids = netstat -ano | Select-String ":5173 .*LISTEN" | ForEach-Object {
                ($_.ToString().Trim() -split '\s+')[-1]
            } | Select-Object -Unique
            
            foreach ($processId in $pids) {
                Write-Host "  Killing process tree $processId..."
                # Use taskkill /F /T to kill entire process tree (parent + children)
                taskkill /F /T /PID $processId >$null 2>&1
            }
            
            # Wait a moment and verify port is actually free
            Start-Sleep -Milliseconds 500
            $stillRunning = netstat -ano | Select-String ":5173 .*LISTEN"
            if ($stillRunning) {
                Write-Host "  Warning: Port 5173 still in use after stop" -ForegroundColor Yellow
            } else {
                Write-Host "  ✓ Port 5173 is now free" -ForegroundColor Green
            }
        }
    }
}

function Show-Logs {
    param(
        [string]$ServiceName,
        [int]$LineCount = 50,
        [bool]$FollowMode = $false
    )
    
    $config = $Script:ServiceConfig[$ServiceName]
    
    if (-not $config) {
        Write-Host "⚠️  Unknown service: $ServiceName" -ForegroundColor Yellow
        Write-Host "   Available services: $($Script:ServiceConfig.Keys -join ', ')" -ForegroundColor Gray
        return
    }
    
    if (-not $config.LogFile) {
        Write-Host "⚠️  $($config.Name) does not have a log file (logs to console only)" -ForegroundColor Yellow
        return
    }
    
    $logPath = Join-Path $Script:ProjectRoot $config.LogFile
    
    if (-not (Test-Path $logPath)) {
        Write-Host "⚠️  Log file not found: $logPath" -ForegroundColor Yellow
        Write-Host "   Service may not have been started yet." -ForegroundColor Gray
        return
    }
    
    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  $($config.Name) Logs" -ForegroundColor Cyan
    Write-Host "  File: $logPath" -ForegroundColor Gray
    Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""
    
    if ($FollowMode) {
        Write-Host "Following logs (Ctrl+C to stop)..." -ForegroundColor Yellow
        Write-Host ""
        Get-Content $logPath -Tail $LineCount -Wait
    } else {
        Get-Content $logPath -Tail $LineCount | ForEach-Object {
            # Colorize log levels
            if ($_ -match 'ERROR|CRITICAL') {
                Write-Host $_ -ForegroundColor Red
            } elseif ($_ -match 'WARN') {
                Write-Host $_ -ForegroundColor Yellow
            } elseif ($_ -match 'INFO') {
                Write-Host $_ -ForegroundColor Cyan
            } elseif ($_ -match 'DEBUG') {
                Write-Host $_ -ForegroundColor Gray
            } else {
                Write-Host $_
            }
        }
    }
    
    Write-Host ""
}

function Get-ServiceStatus {
    param([string]$ServiceName)
    
    $config = $Script:ServiceConfig[$ServiceName]
    $isRunning = & $config.CheckCommand
    
    return @{
        Name = $config.Name
        Port = $config.Port
        Running = $isRunning
    }
}

function Show-Status {
    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  Parthenon Application Status" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""
    
    $statuses = @()
    
    foreach ($serviceName in @('infra', 'control-center', 'agent-runtime', 'communication-hub', 'frontend')) {
        $status = Get-ServiceStatus -ServiceName $serviceName
        $statuses += [PSCustomObject]@{
            Service = $status.Name
            Port = $status.Port
            Status = if ($status.Running) { "✅ Running" } else { "⏹️  Stopped" }
        }
    }
    
    $statuses | Format-Table -AutoSize
    Write-Host ""
}

function Start-Service {
    param(
        [string]$ServiceName,
        [bool]$ForceRestart
    )
    
    $config = $Script:ServiceConfig[$ServiceName]
    $status = Get-ServiceStatus -ServiceName $ServiceName
    
    if ($status.Running) {
        if (-not $ForceRestart) {
            Write-Host ""
            Write-Host "⚠️  $($config.Name) is already running on port $($config.Port)" -ForegroundColor Yellow
            $response = Read-Host "Do you want to [S]kip, [R]estart, or [A]bort? (S/R/A)"
            
            switch ($response.ToUpper()) {
                'S' {
                    Write-Host "Skipping $($config.Name)" -ForegroundColor Gray
                    return
                }
                'R' {
                    Write-Host "Restarting $($config.Name)..." -ForegroundColor Cyan
                    Stop-Service -ServiceName $ServiceName
                    Start-Sleep -Seconds 2
                    & $config.StartCommand
                }
                'A' {
                    Write-Host "Aborted by user" -ForegroundColor Red
                    exit 1
                }
                default {
                    Write-Host "Invalid choice. Skipping." -ForegroundColor Gray
                    return
                }
            }
        } else {
            Write-Host "Force restarting $($config.Name)..." -ForegroundColor Cyan
            Stop-Service -ServiceName $ServiceName
            
            # Verify service stopped before starting
            $maxRetries = 5
            $retry = 0
            while ((& $config.CheckCommand) -and ($retry -lt $maxRetries)) {
                Write-Host "  Waiting for service to stop completely..." -ForegroundColor Yellow
                Start-Sleep -Seconds 1
                $retry++
            }
            
            if (& $config.CheckCommand) {
                Write-Host "⚠️  Service did not stop - may start duplicate instance" -ForegroundColor Yellow
            }
            
            & $config.StartCommand
        }
    } else {
        & $config.StartCommand
    }
}

function Stop-Service {
    param([string]$ServiceName)
    
    $config = $Script:ServiceConfig[$ServiceName]
    $status = Get-ServiceStatus -ServiceName $ServiceName
    
    if ($status.Running) {
        & $config.StopCommand
        
        # Verify the service actually stopped by checking if port is freed
        if ($config.CheckCommand) {
            $maxWait = 10  # seconds
            $waited = 0
            while ((& $config.CheckCommand) -and ($waited -lt $maxWait)) {
                Start-Sleep -Milliseconds 500
                $waited += 0.5
            }
            
            if (& $config.CheckCommand) {
                Write-Host "⚠️  $($config.Name) did not stop cleanly - forcing kill..." -ForegroundColor Yellow
                # Force kill by port one more time
                if ($config.Port) {
                    $pids = netstat -ano | Select-String ":$($config.Port) .*LISTEN" | ForEach-Object {
                        ($_.ToString().Trim() -split '\s+')[-1]
                    } | Select-Object -Unique
                    
                    foreach ($processId in $pids) {
                        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
                        Write-Host "  Force killed process $processId" -ForegroundColor Red
                    }
                    Start-Sleep -Seconds 1
                }
            }
        }
        
        Write-Host "✅ $($config.Name) stopped" -ForegroundColor Green
    } else {
        Write-Host "ℹ️  $($config.Name) is not running" -ForegroundColor Gray
    }
}

# Parse services parameter
$serviceList = if ($Services -eq 'all') {
    @('infra', 'control-center', 'agent-runtime', 'communication-hub', 'frontend')
} elseif ($Services -eq 'backend') {
    # All services except infrastructure
    @('control-center', 'agent-runtime', 'communication-hub', 'frontend')
} else {
    $Services -split ',' | ForEach-Object { $_.Trim() }
}

# Validate service names (skip for logs command which has its own validation)
if ($Action -ne 'logs') {
    foreach ($svc in $serviceList) {
        if ($svc -notin @('infra', 'control-center', 'agent-runtime', 'communication-hub', 'frontend')) {
            Write-Host "Error: Invalid service name '$svc'. Valid options: infra, control-center, agent-runtime, communication-hub, frontend, all" -ForegroundColor Red
            exit 1
        }
    }
}

# Execute action
Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Parthenon Application Manager" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

switch ($Action) {
    'status' {
        Show-Status
    }
    
    'start' {
        Write-Host "Starting services: $($serviceList -join ', ')" -ForegroundColor Cyan
        Write-Host ""
        Set-SslCaBundle
        Write-Host ""

        # Run setup if -RunSetup flag is present and setup hasn't been completed
        if ($RunSetup.IsPresent) {
            $setupMarker = Join-Path $Script:ProjectRoot ".setup-complete.marker"
            if (Test-Path $setupMarker) {
                Write-Host "Setup marker found — skipping setup (use -Force to re-run)" -ForegroundColor Green
            } else {
                Write-Host "--- Running Environment Setup ---" -ForegroundColor Cyan
                Push-Location $Script:ProjectRoot
                try {
                    if (Test-Path ".venv\Scripts\Activate.ps1") {
                        & .venv\Scripts\Activate.ps1
                    }
                    python -m setup.main dev
                    $setupExit = $LASTEXITCODE
                } finally {
                    Pop-Location
                }

                if ($setupExit -eq 0) {
                    New-Item -ItemType File -Path $setupMarker -Force | Out-Null
                    Write-Host "Setup complete — marker written to .setup-complete.marker" -ForegroundColor Green
                } else {
                    Write-Host "Setup failed with exit code $setupExit — services will NOT be started" -ForegroundColor Red
                    exit 1
                }
            }
            Write-Host ""
        }

        # Start in dependency order: infra -> control-center -> agent-runtime -> communication-hub -> frontend
        $orderedServices = @('infra', 'control-center', 'agent-runtime', 'communication-hub', 'frontend') | Where-Object { $_ -in $serviceList }
        
        foreach ($svc in $orderedServices) {
            Start-Service -ServiceName $svc -ForceRestart $Force.IsPresent
            Write-Host ""
        }
        
        Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
        Show-Status
    }
    
    'stop' {
        Write-Host "Stopping services: $($serviceList -join ', ')" -ForegroundColor Cyan
        Write-Host ""
        
        # Stop in reverse order: frontend -> communication-hub -> agent-runtime -> control-center -> infra
        $orderedServices = @('frontend', 'communication-hub', 'agent-runtime', 'control-center', 'infra') | Where-Object { $_ -in $serviceList }
        
        foreach ($svc in $orderedServices) {
            Stop-Service -ServiceName $svc
        }
        
        Write-Host ""
        Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
        Show-Status
    }
    
    'restart' {
        Write-Host "Restarting services: $($serviceList -join ', ')" -ForegroundColor Cyan
        Write-Host ""
        Set-SslCaBundle
        Write-Host ""
        
        # Stop in reverse order
        $orderedServices = @('frontend', 'communication-hub', 'agent-runtime', 'control-center', 'infra') | Where-Object { $_ -in $serviceList }
        foreach ($svc in $orderedServices) {
            Stop-Service -ServiceName $svc
        }
        
        # Wait a bit longer to ensure ports are fully freed
        Write-Host "Waiting for ports to be freed..." -ForegroundColor Cyan
        Start-Sleep -Seconds 3
        
        # Start in normal order using Start-Service to handle any lingering processes
        $orderedServices = @('infra', 'control-center', 'agent-runtime', 'communication-hub', 'frontend') | Where-Object { $_ -in $serviceList }
        foreach ($svc in $orderedServices) {
            # Use Start-Service with ForceRestart to handle any edge cases
            Start-Service -ServiceName $svc -ForceRestart $true
            Write-Host ""
        }
        
        Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
        Show-Status
    }
    
    'init' {
        Write-Host "Initializing local development environment..." -ForegroundColor Cyan
        Write-Host ""
        Write-Host "This will set up:" -ForegroundColor Yellow
        Write-Host "  - Keycloak realm and OIDC clients" -ForegroundColor Yellow
        Write-Host "  - Default admin user (admin@parthenon.local)" -ForegroundColor Yellow
        Write-Host "  - Database roles and permissions" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Prerequisites:" -ForegroundColor Yellow
        Write-Host "  - Keycloak must be running (./parthenon.ps1 start -Services infra)" -ForegroundColor Yellow
        Write-Host "  - Database must be accessible" -ForegroundColor Yellow
        Write-Host ""
        
        # Check if Keycloak is running
        $keycloakRunning = docker ps --filter "name=parthenon-keycloak" --format "{{.Names}}"
        if (-not $keycloakRunning) {
            Write-Host "✗ Keycloak is not running!" -ForegroundColor Red
            Write-Host "  Start infrastructure with: ./parthenon.ps1 start -Services infra" -ForegroundColor Yellow
            exit 1
        }
        
        Write-Host "Running setup command..." -ForegroundColor Cyan
        Write-Host ""
        
        # Activate venv and run setup
        Push-Location $Script:ProjectRoot
        try {
            if (Test-Path ".venv\Scripts\Activate.ps1") {
                & .venv\Scripts\Activate.ps1
            }
            python -m setup.main dev
            $exitCode = $LASTEXITCODE
            
            if ($exitCode -eq 0) {
                Write-Host ""
                Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Green
                Write-Host "  Setup Complete!" -ForegroundColor Green
                Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Green
            } else {
                Write-Host ""
                Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Red
                Write-Host "  Setup Failed!" -ForegroundColor Red
                Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Red
            }
        }
        finally {
            Pop-Location
        }
    }
    
    'logs' {
        # For logs, we only support backend services that have log files
        $logServices = if ($Services -eq 'all') {
            @('control-center', 'agent-runtime', 'communication-hub')
        } else {
            @($Services -split ',' | ForEach-Object { $_.Trim() })
        }
        
        # Validate service names for logs
        foreach ($svc in $logServices) {
            if ($svc -notin @('control-center', 'agent-runtime', 'communication-hub')) {
                Write-Host "Error: Invalid service name '$svc' for logs. Valid options: control-center, agent-runtime, communication-hub, all" -ForegroundColor Red
                exit 1
            }
        }
        
        if ($logServices.Count -eq 1) {
            # Single service - show logs
            # Use foreach instead of [0] to avoid string indexing issue
            foreach ($svc in $logServices) {
                Show-Logs -ServiceName $svc -LineCount $Lines -FollowMode $Follow.IsPresent
            }
        } else {
            # Multiple services - show logs from each
            foreach ($svc in $logServices) {
                Show-Logs -ServiceName $svc -LineCount $Lines -FollowMode $false
            }
            
            if ($Follow.IsPresent) {
                Write-Host "⚠️  Follow mode only works with a single service" -ForegroundColor Yellow
                Write-Host "   Example: .\parthenon.ps1 logs -Services control-center -Follow" -ForegroundColor Gray
            }
        }
    }
}

Write-Host "Done!" -ForegroundColor Green
Write-Host ""
