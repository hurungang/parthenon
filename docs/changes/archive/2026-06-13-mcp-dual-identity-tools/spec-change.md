# MCP Dual-Identity Tools — Specification Delta

## 1. Affected Spec Areas

| Spec Area | Document | Impact |
|-----------|----------|--------|
| MCP Demo App — Product Requirements | [`docs/master/product/features/mcp-demo-app.md`](../../master/product/features/mcp-demo-app.md) | **High** — New tools, dual-identity validation, updated acceptance criteria |
| MCP Demo App — Technical Specification | [`docs/master/technology/modules/mcp-demo-app/tech-spec.md`](../../master/technology/modules/mcp-demo-app/tech-spec.md) | **High** — New tool handlers, dual-identity extraction, claim-based access control |
| MCP Demo App — Test Plan | [`docs/master/qa/test-plans/mcp-demo-app-test-plan.md`](../../master/qa/test-plans/mcp-demo-app-test-plan.md) | **High** — New test cases for helloAgent, helloUser, role enforcement, and access-denied scenarios |
| MCP Hub — Product Requirements | [`docs/master/product/features/mcp-hub.md`](../../master/product/features/mcp-hub.md) | **Low** — Reference to dual-identity validation capability in demo app context |

## 2. New Capabilities

- **Dual-identity validation**: The MCP Demo App now validates that both user identity and agent identity JWTs are forwarded independently by the Communication Hub, proving the full identity propagation chain.
- **Per-identity role-based tool access control**: Two new tools (`helloAgent`, `helloUser`) each gate access on a specific `mcp_role` claim from a specific identity — `helloAgent` requires `demo_agent` on the agent JWT, `helloUser` requires `demo_user` on the user JWT — demonstrating claim-based authorization at the tool level.
- **Independent identity claim inspection**: Each tool inspects only the identity relevant to its purpose. `helloAgent` validates and surfaces agent claims; `helloUser` validates and surfaces user claims. This proves that both identities are independently accessible and that identity-bound authorization is correctly scoped.
- **Clear access-denied signalling**: When an identity lacks the required `mcp_role` claim, the tool returns a structured access-denied response (not a generic error), enabling automated test assertions and operational monitoring.
- **Dual-identity setup documentation**: The demo app README includes step-by-step instructions for configuring both Keycloak realms with the required `mcp_role` claims and test identities, making the setup reproducible for partners and internal teams.

## 3. Modified Capabilities

| Capability | Before | After |
|------------|--------|-------|
| Tool inventory | `tools/list` returned exactly **one** tool: `helloWorld` | `tools/list` returns **three** tools: `helloWorld`, `helloAgent`, `helloUser` with distinct descriptions and input schemas |
| Agent identity surfacing | `helloWorld` greeted the agent identity but did not enforce any role-based access control | `helloWorld` continues to greet the agent identity without role gating (unchanged behavior). New tools add role-gated identity surfacing for both user and agent identities. |
| Identity validation scope | Only the agent identity JWT was validated and used | Both user identity and agent identity JWTs are independently validated, with each tool using only the identity relevant to its access control decision |
| Demo app README | Single-identity setup instructions | Dual-identity setup instructions covering both user realm and agent realm configuration, `mcp_role` claim setup, and verification steps for all three tools |

## 4. Removed Capabilities

None. The existing `helloWorld` tool and all current demo app behavior remain unchanged. No existing endpoints, authentication flows, or Hub registration behaviors are removed.

## 5. Spec Update Instructions

### `docs/master/product/features/mcp-demo-app.md`
- Update "Epic Overview" section to mention dual-identity validation alongside the existing single-identity proof
- Replace or extend "Business Goals" to include measurable outcomes for dual-identity and role-based access control validation
- Add user stories for the new `helloAgent` and `helloUser` tools
- Expand "Acceptance Criteria" with the new tool-specific criteria (helloAgent accessible only with demo_agent role, helloUser only with demo_user role, access-denied behavior, tools/list returning three tools)
- Update "Out of Scope" if needed (note that Communication Hub changes remain out of scope; only the demo app changes)
- Ensure "Dependencies & Constraints" reflects the need for both user and agent realm identities with specific mcp_role claims

### `docs/master/technology/modules/mcp-demo-app/tech-spec.md`
- Add new tool handler functions (`hello_agent_tool`, `hello_user_tool`) to the component breakdown table
- Update `TOOL_MANIFEST` description to indicate three tools instead of one
- Add `verify_user_jwt` or equivalent function for independent user identity JWT validation
- Update the MCP JSON-RPC methods table to document `helloAgent` and `helloUser` tool descriptors
- Update the data access patterns section if dual-identity extraction requires new request-scoped state
- Update the code reference map with new symbols (new tool handlers, dual-identity extraction functions, updated manifest)

### `docs/master/qa/test-plans/mcp-demo-app-test-plan.md`
- Add unit test coverage for `hello_agent_tool` (returns greeting with agent claims when demo_agent role present; access-denied when absent; access-denied when no agent JWT)
- Add unit test coverage for `hello_user_tool` (returns greeting with user claims when demo_user role present; access-denied when absent; access-denied when no user JWT)
- Update `tools/list` test assertions to expect exactly **three** tool descriptors with correct names and schemas
- Add integration test scenarios: call `helloAgent` with a properly configured agent identity, call `helloUser` with a properly configured user identity, call each tool without the required role and verify access-denied response
- Update the acceptance criteria coverage matrix to include the new criteria
- Update the "Known Limitations" note if the new tests require additional service dependencies

### `docs/master/product/features/mcp-hub.md`
- In the "Key Concepts" section under "Agent Identity Validation", update the reference to note that the MCP Demo App now validates dual-identity propagation and per-identity role enforcement in addition to single-identity pass-through
- In "Acceptance Criteria", update the demo app reference to reflect that it validates both identities and claim-based access control
