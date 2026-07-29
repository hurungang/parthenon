# Parthenon Opencode Slash Commands

Project-level slash commands for opencode. Mirrors `.github/prompts/` for cross-IDE compatibility.

## Available Commands

### `/init-app`
Initialize the local development environment. Supports full docker-compose or selective external-service setup. Uses the consolidated `setup/` CLI tool.

### `/start-app`
Start Parthenon services via `parthenon.ps1`. Supports `--infra`, `--backend`, `--frontend`, `--control-center`, `--agent-runtime`, `--communication-hub`, `--setup`, `--force`.

### `/stop-app`
Stop Parthenon services via `parthenon.ps1`.

### `/test-app`
Run tests across all three layers: backend (pytest), frontend (vitest), e2e (playwright).

### `/demo-app`
Demo the application via Playwright headed browser mode.

## Development Workflow

1. **Fresh setup**: `/init-app` then `/start-app`
2. **Daily dev**: `/start-app --backend` then `/test-app --filter "feature"`
3. **Stop**: `/stop-app`

## Syncing

These prompts mirror `.github/prompts/`. Changes to either directory should be kept in sync.
