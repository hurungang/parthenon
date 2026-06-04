# Frontend Test Plan

Covers frontend component tests and E2E UI tests for all frontend-specific concerns including theming, accessibility, and visual consistency.

---

## Coverage Areas

### 1. Material UI Theming

**What is tested:**
- Global theme configuration: palette (indigo primary, slate neutrals), typography (Inter font), shadows, and border radius overrides
- Individual MUI component overrides: AppBar, Drawer, Button, Card, TextField, Chip, Dialog, and others
- Theme consistency across all major application pages
- No visual regressions from legacy styles (Roboto font, old palette, incorrect border radius)

**Acceptance criteria:**
- Inter font applied globally; Roboto absent
- Primary color is indigo (#4f46e5); slate/neutral palette for backgrounds and surfaces
- Cards and relevant components use 12px border radius
- Refined, consistent shadows on all elevated surfaces
- All component overrides match design specification

**Test files:**
- [frontend/src/__tests__/theme.spec.tsx](../../../../frontend/src/__tests__/theme.spec.tsx) — Unit tests for theme configuration (palette, typography, shadows, component overrides)
- [e2e/tests/theme-application.spec.ts](../../../../e2e/tests/theme-application.spec.ts) — E2E: global font and color application
- [e2e/tests/component-theming.spec.ts](../../../../e2e/tests/component-theming.spec.ts) — E2E: component-level styling (cards, AppBar, buttons)
- [e2e/tests/page-consistency.spec.ts](../../../../e2e/tests/page-consistency.spec.ts) — E2E: theme consistency across all major pages

---

### 2. Accessibility

**What is tested:**
- WCAG AA color contrast for text and interactive elements
- Visible focus indicators on all interactive components
- Keyboard navigation through themed components
- Screen reader compatibility for themed UI

**Acceptance criteria:**
- All foreground/background color pairs meet WCAG AA contrast ratio (≥ 4.5:1 for normal text, ≥ 3:1 for large text)
- Focus outlines visible on all interactive elements
- No accessibility regressions introduced by theme changes

**Test files:**
- [e2e/tests/accessibility.spec.ts](../../../../e2e/tests/accessibility.spec.ts) — Automated WCAG AA checks across themed pages

---

### 3. General UI Smoke (Cross-feature)

Core pages and flows verified to render correctly:

| Area | Spec File |
|------|-----------|
| Authentication flows | e2e/tests/test-login-flow.spec.ts |
| Dashboard / app shell | e2e/tests/dashboard.spec.ts |
| Sidebar navigation: 3-group structure (Agents: 11 children, Integrations: 5 children, System: 3 children) + Dashboard standalone | frontend/src/__tests__/AppShell.test.tsx (34 tests), e2e/tests/agent-navigation.spec.ts |
| Agent Management | e2e/tests/agent-management.spec.ts |
| Chat | e2e/tests/chat.spec.ts |
| Conversations | e2e/tests/conversations.spec.ts |
| MCP Hub | e2e/tests/mcp-hub.spec.ts |
| Skills & SOPs | e2e/tests/skills-sops.spec.ts |
| Permissions (Tags, Roles, Groups, Users, Access) | e2e/tests/permissions.spec.ts |
| Setup Wizard | e2e/tests/setup-wizard.spec.ts |

---

### 4. Passthrough Session UI

**What is tested:**
- McpSessionManager: passthrough option present in auth type selector; all credential input fields hidden when selected; informational alert displayed; submit payload omits credentials; passthrough chip shown in session table
- McpSessionManager: switching between passthrough and credential auth types toggles credential field visibility without page reload
- TestMcpToolDialog: for a server whose active session has `auth_type === 'passthrough'`, session picker is replaced by an agent identity picker; submit payload includes `session_id` and `agent_subject`
- TestMcpToolDialog: for a server with a non-passthrough session, existing session picker renders unchanged
- AssignMcpSessionsToRoleDialog: passthrough sessions display a "Passthrough" chip badge; sessions remain selectable; one-session-per-server toggle UI not shown for passthrough sessions

**Acceptance criteria:**
- Credential fields are completely hidden (not just disabled) when passthrough is selected
- Identity picker in TestMcpToolDialog is populated from the agents API
- Passthrough chip rendered in all relevant session lists without page reload
- No regression in non-passthrough session flows

**Test files:**
- [frontend/src/__tests__/McpSessionManager.test.tsx](../../../../frontend/src/__tests__/McpSessionManager.test.tsx) — credential field hiding, informational alert, passthrough chip, submit payload, auth type toggle
- [frontend/src/__tests__/TestMcpToolDialog.test.tsx](../../../../frontend/src/__tests__/TestMcpToolDialog.test.tsx) — identity picker rendered for passthrough server; session picker absent; correct payload on submit
- [frontend/src/__tests__/AssignMcpSessionsToRoleDialog.test.tsx](../../../../frontend/src/__tests__/AssignMcpSessionsToRoleDialog.test.tsx) — passthrough badge, session selectable, toggle constraint not shown
- [e2e/tests/passthrough-sessions.spec.ts](../../../../e2e/tests/passthrough-sessions.spec.ts) — mocked UI flow: admin creates passthrough session, chip displayed, identity picker shown in tool test dialog; `test.describe('Real Backend Integration')`: unauthenticated tool test returns correct status, passthrough+credentials rejected

---

### 5. Service Segregation Security Audit (UI Boundary)

**What is tested:**
- Browser traffic for dashboard/user flows remains on API and WebSocket boundaries only
- Frontend does not attempt direct database channels (`postgres`, `supabase`, or `:5432` network targets)
- Boundary-safe client behavior remains consistent while backend deny-path hardening is in effect

**Acceptance criteria:**
- At least one dashboard journey shows API boundary calls and zero direct database traffic attempts
- Frontend boundary assertions remain green alongside real-backend internal deny-path probes

**Test files:**
- [frontend/src/__tests__/service-segregation-security-audit.test.ts](../../../../frontend/src/__tests__/service-segregation-security-audit.test.ts) — boundary-safe client behavior checks for service segregation assumptions
- [e2e/tests/service-segregation-security-audit.spec.ts](../../../../e2e/tests/service-segregation-security-audit.spec.ts) — browser API/WS-only boundary verification and real-backend deny-path wiring checks

---

## Edge Cases & Risks

- Font loading failure causes fallback to Roboto or system fonts — must be caught by theme-application tests
- Custom or third-party components that bypass MUI theme (e.g., inline styles) may not inherit overrides
- Color contrast failures in disabled, secondary, or placeholder states
- Browser-specific font rendering differences (font-smoothing, subpixel anti-aliasing)
- Rare dialogs and error pages that lack E2E coverage

---

## Change History

| Change | Description | Added |
|--------|-------------|-------|
| apply-material-theme | Material UI theming: Inter font, indigo palette, component overrides, WCAG AA | 2026-04-30 |
| unified-agent-navigation | Added agent-navigation.spec.ts to General UI Smoke table | 2026-05-10 |
| passthrough-sessions | Added section 4: Passthrough Session UI (McpSessionManager, TestMcpToolDialog, AssignMcpSessionsToRoleDialog) | 2026-05-12 |
| service-segregation-security-audit | Added section 5: Service Segregation Security Audit (UI boundary enforcement and deny-path integration checks) | 2026-05-22 |
| reorg-navigation-menu | Updated sidebar navigation from "AI Agent" group + "Notifications" submenu to 3-group structure (Agents: 11 children, Integrations: 5 children, System: 3 children) + Dashboard standalone. AppShell test suite expanded from 5 to 34 tests covering the new structure. | 2026-06-04 |
