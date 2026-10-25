# Demo Cases: software-3.0-agent-framework
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/software-3.0-agent-framework/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
- Agent Type Scripts tab — agent-owned script governance > Scripts tab lists the agent type script with description, lifecycle and health
- Agent Type Scripts tab — agent-owned script governance > version lineage with repaired_from and verification evidence are visible
- Agent Type Scripts tab — agent-owned script governance > Repairs list shows repair attempts recorded after fallback (E10)
- Agent Type Scripts tab — agent-owned script governance > operator promotes a version from the Scripts tab (asserted payload)
- Agent Type Scripts tab — agent-owned script governance > operator retires a version from the Scripts tab
- Agent Type Scripts tab — agent-owned script governance > plan review shows a script link on the script-backed step and opens the Scripts tab (E4a)
- Agent Type Scripts tab — agent-owned script governance > permission-gated promote surfaces via the dialog error pattern without crashing

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Scripts tab browsing | Operator opens the Agent Type detail dialog's Scripts tab and sees the agent-owned script with its human-readable description, lifecycle chip (Compiled) and health chip (Degraded). | e2e/tests/agent-type-scripts-tab.spec.ts | Scripts tab lists the agent type script with description, lifecycle and health |
| 2 | Version lineage & verification evidence | The tab lists all versions with derived / repair-of lineage badges; the Verifications sub-tab shows the Promoted verdict and the Fallbacks sub-tab explains the tool-schema-mismatch trigger with the repair-candidate outcome. | e2e/tests/agent-type-scripts-tab.spec.ts | version lineage with repaired_from and verification evidence are visible |
| 3 | Repairs history (self-improvement) | The Repairs sub-tab shows repair attempts recorded after fallback: defect diagnosis, retry outcome (Pending retry / Retry succeeded) and the applied diff. | e2e/tests/agent-type-scripts-tab.spec.ts | Repairs list shows repair attempts recorded after fallback (E10) |
| 4 | Lifecycle promotion | Operator promotes a version from the Scripts tab; the promote request is sent with `target_status: verified`. | e2e/tests/agent-type-scripts-tab.spec.ts | operator promotes a version from the Scripts tab (asserted payload) |
| 5 | Lifecycle retire | Operator retires a version from the Scripts tab; the retire action is sent and the version leaves active resolution. | e2e/tests/agent-type-scripts-tab.spec.ts | operator retires a version from the Scripts tab |
| 6 | Plan-step script link navigation | Plan review (Agent Preview) shows a Script link on the script-backed step only; clicking it lands in the Scripts tab of the same dialog. | e2e/tests/agent-type-scripts-tab.spec.ts | plan review shows a script link on the script-backed step and opens the Scripts tab (E4a) |
| 7 | Permission gating | A promote denied for missing `agent::scripts` manage permission surfaces the Permission Denied alert inside the dialog instead of crashing. | e2e/tests/agent-type-scripts-tab.spec.ts | permission-gated promote surfaces via the dialog error pattern without crashing |
