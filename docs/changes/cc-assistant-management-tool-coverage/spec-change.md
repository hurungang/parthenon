# Spec Change: Control Center Assistant Management Tool Coverage

## Affected Spec Areas

- [Control Center Assistant](../../../master/product/features/control-center-assistant.md) — assistant management tool coverage, confirm-before-write behavior
- [Control Center](../../../master/product/features/control-center.md) — internal management operations surfaced to the assistant
- [Agent Types](../../../master/product/features/agent-types.md) — full agent-type configuration manageable via conversation
- [Agent Identity](../../../master/product/features/agent-identity.md) — role assignment management via conversation
- [Agent Management](../../../master/product/features/agent-management.md) — agent role management parity
- [Skill Management](../../../master/product/features/skill-management.md) — skill create/update parity
- [SOP Management](../../../master/product/features/sop-management.md) — SOP create/update parity
- [Model Configurations](../../../master/product/features/model-configurations.md) — model config management parity
- [Schedule Management](../../../master/product/features/schedule-management.md) — schedule management parity
- [Agent Data Types](../../../master/product/features/agent-data-types.md) — data type management parity
- [MCP Hub](../../../master/product/features/mcp-hub.md) — MCP server registration/update parity
- [Foundation Platform](../../../master/product/features/foundation-platform.md) — permission parity and tenant scoping for conversational management

## New Capabilities

- **Full-field conversational updates**: the assistant can change every attribute of an assistant-managed resource that the corresponding web UI edit form supports — including previously unsupported fields such as an agent type's role assignment, input/output configuration, structured input/output definitions, system instruction, bindings, and guardrails, and an agent identity's role assignments.
- **Complete conversational creation**: create operations for all assistant-managed families accept the same completeness of configuration as the web UI create forms.
- **Rich conversational reads**: list/get operations expose the same information the web UI list and detail views show, enabling accurate assistant answers about existing resources.
- **Self-correctable validation**: when the assistant submits an invalid or incomplete request, it receives structured, actionable feedback identifying the offending field and expected input, enabling retry without user diagnosis.
- **Permission-denied transparency**: when the requesting user lacks permission for a conversational management action, the assistant receives a clear denial it can relay accurately.

## Modified Capabilities

- **Assistant update tools (before → after)**
  - Before: update tools accept only a subset of fields; unsupported fields are silently dropped or rejected, forcing the assistant to end the task with "cannot be made through the management API."
  - After: update tools accept every field the web UI edit form supports; approved changes apply fully in one conversational flow.
- **Tool parameter descriptions (before → after)**
  - Before: loosely defined tool inputs; some operations fail with generic validation errors (e.g. "slug is required") that the assistant cannot interpret.
  - After: each tool exposes precisely named, self-describing parameters per resource, with per-field validation errors the model can act on.
- **Assistant create tools (before → after)**
  - Before: create tools accept a reduced configuration compared to UI forms.
  - After: create tools accept full UI-form-equivalent configuration, subject to the existing preview-and-approval flow.
- **Management routing (before → after)**
  - Before: routing layer passes a reduced field set between the assistant tool call and Control Center management operations.
  - After: routing preserves the full field set end-to-end so approved conversational changes match UI-driven changes exactly.

## Removed Capabilities

- None. Deletion remains unavailable through the assistant (unchanged policy); no existing assistant capability is withdrawn.

## Spec Update Instructions

- **control-center-assistant.md**: update the management-tools section to state full UI-parity coverage for all assistant-managed resource families; document the self-correctable validation behavior and permission-denied transparency; reaffirm confirm-before-write and no-deletion policy.
- **control-center.md**: update the internal management operations description to reflect full-field acceptance for assistant-driven create/update/read operations and parity enforcement with web UI behavior.
- **agent-types.md**: document that all agent-type configuration (role, input/output definitions, instruction, guardrails, bindings) can be created and updated via assistant conversation with approval.
- **agent-identity.md / agent-management.md**: document conversational management of identity role assignments and agent roles at UI parity.
- **skill-management.md / sop-management.md / model-configurations.md / schedule-management.md / agent-data-types.md / mcp-hub.md**: note in each that assistant management tools cover the same create/update/read capability set as the web UI.
- **foundation-platform.md**: add the permission-parity rule for conversational management (same per-resource actions as UI, executed under the user's identity, tenant-scoped).
- **qa test plans (docs/master/qa/)**: add parity test coverage — for each resource family, every UI-editable field must be verifiable through a conversational update, plus validation-feedback and permission-denial scenarios.
