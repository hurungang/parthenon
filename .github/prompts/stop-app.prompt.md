---
description: Stop the Parthenon application. By default stops everything (frontend, backend, infrastructure). Supports --frontend, --backend, --infra flags to stop only specific parts. Use --docker to stop docker compose services. Named terminals remain open for reuse.
---

Stop the Parthenon application.

**Usage**: `/stop-app [--frontend] [--backend] [--infra] [--docker]`

- No flags → stop everything (frontend, backend, infra containers)
- `--frontend` → stop only the frontend dev/preview server
- `--backend` → stop only the backend API process
- `--infra` → stop only infrastructure containers (postgres, redis)
- `--docker` → stop all docker compose services

**Note**: Terminals remain open after stopping processes and can be reused:
- **"Parthenon Backend"** terminal
- **"Parthenon Frontend"** terminal
- **"Parthenon Preview"** terminal

---

## Step 1: Parse Input

Read the user's message for flags: `--frontend`, `--backend`, `--infra`, `--docker`.

If no flags, default mode = stop everything.

---

## Step 2: Check What Is Running

```powershell
# Check backend (port 8000)
$backend = netstat -ano | Select-String ":8000 .*LISTEN"

# Check frontend (port 5173 or 4173)
$frontend5173 = netstat -ano | Select-String ":5173 .*LISTEN"
$frontend4173 = netstat -ano | Select-String ":4173 .*LISTEN"

# Check docker containers
docker ps --format "{{.Names}}\t{{.Status}}" 2>$null | Select-String "parthenon"
```

Report what is found running before stopping.

---

## Step 3: Stop Frontend (if applicable)

**Skip if `--backend` or `--infra` only.**

Find and stop the Vite dev server or preview server:
```powershell
# Find PID listening on 5173 or 4173
$pids = (netstat -ano | Select-String ":(5173|4173) .*LISTEN" | ForEach-Object {
    ($_ -split '\s+')[-1]
}) | Sort-Object -Unique

if ($pids) {
    Write-Host "Stopping frontend server(s)..."
    $pids | ForEach-Object { 
        Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue 
        Write-Host "  Stopped PID $_"
    }
    Write-Host "✅ Frontend stopped (terminals 'Parthenon Frontend' and 'Parthenon Preview' can be reused)"
} else {
    Write-Host "Frontend not running"
}
```

Confirm port 5173/4173 is no longer listening.

---

## Step 4: Stop Backend (if applicable)

**Skip if `--frontend` or `--infra` only.**

Find and stop the uvicorn process:
```powershell
# Find PID listening on 8000
$pids = (netstat -ano | Select-String ":8000 .*LISTEN" | ForEach-Object {
    ($_ -split '\s+')[-1]
}) | Sort-Object -Unique

if ($pids) {
    Write-Host "Stopping backend server..."
    $pids | ForEach-Object { 
        Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue 
        Write-Host "  Stopped PID $_"
    }
    Write-Host "✅ Backend stopped (terminal 'Parthenon Backend' can be reused)"
} else {
    Write-Host "Backend not running"
}
```

Confirm port 8000 is no longer listening.

---

## Step 5: Stop Infrastructure Containers (if applicable)

**Skip if `--frontend` or `--backend` only.**

```powershell
cd <project_root>
docker compose stop postgres redis keycloak
```

---

## Step 6: Docker Mode (--docker flag)

**Instead of Steps 3–5**, stop all compose services:

```powershell
cd <project_root>
docker compose down
```

---

## Step 7: Report Status

```
## 🛑 Parthenon Application Stopped

| Component     | Action                    |
|---------------|---------------------------|
| Frontend      | ✅ Stopped / ⏭️ Not running |
| Backend API   | ✅ Stopped / ⏭️ Not running |
| PostgreSQL    | ✅ Stopped / ⏭️ Not running |
| Redis         | ✅ Stopped / ⏭️ Not running |
| Keycloak      | ✅ Stopped / ⏭️ Not running |
```
