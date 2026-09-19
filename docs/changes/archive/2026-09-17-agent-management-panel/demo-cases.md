# Demo Cases: agent-management-panel
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/agent-management-panel/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Agent Management Panel — CRUD lifecycle > creates an agent from the panel and shows it in sidebar + header immediately (no reload)
- Agent Management Panel — equipment slots (inline create-and-assign) > role slot: create-new mounts the real Agent Role dialog and assigns the created role
- Agent Management Panel — live topology > topology updates immediately on draft mutations with zero network requests
- Agent Management Panel — Communication Hub in existing preview topologies > Agent Types details dialog shows the hub in a typed agent plan preview topology
- Agent Management Panel — permissions > 403 on the roles list disables only the role slot with a localized explanation
- Agent Management Panel — CRUD lifecycle > pending-changes tray saves the draft with exactly one agent-type PUT

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Agent CRUD lifecycle | Admin fills the Create Agent dialog (name, role, SOP binding); the saved agent appears in the sidebar and header immediately with the agent count updated and no page reload. | agent-management-panel.spec.ts | creates an agent from the panel and shows it in sidebar + header immediately (no reload) |
| 2 | Inline create-and-assign (role slot) | "Create new" in the role slot mounts the real Agent Role dialog (same title/fields as the source module); the persisted role lands on the draft instantly without leaving the panel. | agent-management-panel-slots.spec.ts | role slot: create-new mounts the real Agent Role dialog and assigns the created role |
| 3 | Live topology without saving | Unassigning and re-assigning the role re-renders the topology canvas instantly, proving zero network requests are fired until save. | agent-management-panel-topology.spec.ts | topology updates immediately on draft mutations with zero network requests |
| 4 | Communication Hub in preview topologies | The Agent Types details dialog (Agent Preview tab) appends the Communication Hub node with its dashed "platform messaging" edge to a typed agent's persisted plan topology, exactly once. | agent-management-panel-topology.spec.ts | Agent Types details dialog shows the hub in a typed agent plan preview topology |
| 5 | Permission degradation (403 slot disable) | A 403 on the roles list disables only the role slot with a localized explanation while every other slot keeps working and no error alert appears. | agent-management-panel-permissions.spec.ts | 403 on the roles list disables only the role slot with a localized explanation |
| 6 | Unsaved-changes tray / single-PUT save | Assigning a model dirties the draft with zero write calls and the tray lists the pending change; Save Changes issues exactly one agent-type PUT and flips the tray to saved. | agent-management-panel.spec.ts | pending-changes tray saves the draft with exactly one agent-type PUT |
