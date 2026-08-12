# Architecture Changes: Agent-to-Agent Communication and Slug Enforcement

## Changed Components
- Communication Hub: extended to route A2A requests by target agent type slug and coordinate dynamic target activation when unavailable.
- Agent Runtime: extended to create and attach dynamic receiver instances to requester session context.
- Permission Resolution Path: expanded to evaluate SOP-step-derived A2A allow rules in addition to existing tool-level controls.
- SOP Execution Definition Layer: delegation step definitions now generate agent association and permission mapping, consistent with current skill/tool derivation behavior.
- Plan Preview Layer: renders agent-delegation steps in both ordered plan and topology diagram outputs.
- Validation Layer: shared slug validation introduced across agent type, agent name, and MCP server naming paths.

## New Components
- A2A Session Link Manager: maintains requester-receiver session affinity and lifecycle state until explicit disconnect.
- Dynamic Receiver Lifecycle Controller: governs receiver create, active, disconnect, and remove transitions.

```mermaid
flowchart LR
  UI[Admin UI] --> HUB[Communication Hub]
  HUB --> PERM[Permission Resolver]
  PERM --> SOPPOL[SOP A2A Policy]
  HUB --> REG[Agent Registry]
  REG --> RT[Agent Runtime]
  RT --> LIFECYCLE[Dynamic Receiver Controller]
  LIFECYCLE --> RECEIVER[Receiver Agent Instance]
  HUB --> REQUESTER[Requester Agent Instance]
  REQUESTER --> HUB
  RECEIVER --> HUB
  HUB --> MCP[MCP Gateway and Tools]
  HUB --> SYS[Internal Systems and Services]
  HUB --> AUDIT[Audit and Telemetry]
```

## Integration Points
- Agent Runtime and Communication Hub integration now includes target-availability callback and dynamic receiver provisioning request.
- Communication Hub is the single transport channel for all agent, MCP, and system communications; no direct peer-to-peer agent communication is allowed.
- SOP policy and permission resolver integration now includes delegation-step-derived target agent type slug evaluation.
- Agent role management view integrates allowed agent type slug preview from role assignment data.
- Agent plan preview integration renders delegation steps as first-class plan nodes and edges.
- Naming validation integration is shared across agent type management, agent identity naming, and MCP server registration/update.

## Data Flow Changes
- A2A request path now resolves target agent type by slug before dispatch, and all message exchange remains hub-mediated.
- SOP save/update flow derives A2A permission associations from delegation step definitions and publishes them to permission resolution.
- If no target instance is active, runtime provisions receiver and returns active endpoint binding to hub.
- Hub maintains both agents in one shared session channel until requester emits disconnect intent.
- Disconnect event triggers receiver cleanup and session-link removal.

```mermaid
sequenceDiagram
  participant Req as Requester Agent
  participant Hub as Communication Hub
  participant Perm as Permission Resolver
  participant Run as Agent Runtime
  participant Rec as Dynamic Receiver

  Req->>Hub: A2A request (target_agent_type_slug, payload)
  Hub->>Perm: Validate SOP allows target slug
  Perm-->>Hub: Allowed
  Hub->>Run: Resolve active target instance
  alt target unavailable
    Run->>Run: Create dynamic receiver instance
    Run-->>Hub: Receiver endpoint + session binding
  else target available
    Run-->>Hub: Existing receiver endpoint
  end
  Hub->>Rec: Forward A2A request in shared session
  Rec-->>Hub: Response/event
  Hub-->>Req: Response/event
  Req->>Hub: A2A disconnect
  Hub->>Run: Remove dynamic receiver instance
  Run-->>Hub: Cleanup complete
```

## Master Arch Update Instructions
- Update docs/master/architecture/system-overview.md with A2A routing and dynamic receiver lifecycle.
- Add or update module diagram in docs/master/architecture/modules/communication-hub.md to include SOP A2A permission check path.
- Add lifecycle states and cleanup semantics to docs/master/architecture/modules/agent-runtime.md.
- Add naming validation responsibility notes for shared validation layer in relevant module docs.
