# Agent Execution Flow (Business Overview)

## Overview
Agent execution in Parthenon is governed by a secure, auditable, and policy-driven process. Each agent instance is authenticated using a unique certificate, and all identity management is centralized in the Control Center. Agents never receive or store identity tokens. Every tool call is explicitly authorized by the Control Center, ensuring that only valid, non-revoked agent instances can execute protected operations. This approach eliminates credential leakage risk and provides a centralized audit trail for all identity operations.

## Key Principles
- Agent runtime instances are authenticated using unique certificates
- Identity tokens are never distributed to agent runtimes
- All identity and authorization operations are managed centrally
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
- Compliance officers have a single audit trail for all agent actions
- SOP authors control when and what results are saved by including explicit save instructions
- Tool naming is predictable and consistent across all agent interactions

## Out of Scope
- Technical implementation details, code, or architecture diagrams
- Legacy agent execution models without certificate-based security

## Dependencies & Constraints
- Requires Control Center for certificate management and audit logging
- Relies on OIDC-compliant identity provider
- All changes must comply with Parthenon’s security and audit conventions
