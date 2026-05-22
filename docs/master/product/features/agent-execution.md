# Agent Execution Flow (Business Overview)

## Overview
Agent execution in Parthenon is governed by a secure, auditable, and policy-driven process with explicit service segregation. Agent Runtime is restricted to approved execution responsibilities, while sensitive identity handling and data-access governance remain centralized in the Control Center. Agents never receive or store identity tokens. Runtime access to internal business operations is controlled through a dedicated allowlist for runtime-essential paths, with deny-by-default behavior for all other internal control paths. This reduces privilege overlap and strengthens boundary assurance.

## Key Principles
- Agent runtime instances are authenticated using unique certificates
- Identity tokens are never distributed to agent runtimes
- All identity and authorization operations are managed centrally
- Runtime access is limited to caller-specific, business-essential internal control paths
- Non-allowlisted internal control paths are denied by default
- Every tool call is authorized before execution
- All actions are logged for compliance and audit

## Unified Tool Naming Convention

All tools available to agents — whether built-in platform tools or external MCP server tools — follow the same naming convention: `server____tool_name` (four underscores separate server from tool name).

- **`system`** is the reserved server name for all built-in platform tools (e.g., `system____save_result`, `system____send_notification`, `system____get_recipient_group`)
- **MCP server names** must not contain `____` — this separator is reserved for the naming scheme
- Agent execution code makes no distinction between system tools and MCP server tools — all tool calls are forwarded uniformly to the Communication Hub for routing

This convention ensures tool names are globally unique across all registered servers and routing is deterministic.

## Explicit Result Saving

The agent runtime does **not** automatically save results at the end of execution. If an SOP or agent instruction requires a result to be persisted, the agent must explicitly call the `system____save_result` tool. If no such instruction is given, no result record is created. This design ensures result creation is intentional and traceable to a specific SOP step.

## User Impact
- Security administrators can verify and revoke agent instances
- Platform operators do not manage or distribute identity tokens
- Compliance officers can verify evidence of both permitted and blocked access outcomes
- SOP authors control when and what results are saved by including explicit save instructions
- Tool naming is predictable and consistent across all agent interactions

## Out of Scope
- Technical implementation details, code, or architecture diagrams
- Legacy agent execution models without certificate-based security

## Dependencies & Constraints
- Requires Control Center for certificate management and audit logging
- Relies on OIDC-compliant identity provider
- Requires approved service-boundary policies and runtime allowlist governance
- All changes must comply with Parthenon’s security and audit conventions
