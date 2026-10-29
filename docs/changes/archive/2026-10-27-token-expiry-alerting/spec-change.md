# Spec Change — Token Expiry Alerting

## Affected Spec Areas

- Dashboard metrics & operational health (dashboard stat cards and time-sensitive indicators)
- Agent Identities (identity lifecycle, token refresh, agent realm principals)
- MCP Hub / MCP Sessions (named session credential bindings per MCP server)
- Agent Execution (session submission and pre-execution validation)
- Agent Topology (unified topology canvas container states)
- Navigation & routing (deep links from operational warnings to remediation pages)

## New Capabilities

- **Token health indicators on the dashboard**: separate "expired" and "about to expire (within 7 days)" indicators for agent identities and for MCP sessions, with counts and click-through.
- **Warning-to-remediation routing**: clicking a dashboard token warning navigates to the page where the user refreshes the agent identity or re-authenticates the MCP session.
- **Execution token pre-flight**: before any agent execution starts, the platform validates that every token the run will use — including tokens of associated subagents — is valid; expired tokens block execution with an actionable message naming the identity/session to refresh.
- **Topology token health states**: container nodes in the agent topology diagram display a warning state when a bound identity or MCP session expires within 7 days, and an error state when expired.

## Modified Capabilities

- **Agent execution submission** — Before: executions proceed without token-health validation; authentication failures surface mid-run. After: submission performs a token pre-flight across the agent and all subagents; expired tokens block the run with a pre-execution alert, and the run proceeds only after refresh/re-auth.
- **Agent identities management** — Before: token refresh is automatic and failure is only visible as errors. After: identity pages also expose token health state (valid / expiring within 7 days / expired) and serve as the remediation target for dashboard warnings.
- **MCP sessions management** — Before: session credential expiry is invisible until tool calls fail. After: session listings expose token health state and serve as the remediation target for dashboard warnings.
- **Dashboard metrics** — Before: stat cards cover counts of entities; IdP status is de-emphasized. After: dashboard adds token-expiry warning indicators (identities and MCP sessions, split by expired vs. expiring) with permission-checked visibility, consistent with existing card behavior ("Permission Denied" placeholder instead of 403 errors).
- **Agent topology diagram** — Before: container states reflect composition/slot fill only. After: containers additionally render token-health warning/error badges derived from bound identity and MCP session states; the unified topology canvas remains the single canonical view.

## Removed Capabilities

- None. No existing capability is removed.

## Spec Update Instructions

- Add a "Token Health Alerting" subsection to the dashboard metrics spec describing the expired/expiring indicators for agent identities and MCP sessions, including click-through routing.
- Update the Agent Identities spec to define token health states (valid / expiring within 7 days / expired) and the refresh/re-auth remediation flow.
- Update the MCP Sessions spec to define token health states per named session and the re-authentication remediation flow.
- Update the Agent Execution spec to mandate pre-execution token validation covering subagents, blocking behavior, and user-facing alert content.
- Update the Agent Topology spec to add warning (expiring ≤ 7 days) and error (expired) container states driven by identity/MCP session token health, within the unified topology canvas.
- Add a constraint note to master specs: token health and refresh remain entirely under Control Center; agents never hold identity tokens; all token-health data is tenant-scoped.
- Update master navigation/routing spec with the new deep-link targets from dashboard warnings to identity and MCP session remediation pages.
