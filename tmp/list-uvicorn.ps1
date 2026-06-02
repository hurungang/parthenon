Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match 'uvicorn' } |
    ForEach-Object {
        $app = if ($_.CommandLine -match 'app\.(\w+):app') { $Matches[1] } else { '?' }
        $port = if ($_.CommandLine -match '--port\s+(\d+)') { $Matches[1] } else { '?' }
        Write-Host "PID=$($_.ProcessId)  service=$app  port=$port"
    }
