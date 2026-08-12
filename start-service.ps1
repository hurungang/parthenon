# start-service.ps1 - Helper to start Parthenon services with .env loading
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('control-center', 'agent-runtime', 'communication-hub')]
    [string]$Service,

    [Parameter()]
    [ValidateSet('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')]
    [string]$LogLevel = 'INFO'
)

# Platform detection
$_IsWindows = $PSVersionTable.Platform -eq 'Win32NT' -or [System.Environment]::OSVersion.Platform -eq 'Win32NT'
$PythonExe = if ($_IsWindows) { Join-Path $PSScriptRoot ".venv\Scripts\python.exe" } else { Join-Path $PSScriptRoot ".venv/bin/python" }
$BackendDir = Join-Path $PSScriptRoot "backend"
$Sep = if ($_IsWindows) { '\' } else { '/' }

# Load .env file
$envFile = Join-Path $PSScriptRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#')) {
            if ($line -match '^([^=]+)=(.*)$') {
                $key = $matches[1].Trim()
                $value = $matches[2].Trim()
                
                # Remove inline comments (anything after # that's not inside quotes)
                if ($value -match '^([^#]*?)(\s+#.*)$' -and $value -notmatch '^".*"$' -and $value -notmatch "^'.*'$") {
                    $value = $matches[1].Trim()
                }
                
                # Remove surrounding quotes if present
                $value = $value -replace '^"(.*)"$', '$1' -replace "^'(.*)'$", '$1'
                
                [Environment]::SetEnvironmentVariable($key, $value, "Process")
            }
        }
    }
    Write-Host "Loaded environment variables from .env" -ForegroundColor Green
} else {
    Write-Host "No .env file found" -ForegroundColor Yellow
}

# Prevent Python bytecode caching to ensure fresh code loads
$env:PYTHONDONTWRITEBYTECODE = "1"

# Apply log level
Write-Host "Log level: $LogLevel" -ForegroundColor Cyan
$env:TELEMETRY__LOG_LEVELS = "{""root"": ""$LogLevel""}"

# Service-specific environment
switch ($Service) {
    'control-center' {
        $env:TELEMETRY__EXPORTERS = '["file", "otlp"]'
        $env:TELEMETRY__FILE__PATH = 'logs/control-center.log'
        $env:TELEMETRY__FILE__MAX_BYTES = '10485760'
        $env:TELEMETRY__FILE__BACKUP_COUNT = '5'
        $env:OTEL_SERVICE_NAME = 'parthenon-control-center'
        $env:OTEL_EXPORTER_OTLP_ENDPOINT = 'http://localhost:4317'
        
        Write-Host "`nStarting Control Center on http://localhost:8000" -ForegroundColor Cyan
        Write-Host "Logs: backend${Sep}logs${Sep}control-center.log`n" -ForegroundColor Gray
        
        Set-Location $BackendDir
        & $PythonExe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --no-access-log
    }
    
    'agent-runtime' {
        $env:CONTROL_CENTER_URL = if ($env:CONTROL_CENTER_URL) { $env:CONTROL_CENTER_URL } else { "http://localhost:8000" }
        $env:SERVICE_BOOTSTRAP_KEY = $env:AGENT_RUNTIME_BOOTSTRAP_KEY
        $env:AGENT_CERT_PATH = Join-Path $BackendDir "certs${Sep}agent-runtime${Sep}service-cert.pem"
        $env:AGENT_KEY_PATH = Join-Path $BackendDir "certs${Sep}agent-runtime${Sep}service-key.pem"
        $env:CA_CERT_PATH = Join-Path $BackendDir "certs${Sep}agent-runtime${Sep}ca-cert.pem"
        $env:TELEMETRY__EXPORTERS = '["file", "otlp"]'
        $env:TELEMETRY__FILE__PATH = 'logs/agent-runtime.log'
        $env:TELEMETRY__FILE__MAX_BYTES = '10485760'
        $env:TELEMETRY__FILE__BACKUP_COUNT = '5'
        $env:OTEL_SERVICE_NAME = 'parthenon-agent-runtime'
        $env:OTEL_EXPORTER_OTLP_ENDPOINT = 'http://localhost:4317'
        
        Write-Host "`nStarting Agent Runtime on http://localhost:8001" -ForegroundColor Cyan
        Write-Host "Logs: backend${Sep}logs${Sep}agent-runtime.log`n" -ForegroundColor Gray
        
        Set-Location $BackendDir
        & $PythonExe -m uvicorn app.agent_runtime.main:app --reload --host 0.0.0.0 --port 8001 --no-access-log
    }
    
    'communication-hub' {
        $env:CONTROL_CENTER_URL = if ($env:CONTROL_CENTER_URL) { $env:CONTROL_CENTER_URL } else { "http://localhost:8000" }
        $env:SERVICE_BOOTSTRAP_KEY = $env:COMM_HUB_BOOTSTRAP_KEY
        $env:TELEMETRY__EXPORTERS = '["file", "otlp"]'
        $env:TELEMETRY__FILE__PATH = 'logs/communication-hub.log'
        $env:TELEMETRY__FILE__MAX_BYTES = '10485760'
        $env:TELEMETRY__FILE__BACKUP_COUNT = '5'
        $env:OTEL_SERVICE_NAME = 'parthenon-communication-hub'
        $env:OTEL_EXPORTER_OTLP_ENDPOINT = 'http://localhost:4317'
        
        Write-Host "`nStarting Communication Hub on http://localhost:8002" -ForegroundColor Cyan
        Write-Host "Logs: backend${Sep}logs${Sep}communication-hub.log`n" -ForegroundColor Gray
        
        Set-Location $BackendDir
        & $PythonExe -m uvicorn app.communication_hub.main:app --reload --host 0.0.0.0 --port 8002 --no-access-log
    }
}
