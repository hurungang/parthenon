# Parthenon Slash Commands

This directory contains project-specific slash commands for working with the Parthenon application.

## Available Commands

### 🚀 Application Lifecycle

#### `/init-app`
**First-time setup for local development**

Initializes the local development environment by:
- Creating Keycloak realms (human users: `parthenon`, agents: `ai_agents`)
- Configuring OIDC clients in both realms
- Creating default admin user with consistent UUID
- Seeding database with system roles and permissions
- Assigning system_admin role to admin user

**Prerequisites:**
- Infrastructure must be running (`/start-app --infra`)
- Python virtual environment must be activated

**Usage:**
```
/init-app
```

**Idempotent:** Safe to run multiple times if setup fails or Keycloak is reset.

---

#### `/start-app`
**Start the Parthenon application**

Starts services based on flags provided.

**Usage:**
```
/start-app                    # Start everything (infra + backend + frontend)
/start-app --frontend         # Start only frontend dev server
/start-app --backend          # Start only backend API + infra
/start-app --infra            # Start only infrastructure (postgres, redis, keycloak)
/start-app --docker           # Start full stack via docker compose
```

**Services:**
- Infrastructure: PostgreSQL, Redis, Keycloak, OTEL Collector (port 5432, 6379, 8082)
- Backend: Control Center (port 8000)
- Frontend: Vite dev server (port 5173)

---

#### `/stop-app`
**Stop the Parthenon application**

Stops services based on flags provided.

**Usage:**
```
/stop-app                     # Stop everything
/stop-app --frontend          # Stop only frontend
/stop-app --backend           # Stop only backend
/stop-app --infra             # Stop only infrastructure
/stop-app --docker            # Stop docker compose services
```

---

### 🧪 Testing & Demo

#### `/test-app`
**Run tests for the Parthenon application**

Runs tests across all three layers: backend (pytest), frontend (Vitest), E2E (Playwright).

**Usage:**
```
/test-app                     # Run all tests (backend + frontend + e2e)
/test-app --backend           # Run only backend tests (pytest)
/test-app --frontend          # Run only frontend tests (Vitest)
/test-app --e2e               # Run only E2E tests (Playwright)
/test-app --filter "auth"     # Run all tests matching "auth" across all layers
/test-app --backend --filter "user"  # Run backend tests matching "user"
```

---

#### `/demo-app`
**Run live demo of the application**

Launches interactive demo scenarios using Playwright in headed mode.

**Usage:**
```
/demo-app                     # Interactive scenario selection
/demo-app --fast              # Quick demo (1s per action)
/demo-app --normal            # Normal demo (5s per action, default)
/demo-app --slow              # Presentation demo (10s per action)
/demo-app --manual            # Manual control (UI mode)
/demo-app --cases auth.md     # Run scenarios from specific demo-cases file
```

---

## Development Workflow

### First-Time Setup (New Developer)

1. Clone the repository
2. Install dependencies: `pip install -e backend/` and `npm install` in `frontend/`
3. Start infrastructure: `/start-app --infra`
4. **Initialize environment: `/init-app`** ← New step!
5. Run migrations: `cd backend; alembic upgrade head`
6. Start application: `/start-app`
7. Access at http://localhost:5173 (login: `admin@parthenon.local` / `admin`)

### Daily Development

1. Start infrastructure (if not running): `/start-app --infra`
2. Start backend: `/start-app --backend`
3. Start frontend: `/start-app --frontend`
4. Make changes...
5. Run tests: `/test-app --filter "your feature"`
6. Stop when done: `/stop-app`

### After Pulling Changes

1. Check for migrations: `cd backend; alembic upgrade head`
2. Check for dependency updates: `pip install -e backend/` and `npm install` in `frontend/`
3. If Keycloak was reset or permissions are broken: `/init-app`
4. Restart: `/stop-app` then `/start-app`

---

## Troubleshooting

### "Admin user has no permissions"

**Cause:** Duplicate admin users with different Keycloak UUIDs

**Solution:**
1. Stop services: `/stop-app`
2. Run initialization: `/init-app`
3. Restart: `/start-app`

### "Keycloak is not running"

**Solution:**
```
/start-app --infra
```

Wait 30-60 seconds for Keycloak to fully start, then retry.

### "Port already in use"

**Check what's running:**
```powershell
netstat -ano | findstr ":8000 :5173 :8082"
```

**Stop services:**
```
/stop-app
```

---

## Related Documentation

- [LOCAL-DEV-SETUP.md](../../LOCAL-DEV-SETUP.md) - Comprehensive setup guide
- [README.md](../../README.md) - Project overview
- [PARTHENON-SCRIPT-GUIDE.md](../../PARTHENON-SCRIPT-GUIDE.md) - PowerShell script usage

---

## Command Implementation

All commands are implemented as markdown prompts in `.github/prompts/` using the agent workflow pattern. They guide the AI agent through executing PowerShell commands and validating results.

To add a new command:
1. Create `<name>.prompt.md` in this directory
2. Add YAML frontmatter with `description`
3. Write step-by-step instructions for the agent
4. Update this README
5. Update references in `change-apply.prompt.md` and `change-refinement.prompt.md`
