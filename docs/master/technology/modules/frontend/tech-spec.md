# Module: frontend — Tech Spec

> Part of the [technology documentation](../../README.md).

## Overview

The frontend is a React 19 + TypeScript single-page application (Vite, Material-UI 7, React Router 7, i18next, React Query). This module documents the platform-wide UI infrastructure plus the agent, assistant and optimizer surfaces. Because the surface area spans several separable UI areas, the detail is split into focused pages.

The app is strictly an API/WebSocket client: it never holds database credentials, never talks to PostgreSQL, and never receives identity tokens. Tenant context travels as the `X-Tenant` header (per-tab resolved slug); conversation state travels over the Communication Hub WebSocket and is hydrated from the backend activity record on connect.

| Page | Covers |
|------|--------|
| [shell-and-rendering.md](shell-and-rendering.md) | MUI theme, app bootstrap, layout shell and sidebar, global styles, permission-error infrastructure, content/markdown rendering, execution result display, tenant/workspace frontend plumbing |
| [agent-surfaces.md](agent-surfaces.md) | Agent roles/identities/types/model-config pages, the Agent Management Panel (draft composition, resource picker, topology), implementation/optimized plan tabs, guardrail UI, API-key UI, skill tool-binding editor |
| [chat-surfaces.md](chat-surfaces.md) | Conversation dialog and session controls, intervention UI, assistant launcher/model guidance, resume/recovery rendering, the optimization chat surface |

Backend counterparts: [agents](../agents/tech-spec.md), [conversations](../conversations/tech-spec.md), [sandboxed-scripting](../sandboxed-scripting/tech-spec.md).

### Route map (top-level)

| Route | Surface | Page |
|-------|---------|------|
| `/` , `/dashboard` | Operational dashboard | shell |
| `/agents/panel` | Agent Management Panel | agent surfaces |
| `/agents/types`, `/agents/roles`, `/agents/identities`, `/agents/model-configs` | Agent CRUD | agent surfaces |
| `/agents/executions` (legacy `/agents/instances`) | Execution list + details dialog | agent surfaces |
| `/agents/runtime-control` | Agent Runtime Monitor | agent surfaces |
| `/agent-trails`, `/notifications` | Consolidated tabbed pages | shell |
| `/skills`, `/sops` | Skill/SOP management (binding editor) | agent surfaces |
| `/mcp/servers`, `/system/*` | Integrations and System Config | shell |
| `/platform/*`, `/tenant/*` | Platform console and tenant workspace | shell |
| `/login`, `/signup`, `/callback`, `/invitation/:token` | Auth surfaces | shell |

---

## UI invariants

- Every string is translated through `t()` (`en.json` is the only locale bundle).
- Every dialog that calls an API uses the Dialog Error Handling Standard: a `dialogError` state, clear-on-open/close, and `PermissionDeniedAlert` rendered first in the content.
- Permission gating is always a real backend evaluation (resource-type gate or probe) — never a feature-flag guess.
- Agent/assistant/optimizer conversations share one transport hook and one dialog; mode-specific chrome appears only for its mode.
- Plan generation is explicit (a user action), never a side effect of saving an agent.
- Long-lived surfaces (conversation, sessions view, optimizer chat) survive a reconnect: state is hydrated from the server, never reconstructed from transient client memory alone.

---

## Cross-cutting infrastructure

| Area | Responsibility | Home |
|------|----------------|------|
| API boundary | Single Axios instance with auth-header injection, 401 redirect, and 403 → permission-event dispatch; frontend is API/WebSocket-only (no DB transport) | [shell-and-rendering.md](shell-and-rendering.md) |
| Permission UX | Structured 403 parsing, global snackbar, "Request Access" modal, route-level access-denied page, dialog error standard | [shell-and-rendering.md](shell-and-rendering.md) |
| Theming and shell | Composed MUI theme, bootstrap providers, sidebar/nav groups, tabbed consolidated pages | [shell-and-rendering.md](shell-and-rendering.md) |
| Rendering | HTML detection/sanitisation, markdown conversion, maximizable content, typed/raw result display | [shell-and-rendering.md](shell-and-rendering.md) |
| Tenancy surfaces | Platform console, tenant workspace, sign-up/sign-in, `X-Tenant` binding and self-heal | [shell-and-rendering.md](shell-and-rendering.md) |
| Agent editing | Agent type form, management panel draft, resource pickers, topology canvas | [agent-surfaces.md](agent-surfaces.md) |
| Plans and optimization | Implementation plan, Optimized Plan tab, Optimize action, step tree, script viewer | [agent-surfaces.md](agent-surfaces.md) |
| Conversation UI | Chat dialog, status/activity bubble, sessions view, intervention cards, resume recovery | [chat-surfaces.md](chat-surfaces.md) |
| Assistant and optimizer chat | Assistant launcher/model guidance; optimization mode, ask/approve cards, audit bar | [chat-surfaces.md](chat-surfaces.md) |

All UI text goes through i18next `t()`; all dialogs with API calls follow the Dialog Error Handling Standard (`dialogError` + `PermissionDeniedAlert`).

---

## Code Reference Map — cross-cutting

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `API_CONFIG` | config object | Frontend REST and WebSocket base endpoints | `frontend/src/api/API_CONFIG.ts` |
| `apiClient` | axios instance | Auth-header injection; 401 → OIDC login; 403 → `parsePermissionError` + `dispatchPermissionDeniedEvent`; attaches `X-Tenant` and self-heals an unknown-slug rejection | `frontend/src/api/apiClient.ts` |
| `parsePermissionError` | function | Extracts `PermissionDeniedDetail` from a 403 body | `frontend/src/utils/permissionError.ts` |
| `dispatchPermissionDeniedEvent` / `PERMISSION_DENIED_EVENT` | function / constant | Decoupled permission-denied DOM event | `frontend/src/utils/permissionError.ts` |
| `PermissionErrorSnackbar` | component | Global 403 snackbar with "Request Access" | `frontend/src/components/permissions/PermissionErrorSnackbar.tsx` |
| `RequestPermissionModal` | component | Access-request modal prefilled from the denial context | `frontend/src/components/permissions/RequestPermissionModal.tsx` |
| `AccessDeniedPage` | component | Route-level 403 view | `frontend/src/pages/AccessDeniedPage.tsx` |
| `extractErrorMessage` | function | Shared unknown-error message extraction (Axios detail, Error message, fallback) | `frontend/src/utils/errorUtils.ts` |
| `extractOptimizeGateFailure` / `extractPlanGenerationReason` / `extractOptimizerRefusal` | functions | Structured `412`/`422`/refusal extraction for optimization surfaces | `frontend/src/utils/errorUtils.ts` |
| `useDialogErrorHandler` | hook | Dialog Error Handling Standard helper | `frontend/src/hooks/useDialogErrorHandler.ts` |
| `RESOURCE_TYPE_MANIFEST` / `MODULE_GROUPS` | constants | Frontend mirror of the backend resource-type manifest (slot/sidebar gating) | `frontend/src/constants/resourceTypes.ts` |
| `service-segregation-security-audit` | test | Verifies the frontend stays API/WS-only (no DB transport) | `frontend/src/__tests__/service-segregation-security-audit.test.ts` |
