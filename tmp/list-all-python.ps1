$procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'"
foreach ($p in $procs) {
    Write-Host "PID=$($p.ProcessId) -- $($p.CommandLine)"
}
