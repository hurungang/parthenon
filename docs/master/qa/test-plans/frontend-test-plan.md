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
| Authentication flows | e2e/tests/auth.spec.ts |
| Dashboard / app shell | e2e/tests/dashboard.spec.ts |
| Agent navigation structure, AI Agent nav group | e2e/tests/agent-navigation.spec.ts |
| Agent Management | e2e/tests/agent-management.spec.ts |
| Chat | e2e/tests/chat.spec.ts |
| Conversations | e2e/tests/conversations.spec.ts |
| MCP Hub | e2e/tests/mcp-hub.spec.ts |
| Skills & SOPs | e2e/tests/skills-sops.spec.ts |
| Permissions (Tags, Roles, Groups, Users, Access) | e2e/tests/permissions.spec.ts |
| Setup Wizard | e2e/tests/setup-wizard.spec.ts |

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
