# Spec Delta: Control Center Assistant (Chatbot)

## Affected Spec Areas

| Spec Area | Link | Impact |
|---|---|---|
| Control Center | `../../master/product/features/control-center.md` | Gains an embedded conversational assistant surface |
| Agent Management | `../../master/product/features/agent-management.md` | Management actions become reachable via natural language |
| Agent Types | `../../master/product/features/agent-types.md` | Create/configure agent types via assistant |
| Skill Management | `../../master/product/features/skill-management.md` | Create/update skills via assistant |
| SOP Management | `../../master/product/features/sop-management.md` | Add/update SOPs via assistant |
| Agent Identity | `../../master/product/features/agent-identity.md` | Manage identities via assistant |
| Model Configurations | `../../master/product/features/model-configurations.md` | Create/configure model configs via assistant |
| Schedule Management | `../../master/product/features/schedule-management.md` | Manage schedules via assistant |
| MCP Hub | `../../master/product/features/mcp-hub.md` | Manage MCP Hub connections via assistant |
| Agent Data Types | `../../master/product/features/agent-data-types.md` | Create/configure data types via assistant |
| Agent Data / Outputs | `../../master/product/features/agent-data.md`, `agent-outputs.md` | Read/query scope via assistant (no deletion) |
| Conversation Management | `../../master/product/features/conversation-management.md` | Existing conversational infra extended to a management-scoped assistant |
| Agent Runtime Security | `../../master/product/features/agent-runtime-security.md` | Reinforces delegated, no-elevation, no-direct-DB access guarantees |

## New Capabilities

- **Control Center assistant (conversational chat)** — an embedded conversational assistant in the Control Center web UI that interprets natural-language management requests.
- **Natural-language management of the full Agents menu group** — create, update, and configure actions across the complete `agent::*` resource type namespace: `agent::api_keys`, `agent::roles`, `agent::identities`, `agent::management`, `agent::runtime_control`, `agent::skills`, `agent::sops`, `agent::model_configs`, `agent::schedules`, `agent::trails`, `agent::human_intervention`, `agent::data_types`, `agent::data`, `agent::outputs`, `agent::scripts`.
- **Delegated on-behalf-of action model** — the assistant acts on behalf of the logged-in user, inheriting and never exceeding the user's permission scope; every action is attributed to the user.
- **Conversational read/query** — the assistant can describe current agent configuration (roles, identities, schedules, model configs, etc.) consistent with the UI.

## Modified Capabilities

- **Control Center UI** — *before:* agent administration is manual-only (forms, dialogs, tabs). *after:* a conversational assistant offers an additional natural-language path for the same management actions; existing manual workflows are unchanged.
- **Conversation management** — *before:* conversational infrastructure serves product agents and agent-to-agent/SOP conversations. *after:* it additionally serves a management-scoped assistant bound to a user's session and permission scope.
- **Agent resource management** — *before:* create/update/configure reachable only through dedicated UI forms. *after:* the same operations are reachable through the assistant, subject to identical permission enforcement.

## Removed Capabilities

- None. No existing capability is removed. Manual forms, dialogs, and permission enforcement remain unchanged. Note: **no deletion capability is added at this stage** — the assistant explicitly declines delete requests and any action outside the Agents menu group.

## Spec Update Instructions

- Add a new feature spec (or extend `control-center.md`) documenting the assistant: its embedded surface, its scope (Agents menu group only), the delegated on-behalf-of permission model, and the no-deletion / no-out-of-scope boundary.
- Enumerate assistant coverage across the `agent::*` submodules listed under **New Capabilities**, and state explicitly which actions are supported (create/update/configure/read) versus unsupported (delete).
- Update `conversation-management.md` (and `software-3-0-agent-framework.md` as relevant) to note the management assistant as a new consumer of the existing conversational-agent infrastructure.
- Reinforce in `agent-runtime-security.md` the assistant's security invariants: acts on behalf of the user, never exceeds the user's permissions, no direct database access, and no exposure of sensitive data (identity tokens, database credentials, decrypted credentials).
- Keep all new spec text in business language — no API, schema, or implementation detail.
