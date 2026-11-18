# Token Expiry Alerting

## Overview
Agent identities and MCP sessions rely on refresh credentials that can expire. Previously, users discovered credential failures only when an agent execution failed mid-run, causing wasted work and eroding trust in scheduled workloads. Token Expiry Alerting makes credential health visible and actionable: the dashboard surfaces expired and soon-to-expire (within 7 days) credentials for agent identities and MCP sessions, warnings link directly to the re-authentication flow, agent execution is blocked up-front when a required credential is not usable, and the agent topology diagram reflects credential health at a glance.

## Business Goals
- Eliminate agent executions that fail due to expired credentials (target: zero within one release cycle)
- Reduce remediation time from "discovered at failure" to proactive alerting within the dashboard
- Increase reliability of scheduled (cron) agent workloads through pre-execution credential validation
- Cut support and troubleshooting effort related to authentication failures by removing the need for log inspection

## Who Uses It
- **Platform Administrators** — manage agent identities and MCP server sessions; need a single place to see which credentials are expired or expiring and fix them quickly
- **Agent Operators / Business Users** — launch agents and schedule SOPs; need assurance that executions will not fail for avoidable authentication reasons
- **Tenant Roots** — need tenant-wide health warnings visible on operational surfaces (dashboard, topology)

## What It Does
- Shows separate "expired" and "about to expire (within 7 days)" **refresh-token** indicators on the dashboard for agent identities and for MCP sessions, with counts. Access-token expiry is not an alert while the refresh token is valid, because access tokens are renewed automatically.
- Makes every dashboard credential warning clickable, navigating to the page where the user can refresh the identity or re-authenticate the MCP session
- Validates all refresh-token credentials an execution will use — including those of associated subagents — before the run starts; expired refresh tokens (or unrecoverable refresh failures) block execution with a clear message naming the identity/session to refresh
- Displays warning/error badges on agent topology containers whose bound identity or MCP session is expiring or expired
- Clears warnings automatically once the credential is refreshed or re-authenticated, returning the token-health tile to its green healthy state
- Prioritises actionable dashboard tiles: anything expired or expiring is sorted to the top with an "Action required" highlight

## Key Concepts
- **Refresh-Token Health States**: valid / expiring within 7 days / expired — applied to agent identities and to each named MCP session, driven by the refresh token's expiry. An identity with no refresh token falls back to its access-token expiry; an MCP session with no recorded refresh expiry does the same.
- **Pre-Flight Validation**: credential health check performed before any agent execution begins, covering the agent and all subagents
- **Warning-to-Remediation Routing**: direct navigation from a dashboard warning to the relevant remediation page

## Acceptance Criteria
- Dashboard shows "expired" and "about to expire (within 7 days)" as separate, clearly labeled **refresh-token** indicators for agent identities and MCP sessions; the identity list and session list label the status as refresh-token status and show the refresh-token expiry
- Each dashboard warning is clickable and navigates to the relevant agent identity page or MCP session page for refresh/re-authentication
- Before an agent executes, all refresh-token credentials the execution will use — including subagents' — are checked; expired refresh tokens (or unrecoverable refresh failures) block execution with a clear message identifying the affected identity/session; the run proceeds only after refresh/re-auth. A merely expired access token that can be refreshed does not block the run
- Users never discover a credential failure for the first time at execution time
- In the agent topology diagram, a container whose identity or MCP session expires within 7 days shows a warning state; an expired one shows an error state
- Warnings respect tenant isolation: users see only credentials in their own tenant
- Agents never receive or hold credential tokens; all refresh and resolution remains under Control Center's control
- Warnings disappear automatically once the credential is refreshed/re-authenticated

## Out of Scope
- Automatic re-authentication requiring interactive user consent (the user action remains manual)
- Extending token lifetimes or modifying identity provider token policies
- Alerts via notification channels (email/Slack/Teams) — dashboard, pre-flight, and topology surfaces only
- Credential health for model provider (LLM) API keys or notification integrations
- Historical credential-expiry analytics or audit reporting

## Dependencies & Constraints
- Depends on OIDC-compliant identity providers (Keycloak / Azure EntraID) exposing refresh-token expiry information the Control Center can evaluate; a provider that reports no refresh expiry results in no false warning (treated as having no known expiry)
- Agent identities live in the agent realm as first-class OIDC principals; alerting must align with the existing automatic refresh mechanism — the refresh token, not the short-lived access token, is the credential whose expiry matters
- MCP session expiry depends on the credential/identity binding of each named session per MCP server
- Agents never hold sensitive data including identity tokens; all token resolution and refresh stays in the Control Center
- Strict tenant isolation applies: credential health data and warnings are tenant-scoped end to end

## Multi-Tenancy Note

Token health data and warnings are tenant-scoped: users see and are alerted only about credentials within their own tenant. With multi-tenancy disabled (the default), behavior is unchanged — the deployment operates as the root tenant's workspace.
