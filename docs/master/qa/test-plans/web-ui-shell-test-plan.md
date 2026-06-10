# Web UI Shell — Sidebar Navigation Test Plan

## Test Strategy

The Web UI shell is tested through Vitest component tests that verify structural rendering, interaction behaviour, and permission gating in isolation, and through Playwright E2E tests that validate the full navigation flow from sidebar click through page load. Visual fidelity is validated in Vitest via computed style assertions.

## Coverage Areas

### Structural integrity
- Sidebar renders 4 top-level entries: Dashboard (standalone) + Agents, Integrations, System groups
- Agents group has children in spec order
- Integrations group has children in spec order
- System group has children in spec order
- Dashboard is standalone (not inside any group)

### Interaction behavior
- All groups expand/collapse on header click
- Expanding/collapsing one group does not affect others
- Active child item has selected state
- Active group header is visually indicated as active
- Deep link auto-expands parent group

### Permission gating
- Sidebar items the user cannot access are hidden
- Group remains visible if at least one child is permitted
- Deep-linking to an unauthorized page shows appropriate error

## Critical Scenarios

- **WHEN** a user with full permissions loads the application, **THEN** all 4 top-level entries render with their children in the correct order, and all groups are collapsed by default except the active one.
- **WHEN** a user clicks a group header, **THEN** that group expands to show its children without affecting other groups.
- **WHEN** a user navigates to a page via a deep link, **THEN** the parent group auto-expands and the correct sidebar item is highlighted as active.
- **WHEN** a user lacks permission for a specific sidebar item, **THEN** that item is hidden but its parent group remains visible if at least one other child is permitted.
- **WHEN** a user lacks all permissions in a group, **THEN** the entire group is hidden from the sidebar.

## Edge Cases
- Rapid expand/collapse toggling does not leave sidebar in an inconsistent state
- Browser back/forward navigation correctly updates active sidebar state
- Window resize does not break sidebar layout or interaction

### Test files
- `frontend/src/__tests__/AppShell.test.tsx` (Vitest)
- `e2e/tests/agent-navigation.spec.ts` (Playwright)
