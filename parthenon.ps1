<#
.SYNOPSIS
    Parthenon Application Manager - Start, stop, and manage the Parthenon stack

.DESCRIPTION
    Standalone script to manage the Parthenon application stack.
    Controls infrastructure (Keycloak, PostgreSQL, Redis), backend API, and frontend dev server.

.PARAMETER Action
    Action to perform: start, stop, restart, status

.PARAMETER Services
    Comma-separated list of services: infra, backend, frontend, all (default: all)

.PARAMETER Force
    Force restart without confirmation if service is already running

.EXAMPLE
    .\parthenon.ps1 start
    Start all services

.EXAMPLE
    .\parthenon.ps1 start -Services backend,frontend
    Start only backend and frontend (assumes infra is running)

.EXAMPLE
    .\parthenon.ps1 stop -Services backend
    Stop only the backend

.EXAMPLE
    .\parthenon.ps1 restart -Services all -Force
    Force restart all services without confirmation

.EXAMPLE
    .\parthenon.ps1 status
    Show status of all services
#>

[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [ValidateSet('start', 'stop', 'restart', 'status')]
    [string]$Action = 'status',
    
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$Services = 'all',
    
    [Parameter()]
    [switch]$Force
)

# Script configuration
$Script:ProjectRoot = $PSScriptRoot
$Script:BackendDir = Join-Path $ProjectRoot "backend"
$Script:FrontendDir = Join-Path $ProjectRoot "frontend"

# Service definitions
$Script:ServiceConfig = @{
    infra = @{
        Name = "Infrastructure (Docker)"
        Port = 5432  # Postgres port as indicator
        CheckCommand = { (docker ps --filter "name=parthenon-postgres" --format "{{.Names}}") -ne $null }
        StartCommand = { 
            Write-Host "Starting infrastructure containers (PostgreSQL, Redis, Keycloak)..." -ForegroundColor Cyan
            docker compose up -d postgres redis keycloak
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
            docker compose stop keycloak redis postgres
        }
    }
    
    backend = @{
        Name = "Backend API"
        Port = 8000
        CheckCommand = { (netstat -ano | Select-String ":8000 .*LISTEN") -ne $null }
        StartCommand = {
            Write-Host "Starting backend API server..." -ForegroundColor Cyan
            $backendPath = Join-Path $Script:ProjectRoot "backend"

            # Set SSL certificate bundle for corporate firewall CA (same pattern as myaider-app)
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

            Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "cd /d $backendPath && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
            
            # Wait for backend to be ready
            Start-Sleep -Seconds 8
            $ready = $false
            for ($i = 0; $i -lt 5; $i++) {
                try {
                    $response = Invoke-WebRequest "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
                    if ($response.StatusCode -eq 200) {
                        $ready = $true
                        break
                    }
                } catch {
                    Start-Sleep -Seconds 2
                }
            }
            
            if ($ready) {
                Write-Host "✅ Backend is ready at http://localhost:8000" -ForegroundColor Green
            } else {
                Write-Host "⚠️ Backend started but may not be ready yet" -ForegroundColor Yellow
            }
        }
        StopCommand = {
            Write-Host "Stopping backend API server..." -ForegroundColor Cyan
            $pids = netstat -ano | Select-String ":8000 .*LISTEN" | ForEach-Object {
                ($_.ToString().Trim() -split '\s+')[-1]
            } | Select-Object -Unique
            
            foreach ($processId in $pids) {
                Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
                Write-Host "  Stopped process $processId"
            }
        }
    }
    
    frontend = @{
        Name = "Frontend Dev Server"
        Port = 5173
        CheckCommand = { (netstat -ano | Select-String ":5173 .*LISTEN") -ne $null }
        StartCommand = {
            Write-Host "Starting frontend dev server..." -ForegroundColor Cyan
            $frontendPath = Join-Path $Script:ProjectRoot "frontend"
            Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "cd /d $frontendPath && npm run dev"
            
            # Wait for frontend to be ready
            Start-Sleep -Seconds 10
            $ready = $false
            for ($i = 0; $i -lt 5; $i++) {
                try {
                    $response = Invoke-WebRequest "http://localhost:5173" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
                    if ($response.StatusCode -lt 500) {
                        $ready = $true
                        break
                    }
                } catch {
                    Start-Sleep -Seconds 2
                }
            }
            
            if ($ready) {
                Write-Host "✅ Frontend is ready at http://localhost:5173" -ForegroundColor Green
            } else {
                Write-Host "⚠️ Frontend started but may not be ready yet" -ForegroundColor Yellow
            }
        }
        StopCommand = {
            Write-Host "Stopping frontend dev server..." -ForegroundColor Cyan
            $pids = netstat -ano | Select-String ":5173 .*LISTEN" | ForEach-Object {
                ($_.ToString().Trim() -split '\s+')[-1]
            } | Select-Object -Unique
            
            foreach ($pid in $pids) {
                Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                Write-Host "  Stopped process $pid"
            }
        }
    }
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
    
    foreach ($serviceName in @('infra', 'backend', 'frontend')) {
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
                    & $config.StopCommand
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
            & $config.StopCommand
            Start-Sleep -Seconds 2
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
        Write-Host "✅ $($config.Name) stopped" -ForegroundColor Green
    } else {
        Write-Host "ℹ️  $($config.Name) is not running" -ForegroundColor Gray
    }
}

# Parse services parameter
$serviceList = if ($Services -eq 'all') {
    @('infra', 'backend', 'frontend')
} else {
    $Services -split ',' | ForEach-Object { $_.Trim() }
}

# Validate service names
foreach ($svc in $serviceList) {
    if ($svc -notin @('infra', 'backend', 'frontend')) {
        Write-Host "Error: Invalid service name '$svc'. Valid options: infra, backend, frontend, all" -ForegroundColor Red
        exit 1
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
        
        # Start in order: infra -> backend -> frontend
        $orderedServices = @('infra', 'backend', 'frontend') | Where-Object { $_ -in $serviceList }
        
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
        
        # Stop in reverse order: frontend -> backend -> infra
        $orderedServices = @('frontend', 'backend', 'infra') | Where-Object { $_ -in $serviceList }
        
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
        
        # Stop in reverse order
        $orderedServices = @('frontend', 'backend', 'infra') | Where-Object { $_ -in $serviceList }
        foreach ($svc in $orderedServices) {
            Stop-Service -ServiceName $svc
        }
        
        Start-Sleep -Seconds 2
        
        # Start in normal order
        $orderedServices = @('infra', 'backend', 'frontend') | Where-Object { $_ -in $serviceList }
        foreach ($svc in $orderedServices) {
            & $Script:ServiceConfig[$svc].StartCommand
            Write-Host ""
        }
        
        Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
        Show-Status
    }
}

Write-Host "Done!" -ForegroundColor Green
Write-Host ""
