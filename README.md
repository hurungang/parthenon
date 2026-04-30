# Parthenon — Enterprise AI Harness Framework

Parthenon is a full-stack Enterprise AI Harness that provides a unified platform for managing AI agents with fine-grained control, security, and observability.

## Vision

Parthenon provides a **unified platform to harness AI agents** with enterprise-grade controls:

- **Fine-Grained Permission Control**: Skill-based MCP tool permission management via a communication hub, ensuring agents can only access the tools they need
- **Dual Identity Support**: Agents can operate using their own identity or delegate the user's identity for actions
- **Flexible Agent Input Models**: Support for conversational agents, trigger-only agents (no input required), and argument-based agents (e.g., correlation ID for troubleshooting)
- **Standard Operating Procedures (SOPs)**: Define and standardize operational workflows based on one or multiple skills

## Core Capabilities

### 🔐 Fine-Grained Access Control

Parthenon implements skill-based permission management at the MCP tool level:

- **Communication Hub**: Acts as a permission gateway between agents and MCP tool servers
- **Skill-Based Permissions**: Control which MCP tools an agent can access based on assigned skills
- **Least Privilege Principle**: Agents only get access to tools necessary for their specific function
- **Centralized Policy Management**: Define and enforce access policies across all agents

### 👤 Dual Identity Support

Agents in Parthenon can operate with flexible identity models:

- **Agent Identity**: Agent operates with its own service principal identity for autonomous operations
- **User Identity Delegation**: Agent acts on behalf of the user, inheriting their permissions and audit trail
- **Configurable per Agent Type**: Define identity behavior at the agent type level

### 🤖 Multiple Agent Input Types

Parthenon supports diverse agent interaction patterns:

| Agent Type | Input Model | Use Case Example |
|------------|-------------|------------------|
| **Conversational** | Interactive dialogue | Help desk assistant, Q&A bot |
| **Trigger-Only** | No input, event-triggered | Scheduled reports, monitoring alerts |
| **Argument-Based** | Structured parameters | Troubleshooting with correlation ID, batch processing |

### 📋 Standard Operating Procedures (SOPs)

Define standardized workflows combining one or multiple skills:

- **Multi-Skill Orchestration**: Chain skills together into repeatable procedures
- **Standardized Operations**: Ensure consistent execution across teams
- **Compliance & Audit**: Track SOP execution for regulatory requirements
- **Version Control**: Maintain SOP definitions as code

## Architecture

- **Backend**: Python 3.11+ / FastAPI / SQLAlchemy 2 (async) / PostgreSQL 16 / Redis
- **Frontend**: React 19 / TypeScript / MUI 7 / React Router 7 / Vite
- **Auth**: OIDC/OAuth2 (Keycloak / EntraID)
- **Infra**: Docker Compose + Kubernetes/Helm + nginx + OTEL Collector

## Getting Started

### Using the Management Script (Recommended)

```powershell
# Check status of all services
.\parthenon.ps1 status

# Start all services (infra → backend → frontend)
.\parthenon.ps1 start

# Start specific services
.\parthenon.ps1 start -Services backend

# Stop all services
.\parthenon.ps1 stop

# Restart with force (skip prompts)
.\parthenon.ps1 restart -Force
```

See [PARTHENON-SCRIPT-GUIDE.md](PARTHENON-SCRIPT-GUIDE.md) for detailed usage.

### Manual Start

```bash
# Start infrastructure only
docker compose up -d

# Backend dev
cd backend && pip install -e ".[dev]" && uvicorn app.main:app --reload

# Frontend dev
cd frontend && npm install && npm run dev
```

## Project Structure

```
Parthenon/
├── backend/        # FastAPI application
├── frontend/       # React SPA
├── e2e/            # End-to-end tests
├── infra/          # Docker Compose, Helm, nginx config
└── docs/           # Documentation
```
