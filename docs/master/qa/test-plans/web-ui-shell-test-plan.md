# Web UI Shell — Sidebar Navigation Test Plan

## Coverage Areas

### Structural integrity
- Sidebar renders 4 top-level entries: Dashboard (standalone) + Agents, Integrations, System groups
- Agents group has 11 children in spec order
- Integrations group has 5 children in spec order  
- System group has 3 children in spec order
- Dashboard is standalone (not inside any group)

### Interaction behavior
- All 3 groups expand/collapse on header click
- Expanding/collapsing one group does not affect others
- Active child item has selected state
- Active group header is visually indicated as active
- Deep link auto-expands parent group

### Visual fidelity
- Desktop drawer width: 256px
- Item font: 13px; child font: 11px
- Active state: rgba(0,0,0,0.06) bg, #2563EB accent, 8px radius

### Test files
- `frontend/src/__tests__/AppShell.test.tsx` (34 tests, Vitest)
- `e2e/tests/agent-navigation.spec.ts` (Playwright)
