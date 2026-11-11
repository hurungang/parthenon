"""Assistant knowledge base — queryable platform principles + reference facts.

A structured, deterministic (no-LLM) knowledge corpus distilled from the
ACTUAL platform specifications (``docs/config.yaml`` domain section and
``docs/master/product/features/``).  The Control Center Assistant surfaces
these rules on demand through the ``search_assistant_knowledge`` system
tool instead of carrying them verbatim in its system instruction — this
keeps the always-on context small while remaining answerable about the
platform composition model, model availability, naming rules, and
boundaries.

Each entry is either a GENERIC PRINCIPLE (completeness, prerequisite
ordering, grant-at-the-right-level, reuse-first, confirm-before-write,
no-delete) or a REFERENCE FACT (what a resource type is/needs) — never a
case-scripted workflow for one example scenario (FIX-20261102-100704).
Search is keyword-scored (token overlap weighted by rarity),
tenant-agnostic, and read-only — the corpus contains PLATFORM knowledge
only, never tenant data, so nothing sensitive can leak across tenants.
"""
from __future__ import annotations

from typing import Any

# ── Knowledge corpus ────────────────────────────────────────────────────────
#
# Distilled from docs/config.yaml (domain + conventions) and
# docs/master/product/features/ (skills, sops, agent types/roles/identities,
# model configs, MCP hub).  ``keywords`` drive retrieval; keep them the
# words a user would naturally type.

_KNOWLEDGE_ENTRIES: tuple[dict[str, Any], ...] = (
    {
        "id": "confirmation-preview-format",
        "topic": "CANONICAL CONFIRMATION PREVIEW FORMAT — bold title + Field/Value table",
        "keywords": [
            "confirmation preview format", "preview format", "format", "approval table",
            "markdown table", "layout", "template", "how to format", "confirm format",
            "preview table", "structure", "canonical", "table preview",
            "confirmation preview", "approval preview",
        ],
        "rule_text": (
            "CONFIRMATION PREVIEW FORMAT (canonical contract, "
            "FIX-20261101-223511): EVERY create/update confirmation — both "
            "the message shown to the user AND the human_intervene "
            "intervention prompt — uses EXACTLY this markdown layout: a bold "
            "title line, then one markdown table with the header "
            "'| Field | Value |' and one row per field. Title format: "
            "'**<Operation> <Resource Type>: <Name>**' (e.g. "
            "'**Create Skill: sql-runner**'). Updates list ONLY the changed "
            "fields, with the value showing old → new. For agent-type "
            "creation the table MUST include model, identity, role, skills, "
            "and grants rows. Every field the operation sets gets its own "
            "row — including enum choices (status, input_type, output_type, "
            "provider_type, guardrail modes), role/identity assignments "
            "(identity_id / role_id / role_ids), and list fields "
            "(skill_ids, sop_ids, tool_ids, tool_names, enabled_models); "
            "for list fields write the ADDED entries, e.g. "
            "'Skills (add) | sql-runner, report-gen' — existing entries are "
            "kept, nothing is removed. SOP create/update previews MUST show "
            "the ordered steps as numbered rows (e.g. 'Steps | 1. "
            "skill_invocation: check-credit-score, 2. agent_delegation: "
            "FraudCheckAgent'); updates show the full old → new step list "
            "because 'steps' REPLACES the whole list (omitted steps are "
            "deleted). Example:\n"
            "**Create Skill: sql-runner**\n"
            "| Field | Value |\n|-------|-------|\n"
            "| Operation | create |\n| Resource Type | skill |\n"
            "| Name | sql-runner |\n| Description | Runs SQL |\n"
            "| Tools (add) | supabase____run_sql |\n"
            "Never improvise other layouts — no bullet lists, no prose-only "
            "previews, no extra headings: consistency beats prose. The "
            "intervention prompt IS this table."
        ),
    },
    {
        "id": "structured-error-self-correction",
        "topic": (
            "STRUCTURED VALIDATION ERRORS — read field + remedy, fix, and retry "
            "autonomously"
        ),
        "keywords": [
            "validation error", "structured error", "retry", "fix", "self-correct",
            "400", "bad request", "invalid", "invalid enum", "unknown id",
            "unknown name", "404", "missing slug", "slug required", "conflict",
            "conversational", "typed output", "error payload", "remedy",
            "problems", "field", "correct", "resubmit",
        ],
        "rule_text": (
            "STRUCTURED-ERROR SELF-CORRECTION RULE: when a management create/"
            "update call fails validation, the error payload is STRUCTURED — "
            "{'error': 'validation_failed', 'problems': [{'field', 'problem', 'remedy'}, ...]}. "
            "Read the 'field' and 'remedy' of EACH problem, fix exactly "
            "those fields (never change unrelated ones), and RETRY the same "
            "call autonomously — you do not need to ask the user to retry; "
            "the user already approved the operation, you are only correcting "
            "the payload shape. Known failure shapes and their remedies: "
            "(1) MISSING SLUG (create_data_type / create_mcp_server without "
            "slug) — remedy names the URL-safe slug pattern "
            "(lowercase letters, digits, hyphens); derive the slug from the "
            "name (e.g. 'Incident Report' → 'incident-report') and retry. "
            "(2) INVALID ENUM (e.g. status='enabled', input_type='chat') — "
            "the remedy lists the allowed values; pick the closest allowed "
            "value (status: active/suspended/deprovisioned; input_type: "
            "none/typed/conversation; output_type: auto/typed/markdown; "
            "provider_type: openai/anthropic/...) and retry. "
            "(3) UNKNOWN ID/NAME (a reference field like role_id, "
            "identity_id, output_data_type_id, target_id, skill_ids) — 404 "
            "with no partial write; discover the correct entity with the "
            "list_* tools, use its exact id or name, and retry (see "
            "prerequisite-ordering if the entity must be created first). "
            "(4) CONVERSATIONAL-vs-TYPED-OUTPUT CONFLICT "
            "(input_type=conversation together with output_data_type_id) — "
            "conversational agent types cannot take a typed output data "
            "type; either drop output_data_type_id (keep it conversational) "
            "or change input_type to typed/none, matching what the user "
            "asked for, and retry. If the SAME problem persists after two "
            "corrections, stop and ask the user. A validation failure writes "
            "NOTHING — no rollback or cleanup is ever needed."
        ),
    },
    {
        "id": "resource-completeness",
        "topic": (
            "COMPLETENESS PRINCIPLE — every resource you create must be complete "
            "and functional in its own context"
        ),
        "keywords": [
            "complete", "completeness", "complete resource", "functional",
            "works", "work", "working", "make work", "not working", "broken",
            "incomplete", "shell", "bare", "missing", "what does it need",
            "what must it have", "requirements", "required", "references",
            "dependencies", "cannot act", "cannot run", "cannot function",
            "usable", "valid", "non-functional", "assemble", "fill in",
        ],
        "rule_text": (
            "COMPLETENESS PRINCIPLE (generic, applies to EVERY resource type — "
            "agent types, skills, SOPs, roles, identities, model configs, "
            "schedules, data types, MCP servers, ...). A resource you create or "
            "update must be COMPLETE and FUNCTIONAL in its own context: "
            "everything that resource needs in order to do its job must be "
            "present when it is written — required ids/references, bindings, "
            "grants, model, schema, target, and so on. WHAT 'complete' MEANS "
            "comes from the reference facts for that resource type, not from a "
            "universal checklist (agent types need an enabled model AND an "
            "identity or role carrying the capabilities they must use; skills "
            "need at least one tool binding to be able to do anything; SOPs "
            "need their constituent skills; schedules need a cron expression "
            "and a target; typed-output agent types need a data type). So: "
            "identify the resource type, consult its reference facts (search "
            "this knowledge), discover the required references with the "
            "discovery tools (list_*/get_*), include them in the payload, and "
            "for any value you cannot determine, mark the gap in the preview "
            "and ASK the user instead of writing a placeholder. A resource that "
            "cannot function in its context is a shell, never a valid "
            "creation."
        ),
    },
    {
        "id": "prerequisite-ordering",
        "topic": (
            "PREREQUISITE ORDERING PRINCIPLE — create what you reference before "
            "you reference it"
        ),
        "keywords": [
            "prerequisite", "prerequisites", "before", "before creating",
            "must exist", "does not exist", "doesn't exist", "missing",
            "order", "ordering", "sequence", "dependencies", "dependency",
            "depend", "reference", "referenced", "create first", "first",
            "cannot bind", "unknown id", "unknown name", "404", "not found",
            "chicken and egg", "what must exist",
        ],
        "rule_text": (
            "PREREQUISITE ORDERING PRINCIPLE (generic): a reference — a "
            "binding, a grant, an assignment, a target, or any id/name field — "
            "can only point at something that ALREADY EXISTS. If a capability "
            "or entity you need to reference does not exist yet, create it "
            "first and then reference it. The valid order is DERIVED from the "
            "dependency you just discovered (X references Y ⇒ Y must exist "
            "before X is written), never from a memorized script: an agent "
            "type that binds a skill needs the skill to exist; a skill that "
            "wraps an MCP tool needs that tool to exist on its server; a role "
            "grant needs the skill/SOP; an identity assignment needs the role. "
            "There is no single universal sequence that covers every request — "
            "resolve each dependency in turn, and if one cannot be satisfied, "
            "say what is missing and ask the user. Writing an unknown id/name "
            "fails with a structured 404 and no partial write, so resolve "
            "prerequisites first. A prerequisite the assistant creates is "
            "itself a write and follows the confirmation rule."
        ),
    },
    {
        "id": "reuse-first",
        "topic": (
            "REUSE-FIRST PRINCIPLE — prefer an existing compatible entity over "
            "inventing a new one"
        ),
        "keywords": [
            "reuse", "existing", "already exists", "duplicate", "new one",
            "compatible", "similar", "which role", "which identity",
            "which model", "look up", "list", "ask", "ambiguous", "prefer",
        ],
        "rule_text": (
            "REUSE-FIRST PRINCIPLE (generic): before creating anything, look "
            "for an existing entity that already fits (list_* discovery / "
            "search). Prefer a compatible existing model configuration, "
            "identity, role, skill, SOP, data type, or MCP server over a new "
            "near-duplicate — duplicates fragment permissions and names must "
            "be unique per tenant anyway. Create a new entity only when "
            "nothing suitable exists or the user explicitly wants one. When "
            "more than one candidate fits (two compatible roles, several "
            "enabled models, ...), do not guess: ask the user which one to "
            "use and show the candidates."
        ),
    },
    {
        "id": "skill-tool-binding",
        "topic": "A skill can only invoke tools BOUND to it — bind tools at creation",
        "keywords": [
            "skill", "tool", "bind", "binding", "tool_ids", "tool_names",
            "create_skill", "update_skill", "wrap", "wraps", "mcp tool",
            "attach tool", "associate tool", "cannot invoke", "no tools",
            "discover tool", "get_mcp_server", "cc____", "management capability",
        ],
        "rule_text": (
            "SKILL-TOOL BINDING RULE (FIX-20261101-000319): a skill can "
            "only invoke tools BOUND to it — a skill without bindings "
            "cannot do anything. When creating a skill that wraps an MCP "
            "tool, FIRST discover the tool: get_mcp_server returns the "
            "server's 'tools' list with canonical server____tool names "
            "(e.g. supabase____run_sql). THEN create the skill with "
            "tool_names and/or tool_ids in the data object (create_skill), "
            "or add them afterward via update_skill — bindings are "
            "additive and idempotent (re-binding is a no-op, nothing is "
            "ever removed, unknown tool → 404 with no partial write). "
            "cc____ tools are Control Center management capabilities — "
            "grant them to roles deliberately via the Control Center MCP "
            "entity, distinct from general system____ tools (save_data, "
            "get_data, human_intervene, script tools, etc.). "
            "ZERO-BINDING GUARD (FIX-20261101-223511): create_skill / "
            "update_skill return a 'warnings' entry when the skill has NO "
            "tools bound. If you see that warning, NEVER leave it as-is: "
            "discover the right tool (get_mcp_server 'tools' list) and bind "
            "it immediately via update_skill tool_ids/tool_names, then tell "
            "the user what you bound."
        ),
    },
    {
        "id": "confirm-before-write",
        "topic": "CONFIRMATION RULE — never create/update without prior human approval",
        "keywords": [
            "confirm", "confirmation", "approval", "approve", "approve first",
            "before creating", "before updating", "human_intervene", "intervene",
            "preview", "create", "update", "write", "safe", "sure", "accident",
            "reject", "rejected", "declined",
        ],
        "rule_text": (
            "CONFIRMATION RULE (hard, FIX-20261031-133253): before ANY "
            "invoke_management_tool call whose wrapped action is a CREATE or "
            "an UPDATE, you MUST: (1) build the EXACT payload; (2) present a "
            "markdown TABLE preview to the user — one row per field with "
            "field → value (for updates: field-by-field old → new changes); "
            "(3) call human_intervene with intervention_type='approval' and "
            "prompt = the same table preview, and WAIT for the response; "
            "(4) execute the create/update ONLY if the user approves. If "
            "the user rejects, do NOT execute — ask what to change and "
            "repeat the confirmation with the corrected preview. Read, "
            "list, and get actions need NO confirmation. Never batch an "
            "unconfirmed write: each create/update gets its own approval. "
            "The preview layout is CANONICAL (see the "
            "confirmation-preview-format knowledge entry): bold title line "
            "'**<Operation> <Resource Type>: <Name>**' + one '| Field | "
            "Value |' markdown table — never improvise another layout."
        ),
    },
    {
        "id": "agent-creation-completeness",
        "topic": (
            "REFERENCE FACT — what makes an agent type functional (enabled "
            "model + identity/role carrying the granted capabilities)"
        ),
        "keywords": [
            "agent creation", "create agent", "new agent", "agent type",
            "what does an agent need", "working agent", "make agent work",
            "complete agent", "bare", "shell", "model", "identity", "role",
            "grant", "grants", "list_agent_identities", "list_agent_roles",
            "list_model_configs", "non-functional", "incomplete",
            "prerequisites", "assemble",
        ],
        "rule_text": (
            "AGENT-TYPE REFERENCE FACT (the completeness principle applied to "
            "agent types): an agent type is functional only when it has (a) a "
            "model_id that exists in an ENABLED model of one of the tenant's "
            "Model Configurations (discover with list_model_configs) and (b) "
            "either an agent identity + role pair (list_agent_identities / "
            "list_agent_roles) whose role carries the skills/SOPs the agent "
            "must use, or direct skill/SOP bindings. Every execution validates "
            "that the type's identity is assigned to its role. An agent type "
            "without a working model AND (an identity or a role) is "
            "NON-FUNCTIONAL — a shell, never a valid creation. Because this is "
            "a fact about the resource type (not a script), the confirmation "
            "preview for an agent type shows model, identity, role, skills, "
            "and grants; any piece that is unknown is asked about or resolved "
            "before writing, and existing compatible entities are reused "
            "rather than recreated."
        ),
    },
    {
        "id": "creation-payload-completeness",
        "topic": "Include all required fields in any creation preview",
        "keywords": [
            "required fields", "payload", "fields", "complete payload",
            "gaps", "missing fields", "fill", "any resource", "creating",
            "preview", "defaults", "placeholder",
        ],
        "rule_text": (
            "When creating or updating ANY resource, gather and include ALL "
            "required fields in the confirmation preview — never submit a "
            "payload with unknown or placeholder values. If a required field "
            "is missing (name, model, type, target, ...), present the preview "
            "with the gap explicitly marked and let the user fill it BEFORE "
            "executing. What counts as 'required' for a given resource comes "
            "from its reference facts (see the resource-completeness entry and "
            "the per-resource facts); an agent type additionally needs the "
            "model + identity/role + granted-capability facts described in "
            "agent-creation-completeness."
        ),
    },
    {
        "id": "agent-type-composition",
        "topic": "Agent type composition — skills/SOPs, never raw MCP tools",
        "keywords": [
            "agent type", "compose", "composition", "skill", "sop", "mcp tool",
            "raw tool", "attach", "bind", "binding", "grant", "tools",
            "associate", "association", "link", "connect",
        ],
        "rule_text": (
            "REFERENCE FACT: agent types associate with SKILLS and SOPs — "
            "never with raw MCP tools. A skill wraps one or more MCP tool "
            "calls and is the permission-grantable unit, so an agent type gets "
            "tool access by binding skills (directly on the agent type) and/or "
            "through the role assigned to it. To give an agent type access to "
            "an MCP tool, a skill wrapping that tool must exist (create it "
            "when it does not — see prerequisite-ordering, there is no "
            "mandatory global order beyond that dependency) and then be bound "
            "or granted at the level the configuration consumes it. "
            "MECHANICS: skill_ids and/or sop_ids (ids or names, tenant-scoped) "
            "can be supplied in create_agent_type's data or added afterwards "
            "via update_agent_type; bindings are ADDITIVE — provided entries "
            "are added, existing bindings are never removed, re-binding an "
            "existing pair is an idempotent no-op, an unknown skill/SOP "
            "id/name returns 404. An agent type with no associated skill/SOP "
            "and no assigned role has no capabilities — that is an incomplete "
            "creation (see resource-completeness), so either associate the "
            "capabilities or explain to the user why not."
        ),
    },
    {
        "id": "skills-first-prerequisite",
        "topic": "Skill/SOP prerequisite — bindings and grants reference existing rows only",
        "keywords": [
            "create", "skill", "sop", "missing", "does not exist", "prerequisite",
            "first", "before", "new tool", "wrap", "created first",
        ],
        "rule_text": (
            "SKILL/SOP PREREQUISITE (an instance of the prerequisite-ordering "
            "principle): a role grant or an agent-type binding references "
            "EXISTING rows only, so a skill or SOP that does not exist yet "
            "must be created first — before anything can reference it. There "
            "is NO fixed global sequence beyond that dependency: whether you "
            "then grant it to a role, bind it directly to an agent type, or "
            "compose it into an SOP depends on the configuration at hand (an "
            "SOP composes existing skills with sequencing and may delegate to "
            "other agents). Derive the order from the dependency graph of the "
            "request, and ask the user when a prerequisite's shape is "
            "ambiguous."
        ),
    },
    {
        "id": "role-identity-chain",
        "topic": "Roles grant skills/SOPs; identities are assigned to roles",
        "keywords": [
            "role", "identity", "assign", "assignment", "permission", "grant",
            "agent role", "agent identity", "oidc", "many-to-many", "validate",
        ],
        "rule_text": (
            "REFERENCE FACT: Agent Roles are permission sets that grant access "
            "to SOPs and/or Skills; a role resolves to its complete set of "
            "allowed MCP tools. Agent Identities are first-class OIDC "
            "principals in the agent realm, and each identity is explicitly "
            "assigned to one or more roles via a many-to-many relationship. An "
            "agent type references an identity and a role, and every execution "
            "VALIDATES that the identity is assigned to the type's role. The "
            "dependency order follows from those relationships (the role and "
            "the identity must exist and the identity must be assigned to the "
            "role before an agent type can rely on that pair) — it is derived, "
            "not scripted."
        ),
    },
    {
        "id": "role-grant-workflow",
        "topic": (
            "GRANT-AT-THE-RIGHT-LEVEL PRINCIPLE — access comes from the "
            "permission model at the level the configuration consumes it"
        ),
        "keywords": [
            "role", "grant", "grants", "skill", "sop", "assign skill",
            "agent role", "role-based", "direct binding", "update_agent_role",
            "create_agent_role", "skill_ids", "sop_ids", "inaccessible",
            "cannot access", "cant", "can't", "access", "runtime access",
            "permission", "cannot use", "no tools", "agent access", "denied",
        ],
        "rule_text": (
            "GRANT-AT-THE-RIGHT-LEVEL PRINCIPLE (generic): access is granted "
            "through the platform's permission model, and it must be granted "
            "at the level the configuration actually consumes it. Reference "
            "facts: agent ROLES are permission sets that grant skills/SOPs "
            "(PERMISSION scope); agent TYPES define VISIBILITY — the agent "
            "only sees what is directly associated to it (its SOP/skill "
            "bindings), as a subset of the role's grants; identities are "
            "assigned to roles; both a role grant AND an agent-type "
            "association are needed for a tool to be visible at runtime. "
            "So when an agent cannot see an expected capability, grant it "
            "on the role (permission) AND associate it to the agent type "
            "(visibility) — a capability granted only on the role is "
            "INVISIBLE to agent types without the association. "
            "MECHANICS: create_agent_role / update_agent_role accept skill_ids "
            "/ sop_ids (ids or names, tenant-scoped); grants are additive and "
            "idempotent, existing grants are never removed, an unknown "
            "id/name returns 404. To diagnose 'why can't my agent access X', "
            "check the level the configuration uses (role vs direct binding) "
            "and whether the grant exists there — do not add a second grant at "
            "a random level."
        ),
    },
    {
        "id": "sop-only-router-roles",
        "topic": (
            "Role = permission, agent type = visibility — why an agent can't "
            "see an expected tool"
        ),
        "keywords": [
            "router", "router role", "delegation", "agent_delegation",
            "sop-only", "sop only", "visibility", "permission",
            "cannot see", "no tools", "missing tool", "tool not visible",
            "agent bindings", "skill bindings", "sop bindings",
            "delegation-style role", "role grants", "subset",
            "sop-only-router",
        ],
        "rule_text": (
            "ROLE-PERMISSION vs AGENT-VISIBILITY MODEL (correct semantics): a "
            "role controls PERMISSION only — what tools the role's grants "
            "(skills/SOPs) allow. An AGENT TYPE controls VISIBILITY: the "
            "agent sees only what is DIRECTLY ASSOCIATED to the agent type — "
            "its assigned SOPs (their skill_invocation steps' skills' tools, "
            "and agent_delegation steps' target agents for delegation) plus "
            "its direct skill bindings. The agent uses a SUBSET of what the "
            "role granted; role grants alone do NOT make a tool visible. So "
            "if an agent can't see an expected tool, associate the SOP/skill "
            "to the AGENT TYPE (agent-type bindings), not just the role. "
            "Conversely, extra role grants that are not agent-type-associated "
            "are correctly invisible — this is by design, not a warning "
            "condition; do not try to 'fix' a router agent that only sees "
            "its SOP's delegated agents. Search the knowledge for "
            "'sop-only-router'."
        ),
    },
    {
        "id": "model-availability",
        "topic": "Models must exist in a tenant Model Config's enabled models",
        "keywords": [
            "model", "model config", "enabled models", "available", "unavailable",
            "not available", "provider", "llm", "select model", "model_id",
            "disabled",
        ],
        "rule_text": (
            "An agent type's model must exist in the enabled-models list of a "
            "tenant Model Configuration (Model Config). Model Configs are "
            "centrally managed per provider with encrypted credentials and an "
            "explicit enabled model list; agent types reference a model id "
            "that is resolved to a config at runtime. If the requested model "
            "is not enabled on any of the tenant's model configs, add it to "
            "a config's enabled_models (update_model_config) or pick another "
            "enabled model. Conversational agent types use conversational "
            "model support; typed-output agent types additionally need "
            "provider-native structured output where enforced."
        ),
    },
    {
        "id": "io-types",
        "topic": "Input/output type rules — conversational vs typed outputs",
        "keywords": [
            "input type", "output type", "conversation", "conversational",
            "typed", "typed output", "data type", "schema", "none", "auto",
            "structured output",
        ],
        "rule_text": (
            "Agent types define input and output types. Input types include "
            "'none' and 'conversation'; output types include 'auto', text/"
            "markdown, and 'typed'. Typed outputs require an Agent Data Type "
            "(a reusable schema of typed fields: string, number, boolean, "
            "date, enum) assigned via output_data_type_id. CONVERSATIONAL "
            "agent types do NOT support typed outputs — they answer in plain "
            "conversation text. Data types cannot be deleted while referenced "
            "by agent types."
        ),
    },
    {
        "id": "mcp-hub-basics",
        "topic": "MCP Hub — slug uniqueness and sessions",
        "keywords": [
            "mcp", "mcp hub", "server", "slug", "session", "register",
            "connection", "namespace", "sync", "tools",
        ],
        "rule_text": (
            "Each registered MCP server has a slug that is UNIQUE PER TENANT "
            "(business identity is (tenant_id, slug)). All tools from a "
            "server are synced under the slug namespace and resolved within "
            "the calling tenant. Multiple named MCP sessions can be defined "
            "per server with different identity/credential bindings; a "
            "session can be mapped to an agent identity or a role. "
            "Credentials are stored encrypted (AES-256) and are never "
            "returned by management tools."
        ),
    },
    {
        "id": "naming-uniqueness",
        "topic": "Per-tenant name/slug uniqueness",
        "keywords": [
            "name", "unique", "uniqueness", "duplicate", "slug", "conflict",
            "409", "already exists", "rename",
        ],
        "rule_text": (
            "Most management resources are unique by display NAME within a "
            "tenant; MCP servers are unique by SLUG within a tenant; agent "
            "data types carry both a name and a slug. Creating a resource "
            "with a name/slug that already exists in the same tenant fails "
            "with 409 — pick a different name or update the existing "
            "resource instead."
        ),
    },
    {
        "id": "no-delete-boundary",
        "topic": "No delete — assistant cannot delete resources",
        "keywords": [
            "delete", "remove", "destroy", "drop", "deletion", "unassign",
            "cannot delete", "decline",
        ],
        "rule_text": (
            "Deletion is NOT supported through the assistant or the "
            "management tools: there is no delete verb registered for any "
            "management resource. If the user asks to delete something, "
            "decline clearly and explain that deletion is not available via "
            "the assistant; the user can delete resources through the "
            "management UI themselves."
        ),
    },
    {
        "id": "permission-parity",
        "topic": "Permission parity — every action runs inside the user's own scope",
        "keywords": [
            "permission", "denied", "forbidden", "403", "parity", "scope",
            "elevate", "authorize", "authorization", "allowed",
        ],
        "rule_text": (
            "Every management tool call is authorized against the SIGNED-IN "
            "USER's own permission scope using the same (resource_type, "
            "action) pair the equivalent REST endpoint enforces — the "
            "assistant has no elevated privileges. A denied call returns a "
            "structured permission error; explain that the user lacks the "
            "required permission and do not retry. Permission requirements "
            "per tool are listed by list_management_tools."
        ),
    },
    {
        "id": "sop-composition",
        "topic": "SOPs compose skills (and may delegate to agents)",
        "keywords": [
            "sop", "standard operating procedure", "compose", "sequence",
            "step", "delegate", "delegation", "workflow", "multi-step",
        ],
        "rule_text": (
            "REFERENCE FACT: SOPs (Standard Operating Procedures) are "
            "higher-level skills composed of multiple Skills with sequencing "
            "logic, and may include agent-to-agent delegation steps. Granting "
            "an SOP to a role makes its composed skills' tools available to "
            "that role's agents. The constituent skills must exist before the "
            "SOP can reference them (prerequisite-ordering); the composition "
            "order itself is whatever the procedure requires.\n"
            "HARD RULE: a SOP must NEVER mention or instruct direct "
            "MCP-tool calls — no 'server____tool' names in steps or "
            "instructions. Capability is expressed ONLY via agent_delegation "
            "and skill_invocation steps; if a capability lives in a raw "
            "tool, bind the tool into a SKILL and use a skill_invocation "
            "step.\n"
            "STEP AUTHORING (create_sop / update_sop 'steps'): a SOP is an "
            "ORDERED list of steps. A skill_invocation step references a "
            "skill by id or exact name (skill_id — REQUIRED for that step "
            "type); an agent_delegation step references a target agent type "
            "by id or exact name (target_agent_type_id — REQUIRED for that "
            "step type; delegation steps gate the role permissions of every "
            "role bound to the SOP)."
        ),
    },
    {
        "id": "sop-steps-replace-semantics",
        "topic": "SOP steps REPLACE the whole list on update — send the complete desired list",
        "keywords": [
            "sop step", "sop steps", "steps", "replace", "replace steps",
            "step list", "update sop", "create sop", "ordered steps",
            "step order", "delegation step", "skill_invocation",
            "agent_delegation", "step preview",
        ],
        "rule_text": (
            "SOP STEPS REPLACE SEMANTICS: the 'steps' array on create_sop / "
            "update_sop is a FULL-LIST REPLACE, never an additive merge — on "
            "update_sop, a present 'steps' array REPLACES the entire ordered "
            "step list and every step you omit is DELETED, so ALWAYS send the "
            "complete desired list; an absent 'steps' array leaves the "
            "existing steps untouched. Each step needs an integer 'order' and "
            "a step_type: skill_invocation steps REQUIRE skill_id (skill id "
            "or exact name); agent_delegation steps REQUIRE "
            "target_agent_type_id (agent type id or exact name) — a skill_id "
            "XOR target_agent_type_id, never both. In the canonical "
            "confirmation preview table, show the ordered steps as numbered "
            "rows (e.g. 'Steps | 1. skill_invocation: check-credit-score, "
            "2. agent_delegation: FraudCheckAgent'); on updates show the full "
            "old → new step list, and warn that omitted steps are deleted."
        ),
    },
    {
        "id": "sop-no-raw-tool-mentions",
        "topic": "HARD RULE — SOPs must never mention or instruct direct MCP-tool calls",
        "keywords": [
            "sop tool mention", "mcp tool in sop", "sop step rule",
            "sop raw tool", "tool name in step", "direct tool call in sop",
            "sop instructions tool", "server____tool in sop", "skill_invocation",
            "agent_delegation", "sop capability", "bind tool to skill",
            "tool visibility", "sop authoring rule",
            "mention", "raw", "instruct", "tool name", "mcp", "tool",
        ],
        "rule_text": (
            "HARD RULE — SOPs NEVER mention raw MCP tools: a SOP's step "
            "instructions must not name or instruct direct MCP-tool calls — "
            "no 'server____tool' names (e.g. 'mcp-demo____searchFlights') in "
            "any step description, instruction, or free text, and never tell "
            "an agent to 'call tool X yourself'. Tool visibility flows ONLY "
            "through SOP associations: a SOP expresses capability exclusively "
            "as agent_delegation steps (target agent type, id-or-name) and "
            "skill_invocation steps (skill, id-or-name). If a needed "
            "capability lives in a raw MCP tool, bind the tool into a SKILL "
            "(create_skill / update_skill tool bindings) and reference that "
            "skill with a skill_invocation step — never the tool directly."
        ),
    },
    {
        "id": "progressive-context",
        "topic": "How to discover and invoke management tools",
        "keywords": [
            "invoke", "invoke_management_tool", "tool schema", "which tools",
            "list tools", "how do i", "discover", "progressive", "wrapper",
        ],
        "rule_text": (
            "The full management tool set is NOT loaded into this "
            "conversation. Discovery pointer set: list_management_tools shows "
            "every available management action with its permission "
            "requirement; get_management_tool_schema returns one tool's exact "
            "argument schema before first use; invoke_management_tool("
            "tool_name, args) executes any of them; list_* reads the existing "
            "entities of a resource type; get_mcp_server returns a server's "
            "tools; search_assistant_knowledge returns the platform principles "
            "and reference facts. Understand the platform model with these "
            "before acting, and never guess a name, id, or required field."
        ),
    },
    {
        "id": "schedules",
        "topic": "Schedule management basics",
        "keywords": [
            "schedule", "cron", "cron_expression", "recurring", "trigger",
            "job", "target",
        ],
        "rule_text": (
            "Schedules are cron-based triggers for prompts/SOPs, managed via "
            "the admin UI and backed by a persistent job store. A schedule "
            "requires a cron_expression and a target (target_type + "
            "target_id, e.g. an agent type). Creating a schedule registers "
            "it with the scheduler; deletion is not available through the "
            "assistant."
        ),
    },
    {
        "id": "role-mcp-session-mappings",
        "topic": (
            "Agent roles need an MCP session mapped for every MCP server "
            "their skills touch, or the MCP tools will not work"
        ),
        "keywords": [
            "mcp session", "session mapping", "mcp_session_mappings",
            "passthrough", "oauth2", "external auth session", "role session",
            "agent role", "mcp tools not working", "credentials", "harry",
            "which session", "session warning", "auth type", "mapped session",
        ],
        "rule_text": (
            "REFERENCE FACT: MCP tools only work for an agent if its role has "
            "an MCP session mapped for each MCP server involved. Two kinds of "
            "sessions exist: passthrough sessions forward the agent's own "
            "identity to the MCP server, while external-auth sessions "
            "(bearer token, basic auth, oauth2) are named credential sessions "
            "configured on the server (for example identity test_agent_1 "
            "using session 'harry' on the supabase MCP server). MECHANICS: "
            "create_agent_role / update_agent_role accept mcp_session_mappings "
            "(a list of {server, session} objects, both id-or-name; the "
            "session must belong to the given server) — mappings are additive "
            "and one per server per role; re-mapping a server to a different "
            "session is a 409 conflict. DEFAULTS run automatically after "
            "explicit mappings so EVERY server ends up mapped: a server with "
            "a passthrough session defaults to passthrough; a server with "
            "exactly one session defaults to that session; a server with "
            "MULTIPLE sessions defaults to the FIRST one (is_default first, "
            "then oldest created) — the tool response carries a warnings "
            "list naming the defaulted session and the alternatives, and you "
            "MUST confirm the defaulted session with the user (offering the "
            "alternatives for re-mapping) before finishing. CRITICAL NAMING "
            "FACT: 'passthrough' "
            "is an auth TYPE, not a session name — NEVER pass "
            "session: 'passthrough' in a mapping. Explicit mappings are for "
            "EXTERNAL credential sessions only (for example {server: "
            "'supabase', session: 'harry'}); for servers whose session is "
            "passthrough-auth, NO explicit mapping is needed (the default "
            "rule auto-maps it) — or reference the actual session name "
            "(e.g. 'default'). If you mistakenly pass an auth type as a "
            "session name, the tool resolves it to that server's session "
            "with that auth type when one exists — but never rely on this; "
            "use the real session name from get_mcp_server. On every role "
            "create/update, check "
            "the returned warnings and confirm any defaulted multi-session "
            "mappings with the user before finishing. Confirmation preview rows for mappings use "
            "the form: supabase → session harry (oauth2). Sessions and "
            "credential material are never echoed — only the auth type."
        ),
    },
    {
        "id": "tenant-isolation",
        "topic": "Tenant scoping — one session, one tenant",
        "keywords": [
            "tenant", "workspace", "isolation", "scope", "cross-tenant",
            "another workspace",
        ],
        "rule_text": (
            "One session = one tenant. All management operations are "
            "tenant-scoped: you only ever see and modify resources belonging "
            "to the current tenant, and all permission grants apply only "
            "within it. Cross-tenant access is impossible through the "
            "management tools."
        ),
    },
    {
        "id": "cc-integration-protected",
        "topic": "Control Center integration — protected entity",
        "keywords": [
            "control center integration", "cc entity", "cc server",
            "protected integration", "control_center", "cannot see cc",
            "cc not visible", "control center permission",
        ],
        "rule_text": (
            "The Control Center integration (the 'cc' MCP entity hosting the "
            "cc____ management tools) is a protected integration: it is "
            "visible only to roles granted the "
            "integration::control_center permission ('read' to view it, "
            "'manage' to grant its tools or configure it). If the cc entity "
            "does not appear in server listings, the current user's roles "
            "do not carry the grant — request the permission rather than "
            "retrying."
        ),
    },
)

#: Lower-cased token → set of entry indexes (built once at import).
_INDEX: dict[str, set[int]] = {}
for _i, _entry in enumerate(_KNOWLEDGE_ENTRIES):
    for _kw in _entry["keywords"]:
        _INDEX.setdefault(_kw.lower(), set()).add(_i)


def search_knowledge(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    """Keyword-scored search over the corpus (deterministic, no LLM).

    Scores = matched keyword count (weighted 3) + query-token overlap with
    topic/rule text (weighted 1). Returns the ``top_k`` best entries with
    score > 0, each as ``{id, topic, rule_text, score}``.
    """
    if not query or not query.strip():
        return []
    tokens = {
        t
        for t in query.lower().replace(",", " ").replace("?", " ").split()
        if len(t) > 1
    }
    if not tokens:
        return []

    scores: dict[int, float] = {}
    for token in tokens:
        for idx in _INDEX.get(token, ()):
            scores[idx] = scores.get(idx, 0.0) + 3.0
        # Substring fallback so "models" matches keyword "model" and rule text.
        for idx, entry in enumerate(_KNOWLEDGE_ENTRIES):
            hay = f"{entry['topic']} {entry['rule_text']}".lower()
            if token in hay:
                scores[idx] = scores.get(idx, 0.0) + 1.0

    ranked = sorted(
        ((idx, s) for idx, s in scores.items() if s > 0),
        key=lambda pair: (-pair[1], pair[0]),
    )[: max(1, min(top_k, 10))]

    return [
        {
            "id": _KNOWLEDGE_ENTRIES[idx]["id"],
            "topic": _KNOWLEDGE_ENTRIES[idx]["topic"],
            "rule_text": _KNOWLEDGE_ENTRIES[idx]["rule_text"],
            "score": round(score, 2),
        }
        for idx, score in ranked
    ]


def get_entry_count() -> int:
    """Return the number of corpus entries (used by tests/meta tools)."""
    return len(_KNOWLEDGE_ENTRIES)
