$procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'"
foreach ($p in $procs) {
    if ($p.CommandLine -match 'communication_hub') {
        Write-Host "CH: PID=$($p.ProcessId)"
    } elseif ($p.CommandLine -match 'control_center|main:app') {
        Write-Host "CC: PID=$($p.ProcessId)"
    } elseif ($p.CommandLine -match 'agent_runtime') {
        Write-Host "AR: PID=$($p.ProcessId)"
    }
}
