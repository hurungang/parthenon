# PRD — Token Expiry Alerting

## Epic Overview

Parthenon agent identities and MCP sessions rely on OAuth/OIDC refresh tokens that can expire. Today, users discover token failures only when an agent execution fails mid-run, causing wasted executions, confusing errors, and loss of trust in scheduled/automated workloads. This epic makes token health visible and actionable: the dashboard surfaces expired and soon-to-expire (within 7 days) tokens for agent identities and MCP sessions, warnings link directly to the re-authentication flow, agent execution is blocked up-front when a required token is not usable, and the agent topology diagram reflects token health at a glance.

## Business Goals

- Eliminate agent executions that fail due to expired tokens (target: zero token-failure executions within one release cycle).
- Reduce mean time to remediate expired credentials from "discovered at failure" to proactive alerting within the dashboard.
- Increase reliability of scheduled (cron) agent workloads by guaranteeing pre-flight token validation.
- Cut support/troubleshooting effort related to authentication failures by making token state visible without log inspection.

## Users & Personas

- **Platform Administrator** — manages agent identities and MCP server sessions; needs a single place to see which credentials are expired or expiring and fix them quickly.
- **Agent Operator / Business User** — launches agents and schedules SOPs; needs assurance that executions will not fail for avoidable authentication reasons.
- **Tenant Root** — responsible for tenant-wide health; needs warnings visible on operational surfaces (dashboard, topology) scoped to their tenant.

## User Stories

- As a platform administrator, I want to see separate counts of expired and expiring agent identity tokens on the dashboard, so that I can prioritize re-authentication work.
- As a platform administrator, I want to see the same warning counts for MCP sessions, so that tool connectivity issues are caught before agents run.
- As an administrator, I want to click a token warning and land directly on the page where I can refresh the identity or re-authenticate the MCP session, so that remediation takes seconds.
- As an agent operator, I want the system to check token health before an agent (and its subagents) executes, so that I am never surprised by a mid-run authentication failure.
- As an agent operator, I want a clear pre-execution message naming which identity or session needs refresh, so that I know exactly what to fix.
- As an administrator, I want the agent topology diagram to show warning/error badges on containers whose identity or MCP session is expiring/expired, so that I can spot risk while designing or reviewing agents.

## Acceptance Criteria

- Dashboard shows "expired" and "about to expire (within 7 days)" states as separate, clearly labeled indicators for (a) agent identities and (b) MCP sessions.
- Each dashboard warning is clickable and navigates to the relevant agent identity page or MCP session page where the user can refresh/re-authenticate.
- Before an agent executes, all tokens the execution will use — including those of associated subagents — are checked; if any are expired, execution is blocked with a clear message identifying the affected identity/session, and execution proceeds only after refresh/re-auth.
- Users can never discover token failure for the first time at execution time; every expired token that would be used is surfaced before the run.
- In the agent topology diagram, a container whose identity or MCP session is within 7 days of expiry shows a warning state; an expired one shows an error state.
- Token health checks respect tenant isolation: users only see and are alerted about tokens in their own tenant.
- Agents never receive or hold tokens; all refresh and resolution remains under Control Center's control.
- Warnings disappear automatically once the token is refreshed/re-authenticated.

## Out of Scope

- Automatic re-authentication requiring interactive user consent (e.g., OIDC consent prompts) — the user action remains manual.
- Extending token lifetimes or modifying identity provider token policies.
- Alerting via notification channels (email/Slack/Teams) — dashboard, pre-flight, and topology surfaces only.
- Token health for model provider (LLM) API keys or notification integrations.
- Historical token-expiry analytics or audit reporting.

## Dependencies & Constraints

- Depends on OIDC provider behavior (Keycloak / Azure EntraID) exposing refresh token expiry information that Control Center can evaluate.
- Agent identities live in the agent realm and are managed as first-class OIDC principals; the alerting must align with the existing automatic refresh mechanism.
- Architectural constraint: agents never hold sensitive data including identity tokens; all token resolution/refresh stays in Control Center.
- Strict tenant isolation applies: token health data and warnings are tenant-scoped end to end.
- MCP session expiry depends on the credential/identity binding of each named session per MCP server.
