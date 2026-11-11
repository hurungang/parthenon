"""AssistantSeeder — idempotent provisioning of the Control Center Assistant.

The Control Center Assistant is a seeded, system-provided conversational
``AgentType`` whose tools are the management MCP tools (create / update /
read of the Agents-menu resources).  Its management operations run on the
*user's* OAuth identity via the Communication Hub MCP protocol server; the
assistant acts strictly on behalf of the authenticated user within that
user's permission scope, and never performs deletion.

The assistant is tenant-bound: every tenant gets its OWN assistant
``AgentType`` and management skill (per-tenant model selection is configured
through ``PUT /agents/model-configs/assistant-model``, which persists onto
that tenant's assistant ``AgentType.model_id``).  The seeder therefore never
binds a model.

Idempotent: run at Control Center startup; existing rows are updated in
place (system flag, instruction, tool bindings) without touching another
tenant's data — each tenant is provisioned independently and one tenant's
failure never aborts the rest.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete as sqlalchemy_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: Four-underscore separator / CC namespace slug (mirrored from the registry
#: to keep the seeder import-light).
TOOL_SEPARATOR = "____"
CC_SERVER_SLUG = "cc"


def _tenant_system_server_id(tenant_id: Any) -> Any:
    """Deterministic per-tenant id for the mirrored ``system`` MCP server."""
    import uuid as _uuid

    return _uuid.uuid5(_uuid.NAMESPACE_OID, f"parthenon:system-server:{tenant_id}")


def _tenant_cc_server_id(tenant_id: Any) -> Any:
    """Deterministic per-tenant id for the "Control Center" MCP server.

    The Control Center entity (slug ``cc``) hosts the management + meta
    tools under the ``cc____`` namespace (FIX-20261101-000319).  Its UUID
    is a NEW reserved identity derived per tenant — never the System
    server's reserved id.
    """
    import uuid as _uuid

    return _uuid.uuid5(_uuid.NAMESPACE_OID, f"parthenon:cc-server:{tenant_id}")


def _tenant_management_tool_id(mcp_hub_id: Any, tenant_id: Any) -> Any:
    """Deterministic per-tenant id for a mirrored management ``McpTool`` row.

    The registry's stable ``mcp_hub_id`` belongs to the ROOT tenant's row;
    per-tenant mirrors derive a uuid5 from it plus the tenant id so the
    upsert is idempotent across restarts.
    """
    import uuid as _uuid

    return _uuid.uuid5(
        _uuid.NAMESPACE_OID, f"parthenon:system-tool:{tenant_id}:{mcp_hub_id}"
    )

#: Stable, per-tenant-unique names for the assistant and its management skill.
ASSISTANT_AGENT_TYPE_NAME = "control-center-assistant"
MANAGEMENT_SKILL_NAME = "control-center-management"

#: FIX-20261101-111439: workflow-appropriate iteration budget for the
#: assistant. The documented agent-creation workflow alone needs 11+ tool
#: iterations (list_agent_identities + list_agent_roles + list_model_configs
#: + get_mcp_server tool discovery → create_skill → create_agent_identity →
#: create_agent_role → update_agent_role grant → create_agent_type; each tool
#: call costs an LLM iteration). 24 = ~2x headroom over the observed 11-step
#: exhaustion at the default 10, while still bounding runaway loops.
ASSISTANT_GUARDRAIL_MAX_ITERATIONS = 24

#: Constrains the assistant to the Agents-menu management scope, no-delete,
#: and delegated-action rules (act on behalf of the authenticated user within
#: the user's own permission scope).  This text is the assistant's
#: ``system_instruction``.
#:
#: FIX-20261102-100704: the always-on rules carry GENERIC PRINCIPLES
#: (understand-before-acting, completeness, prerequisite-ordering,
#: grant-at-the-right-level, reuse-first) plus accurate reference FACTS — never
#: a fixed case script (e.g. "create skill → grant → create agent"), so the
#: model derives the correct order for whatever request it receives.
ASSISTANT_SYSTEM_INSTRUCTION = (
    "You are the Control Center Assistant, a management helper embedded in the "
    "Control Center web UI. You help the signed-in user perform Agents-menu "
    "management tasks through natural language: creating, updating and reading "
    "skills, SOPs, agent types, agent roles, agent identities, model "
    "configurations, schedules, data types, and MCP Hub connections.\n\n"
    "Rules you must always follow:\n"
    "1. Act strictly ON BEHALF OF the authenticated user and only within that "
    "user's permission scope. You have no elevated privileges; every management "
    "tool call is authorized against the user's own permissions, so if a call "
    "is denied, explain that the user lacks permission and do not retry it.\n"
    "2. You may only create, update, list, and read management resources. "
    "Deletion is NOT supported — if the user asks you to delete or remove "
    "anything, decline clearly and explain that deletion is not available "
    "through the assistant.\n"
    "2a. UNDERSTAND BEFORE ACTING (generic): before acting on a request, "
    "establish the platform model for the resource at hand — call "
    "search_assistant_knowledge for the relevant principles and reference "
    "facts, and use the discovery tools (list_* for existing entities, "
    "get_mcp_server for a server's tools, get_management_tool_schema for a "
    "tool's exact schema) instead of guessing names, ids, or required "
    "fields.\n"
    "2b. COMPLETENESS PRINCIPLE (generic, every resource type): a resource "
    "you create or update must be COMPLETE and functional in its own "
    "context — everything it needs to do its job must be present at write "
    "time (required ids/references, bindings, grants, model, schema, "
    "target, ...), and no payload may carry a placeholder value. What "
    "'complete' means comes from the reference facts for that resource "
    "type, not from one universal checklist (search the knowledge for "
    "'resource-completeness' when unsure). If a required value is unknown, "
    "mark the gap in the preview and ASK the user before writing. A "
    "resource that cannot function in its context is a shell, never a valid "
    "creation.\n"
    "2c. PREREQUISITE AND GRANT PRINCIPLES (generic — derive, never script): "
    "(a) Prerequisite ordering: a reference can only point at something "
    "that already exists, so if a capability or entity you need to "
    "reference does not exist yet, create it first and then reference it. "
    "Derive the order from the dependencies you discovered (X references Y "
    "⇒ Y must exist before X is written) — there is no universal fixed "
    "sequence; if a dependency cannot be satisfied, say what is missing and "
    "ask. (b) Grant at the right level: access is granted through the "
    "platform permission model, and it must be granted at the level the "
    "configuration actually consumes it — role-based agent types get "
    "runtime access from their ROLE's skill/SOP grants, role-less agent "
    "types from their DIRECT skill/SOP bindings. A capability merely bound "
    "on the agent type but not granted where the configuration consumes it "
    "is inaccessible at runtime; diagnose missing access by checking that "
    "level. (c) Reuse-first: prefer an existing compatible entity over "
    "inventing a new one — list before you create, and ask when several "
    "candidates fit. Search the knowledge for 'prerequisite-ordering', "
    "'grant-at-the-right-level' and 'reuse-first' for the reference facts. "
    "A prerequisite you create is itself a write and needs confirmation "
    "(rule 2e).\n"
    "2d. AGENT-CREATION COMPLETENESS (critical): before creating an agent "
    "type, run list_agent_identities, list_agent_roles and "
    "list_model_configs to discover the existing pieces. Reuse a compatible "
    "identity and role (or create them: create_agent_identity; "
    "create_agent_role WITH the skill granted via skill_ids); if the agent "
    "uses a role, grant the skill to the role (update_agent_role "
    "skill_ids). Choose model_id ONLY from an ENABLED model in "
    "list_model_configs. An agent type without a working model AND (an "
    "identity or a role) is NON-FUNCTIONAL — never create one. If any piece "
    "is missing or unknown, ask the user first.\n"
    "2f. SKILL-TOOL BINDING RULE (critical): a skill can only invoke tools "
    "BOUND to it. When creating a skill that wraps an MCP tool, discover the "
    "tool (get_mcp_server returns its 'tools' list with canonical "
    "server____tool names) and bind it at creation with tool_names / "
    "tool_ids in the data object (or add it afterward via update_skill — "
    "additive, idempotent), because a skill without bindings cannot do "
    "anything. If create_skill or update_skill returns a 'warnings' entry "
    "saying the skill has no tools bound, NEVER leave it that way — discover "
    "the right tool and bind it immediately via update_skill, then tell the "
    "user what you bound. cc____ tools are Control Center management "
    "capabilities — grant them to roles deliberately via the Control Center "
    "MCP entity, distinct from general system____ tools.\n"
    "2h. ROLE-MCP-SESSION RULE (critical): MCP tools only work for an agent "
    "if its role has an MCP session mapped for every MCP server its skills "
    "touch. create_agent_role / update_agent_role accept "
    "mcp_session_mappings ({server, session}, ids or names) — additive, one "
    "session per server per role. Defaults apply automatically so every "
    "server ends up mapped (passthrough preferred; a server with exactly one "
    "session uses it; a server with MULTIPLE sessions defaults to the FIRST "
    "one — is_default first, then oldest): when the tool response carries a "
    "'warnings' entry saying a server was defaulted to a session, CONFIRM "
    "that choice with the user (the warning lists alternative sessions for "
    "re-mapping) before finishing. "
    "CRITICAL: 'passthrough' is an auth TYPE, not a session name — NEVER "
    "pass session: 'passthrough'. Explicit mappings are for EXTERNAL "
    "credential sessions only (e.g. {server: 'supabase', session: "
    "'harry'}); passthrough-auth servers need NO explicit mapping (the "
    "default rule auto-maps) or the real session name (e.g. 'default'). "
    "After every role create/update, check the returned 'warnings' and "
    "'auto_mapped_mcp_sessions' and relay/resolve them before finishing. "
    "Preview "
    "rows for mappings use the form 'supabase → session harry (oauth2)'. "
    "Search the knowledge for 'role-mcp-session-mappings'.\n"
    "2i. ROLE-PERMISSION vs AGENT-VISIBILITY MODEL (critical): a role "
    "controls PERMISSION only; an AGENT TYPE controls VISIBILITY — the "
    "agent sees only what is directly associated to the agent type (its "
    "assigned SOPs — skill_invocation steps' skills' tools and "
    "agent_delegation steps' target agents — plus its direct skill "
    "bindings), as a SUBSET of the role's grants. Extra role grants that "
    "are not agent-type-associated are correctly invisible — this is by "
    "design, never a warning or error. If a user reports an agent can't "
    "see an expected tool, associate the SOP/skill to the AGENT TYPE "
    "(agent-type bindings), not just the role. Search the knowledge for "
    "'sop-only-router'.\n"
    "2e. CONFIRMATION RULE (critical, hard): before ANY "
    "invoke_management_tool call whose wrapped action is a CREATE or an "
    "UPDATE (read/list/get unaffected), you MUST: (1) build the exact "
    "payload; (2) present the CANONICAL markdown preview (FIX-20261101-"
    "223511): a bold title line '**<Operation> <Resource Type>: <Name>**' "
    "immediately followed by ONE markdown table with the header "
    "'| Field | Value |' and one row per field — never bullet lists or "
    "prose-only previews, never another layout; for updates list ONLY the "
    "changed fields (old → new); for agent-type creation the table MUST "
    "show model, identity, role, skills, and grants rows. Every field the "
    "operation sets gets a row: enum choices (status, input_type, "
    "output_type, provider_type, guardrail modes) show the exact value; "
    "role/identity assignments (identity_id, role_id, role_ids) show the "
    "resolved id and name; list fields (skill_ids, sop_ids, tool_ids, "
    "tool_names, enabled_models) show the ADDED entries labeled '(add)' — "
    "mcp_session_mappings show one row per mapping, e.g. "
    "'supabase → session harry (oauth2)'; "
    "existing entries are kept, nothing is ever removed; SOP steps show the "
    "ORDERED list as numbered rows (e.g. '1. skill_invocation: "
    "check-credit-score', '2. agent_delegation: FraudCheckAgent') — on "
    "updates the full old → new step list, because 'steps' REPLACES the "
    "whole list and omitted steps are deleted; (3) call "
    "human_intervene with "
    "intervention_type='approval' and prompt = the table preview, and WAIT "
    "for the response; (4) execute ONLY if the user approves. If the user "
    "rejects, do NOT execute — confirm with the user what to change. When "
    "creating ANY resource, include all "
    "required fields in the preview and let the user fill gaps before "
    "executing. Reads need no confirmation.\n"
    "2g. STRUCTURED-ERROR SELF-CORRECTION: when a management call fails "
    "validation, the error payload is structured — "
    "{'error': 'validation_failed', 'problems': [{field, problem, remedy}]}. "
    "Read each problem's field and remedy, fix exactly those fields, and "
    "retry autonomously (the user already approved the operation; you are "
    "only correcting the payload). Typical shapes: missing slug (derive it "
    "from the name); invalid enum (the remedy lists allowed values — pick "
    "the closest); unknown id/name (404 — discover the right entity with "
    "list_* first); conversational input_type with output_data_type_id "
    "(drop the data type or switch input_type). A validation failure "
    "writes nothing. Search the knowledge for "
    "'structured-error-self-correction' for the full playbook. If the same "
    "problem survives two corrections, stop and ask the user.\n"
    "3. Stay within the Agents-menu management scope. Decline requests outside "
    "this scope (for example platform administration, system configuration, or "
    "anything not reachable through your management tools).\n"
    "4. Confirm the essential details (name and required fields) before "
    "creating a resource, and report back what was created or changed with its "
    "id and name.\n"
    "5. Never invent, echo, or request credentials, tokens, or secret material "
    "of any kind.\n"
    "6. NEVER claim that a resource was created, updated, listed, or read "
    "unless the corresponding management tool call actually returned a "
    "success result — report the real id and name exactly as they appear in "
    "the tool result. If the management tool you need is unavailable, "
    "returns an error, or is denied, say so plainly and stop; do not "
    "fabricate a result or pretend the operation succeeded.\n\n"
    "Tool discovery (progressive disclosure):\n"
    "7. Only a small set of meta tools is loaded in this conversation. Use "
    "list_management_tools to see every available management action, "
    "get_management_tool_schema before invoking an unfamiliar tool, and "
    "invoke_management_tool(tool_name, args) to execute any of them.\n"
    "8. Use search_assistant_knowledge for Parthenon principles and "
    "reference facts before acting. Reference FACTS (consult them — they are "
    "not a script): agent types bind SKILLS/SOPs and never raw MCP tools; "
    "skills wrap tools through tool bindings; roles grant skills/SOPs and "
    "identities are assigned to roles; an agent's model must exist in a "
    "tenant Model Config's enabled models; conversational agent types do not "
    "support typed outputs; names/slugs are unique per tenant; cc____ tools "
    "are Control Center management capabilities distinct from general "
    "system____ tools; deletion is not supported. PRINCIPLES: "
    "resource-completeness, prerequisite-ordering, grant-at-the-right-level, "
    "reuse-first, confirm-before-write (rules 2b/2c/2e). ALWAYS confirm "
    "create/update with a human_intervene markdown-table preview before "
    "executing."
)


#: Shared instruction digest for the management skill — used for BOTH the
#: create and the refresh (digest-compare) branches so already-seeded rows
#: converge to the same text on the next seeder run.
#:
#: FIX-20261102-100704: generic principles + reference facts instead of the
#: former hardcoded "composition chain" (create skill → grant → create
#: agent).  The digest is compared verbatim by both seeder branches, so a
#: restart refreshes every previously seeded row.
MANAGEMENT_SKILL_INSTRUCTIONS = (
    "Invoke the appropriate management tool to create, update, list, or "
    "read Agents-menu resources on behalf of the user. Deletion is not "
    "available. Work from the PRINCIPLES and REFERENCE FACTS surfaced by "
    "search_assistant_knowledge, not from a memorized sequence. "
    "PRINCIPLES: (1) understand the platform model before acting — use "
    "list_*, get_mcp_server and get_management_tool_schema instead of "
    "guessing; (2) completeness — every resource you create must be complete "
    "and functional in its own context, with every reference it needs and no "
    "placeholder values, and unknown values are asked about before writing; "
    "(3) prerequisite ordering — create what you reference before you "
    "reference it, deriving the order from the discovered dependencies (X "
    "references Y ⇒ Y exists first), never from a fixed script; (4) grant at "
    "the right level — access comes from the permission model at the level "
    "the configuration consumes it (role grants for role-based agent types, "
    "direct bindings for role-less ones); (5) reuse-first — prefer an "
    "existing compatible entity and ask when several candidates fit. "
    "REFERENCE FACTS: skills wrap MCP tools through tool bindings — a skill "
    "can only invoke tools BOUND to it, bound at creation via tool_names / "
    "tool_ids in create_skill or added via update_skill (additive, "
    "idempotent); if the tool result carries a 'warnings' entry about zero "
    "bindings, bind the right tool immediately via update_skill and tell the "
    "user. SOPs compose skills: a SOP is an ordered list of steps — "
    "skill_invocation steps reference a skill (skill_id, id or exact name) "
    "and agent_delegation steps reference a target agent type "
    "(target_agent_type_id, id or exact name; delegation steps gate the "
    "role permissions of every role bound to the SOP). HARD RULE — SOPs "
    "must never mention or instruct direct MCP-tool calls: no "
    "'server____tool' names in any step or instruction, and never tell an "
    "agent to call a raw tool itself; tool visibility flows ONLY through "
    "SOP associations (agent_delegation + skill_invocation steps), so bind "
    "a needed raw tool into a SKILL and use a skill_invocation step. The "
    "'steps' array on "
    "create_sop / update_sop REPLACES the whole list on update — always "
    "send the complete desired list, since omitted steps are deleted. "
    "Roles grant skills/SOPs (create_agent_role / "
    "update_agent_role with skill_ids / sop_ids — additive, idempotent, "
    "unknown id/name → 404) and identities are assigned to roles. Agent "
    "types bind skills/SOPs (never raw MCP tools) and are non-functional "
    "without an enabled model from a tenant Model Config AND (an identity or "
    "a role) — never create such a shell. cc____ tools are Control Center "
    "management capabilities, distinct from general system____ tools. "
    "CONFIRMATION RULE: before ANY create or update management call, present "
    "the CANONICAL markdown preview — a bold title line '**<Operation> "
    "<Resource Type>: <Name>**' followed by ONE '| Field | Value |' markdown "
    "table (updates: only changed fields, old → new; enum fields show the "
    "exact value; role/identity assignments show the resolved id and name; "
    "list fields show the ADDED entries labeled '(add)' — additive merge, "
    "nothing removed) — and call "
    "human_intervene with intervention_type='approval'; execute only after "
    "the user approves; if rejected, do not execute and ask what to change. "
    "If a call fails validation, the structured error payload "
    "({'error': 'validation_failed', 'problems': [{field, problem, remedy}]}) "
    "tells you which field to fix — correct exactly those fields and retry "
    "autonomously. "
    "Reads need no confirmation. Use get_management_tool_schema before "
    "invoking an unfamiliar tool."
)


class AssistantSeeder:
    """Idempotently seed the Control Center Assistant and its tool bindings."""

    async def run(self, session: AsyncSession) -> dict[str, Any]:
        """Seed the assistant agent type, management skill and tool bindings.

        Provisions every tenant (the assistant is tenant-bound).  Returns a
        summary dict describing the actions taken per tenant; a single
        tenant's failure is logged and skipped, never aborting the rest.
        """
        from app.db.models.tenant import Tenant

        tenants = (
            (await session.execute(select(Tenant).order_by(Tenant.created_at.asc())))
            .scalars()
            .all()
        )
        if not tenants:
            raise RuntimeError(
                "AssistantSeeder requires at least the root tenant to be "
                "provisioned — run ensure_root_tenant() before seeding."
            )

        summary: dict[str, Any] = {"tenants": len(tenants), "per_tenant": {}}
        for tenant in tenants:
            try:
                summary["per_tenant"][str(tenant.id)] = await self._seed_tenant(
                    session, tenant.id
                )
                # Commit per tenant so one tenant's failure (which requires a
                # transaction rollback) never undoes another tenant's work.
                await session.commit()
            except Exception:
                logger.exception(
                    "AssistantSeeder: provisioning failed for tenant %s — "
                    "rolling back this tenant only and continuing.",
                    tenant.id,
                )
                await session.rollback()
                summary["per_tenant"][str(tenant.id)] = "failed"
        return summary

    async def _seed_tenant(self, session: AsyncSession, tenant_id: Any) -> dict[str, str]:
        """Seed the management skill + assistant agent type for one tenant."""
        summary: dict[str, str] = {}
        skill = await self._seed_skill(session, tenant_id)
        summary["skill"] = skill
        agent_type = await self._seed_agent_type(session, tenant_id)
        summary["agent_type"] = agent_type
        await session.flush()
        return summary

    async def _seed_skill(self, session: AsyncSession, tenant_id: Any) -> str:
        """Create/update the management skill and its tool bindings (idempotent)."""
        from app.db.models.mcp_hub import McpTool
        from app.db.models.skills import Skill, SkillToolBinding
        from app.services.agents.system_tool_registry import SystemToolRegistry

        skill = (
            await session.execute(
                select(Skill).where(
                    Skill.name == MANAGEMENT_SKILL_NAME,
                    Skill.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if skill is None:
            skill = Skill(
                tenant_id=tenant_id,
                name=MANAGEMENT_SKILL_NAME,
                description=(
                    "Control Center management operations (create / update / read) "
                    "for the Agents-menu resources."
                ),
                instructions=MANAGEMENT_SKILL_INSTRUCTIONS,
                is_active=True,
                is_system=True,
            )
            session.add(skill)
            await session.flush()
            action = "created"
            logger.info("AssistantSeeder: created management skill '%s'", MANAGEMENT_SKILL_NAME)
        else:
            action = "exists"
            updated = False
            if not skill.is_system:
                skill.is_system = True
                updated = True
            # Digest-compare against the shared constant so already-seeded
            # (pre-fix) rows converge to the current text on the next run.
            if skill.instructions != MANAGEMENT_SKILL_INSTRUCTIONS:
                skill.instructions = MANAGEMENT_SKILL_INSTRUCTIONS
                updated = True
            if updated:
                logger.info("AssistantSeeder: updated management skill '%s'", MANAGEMENT_SKILL_NAME)

        await self._ensure_skill_bindings(session, skill, tenant_id)
        return action

    async def _ensure_skill_bindings(
        self, session: AsyncSession, skill: Any, tenant_id: Any
    ) -> None:
        """Bind every management tool to the skill (missing bindings only).

        Self-seeding: the per-tenant ``McpTool`` rows for the management
        tools are upserted here when missing (FIX-20261031-035145) instead
        of depending on another component having seeded them first — the
        global system-tool seeding stamps rows to the ROOT tenant only, so
        every non-root tenant previously ended up with 0 bindings and a
        "not seeded yet" warning on each startup.

        FIX-20261101-000319: rows live under the per-tenant "Control
        Center" entity with canonical ``cc____<bare>`` names; legacy
        ``system____<bare>`` management rows (and their bindings) are
        retired by :meth:`_retire_legacy_management_rows` first.
        """
        from app.db.models.mcp_hub import McpTool
        from app.db.models.skills import SkillToolBinding
        from app.services.agents.system_tool_registry import SystemToolRegistry

        await self._retire_legacy_management_rows(session, tenant_id, skill)
        await self._ensure_management_tool_rows(session, tenant_id)

        # The management skill binds BOTH sets: the ~36 execution tools
        # (what the invoke wrapper dispatches to, what the parity map /
        # resolve endpoint / external MCP clients use) and the constant
        # meta tools (what the assistant context actually loads).
        seeded_names = (
            SystemToolRegistry.get_management_tool_names()
            | SystemToolRegistry.get_meta_tool_names()
        )
        tools = (
            (
                await session.execute(
                    select(McpTool).where(
                        McpTool.original_name.in_(seeded_names),
                        McpTool.tenant_id == tenant_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        by_name = {t.original_name: t for t in tools}

        existing_bindings = (
            (
                await session.execute(
                    select(SkillToolBinding).where(SkillToolBinding.skill_id == skill.id)
                )
            )
            .scalars()
            .all()
        )
        bound_tool_ids = {b.tool_id for b in existing_bindings}

        order = len(existing_bindings)
        for name in sorted(seeded_names):
            tool = by_name.get(name)
            if tool is None:
                logger.error(
                    "AssistantSeeder: management tool '%s' could not be "
                    "provisioned for tenant %s — binding skipped.",
                    name, tenant_id,
                )
                continue
            if tool.id in bound_tool_ids:
                continue
            session.add(SkillToolBinding(skill_id=skill.id, tool_id=tool.id, order=order))
            order += 1
            logger.info(
                "AssistantSeeder: bound skill '%s' → tool '%s'",
                MANAGEMENT_SKILL_NAME, name,
            )

    async def _retire_legacy_management_rows(
        self, session: AsyncSession, tenant_id: Any, skill: Any
    ) -> None:
        """Delete legacy ``system____<bare>`` management rows + their bindings.

        Migration (FIX-20261101-000319): before the ``cc____`` namespace,
        management + meta tools were provisioned as ``system____<bare>``
        rows under the per-tenant ``system`` server mirror (and, for the
        root tenant, under the global System entity).  Those rows must no
        longer be grantable or listed.  This removes every management/
        meta McpTool row of the tenant whose canonical name still carries
        the ``system____`` prefix, together with any ``SkillToolBinding``
        rows referencing them — the new ``cc____`` rows (and fresh
        bindings) are provisioned right after.  General ``system____``
        rows are never touched.  Idempotent: once retired, nothing matches.
        """
        from app.db.models.mcp_hub import McpTool
        from app.db.models.skills import SkillToolBinding
        from app.services.agents.system_tool_registry import SystemToolRegistry

        seeded_names = {e["original_name"] for e in SystemToolRegistry.get_cc_mcp_hub_entries()}
        legacy_rows = (
            (
                await session.execute(
                    select(McpTool).where(
                        McpTool.tenant_id == tenant_id,
                        McpTool.name.like(f"system{TOOL_SEPARATOR}%"),
                        McpTool.original_name.in_(seeded_names),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not legacy_rows:
            return

        legacy_ids = [row.id for row in legacy_rows]
        await session.execute(
            sqlalchemy_delete(SkillToolBinding).where(
                SkillToolBinding.tool_id.in_(legacy_ids)
            )
        )
        for row in legacy_rows:
            await session.delete(row)
        await session.flush()
        logger.info(
            "AssistantSeeder: retired %d legacy system____ management rows "
            "for tenant %s",
            len(legacy_rows), tenant_id,
        )

    async def _ensure_management_tool_rows(
        self, session: AsyncSession, tenant_id: Any
    ) -> None:
        """Upsert the tenant's own ``McpTool`` rows for the management tools.

        Idempotent and tenant-scoped: row id is a deterministic uuid5 of the
        registry entry's stable ``mcp_hub_id`` plus the tenant id (the raw
        ``mcp_hub_id`` belongs to the ROOT tenant's row — reusing it would
        violate the primary key).  The parent is the per-tenant "Control
        Center" MCP server (slug ``cc``) — management tools are
        ``cc____<bare>`` rows of that dedicated entity
        (FIX-20261101-000319), never of the generic System entity.
        """
        from app.db.models.mcp_hub import McpServer, McpServerStatus, McpTool
        from app.services.agents.system_tool_registry import SystemToolRegistry

        entries = SystemToolRegistry.get_cc_mcp_hub_entries()
        # The general meta tools (human_intervene) stay system____-named but
        # still need a per-tenant row so the management skill can bind them.
        general_meta = {
            e["original_name"]: e
            for e in SystemToolRegistry.get_mcp_hub_entries()
            if e["original_name"] in SystemToolRegistry.get_meta_tool_names()
        }
        for name, entry in general_meta.items():
            if all(e["original_name"] != name for e in entries):
                entries.append(entry)
        if not entries:
            return

        existing_tools = (
            (
                await session.execute(
                    select(McpTool).where(
                        McpTool.tenant_id == tenant_id,
                        McpTool.original_name.in_(
                            {e["original_name"] for e in entries}
                        ),
                        McpTool.name.like(f"{CC_SERVER_SLUG}{TOOL_SEPARATOR}%"),
                    )
                )
            )
            .scalars()
            .all()
        )
        existing_by_name = {t.original_name: t for t in existing_tools}

        missing = [e for e in entries if e["original_name"] not in existing_by_name]
        if not missing:
            return

        # Parent server: per-tenant "Control Center" entity (slug ``cc``).
        server_id = _tenant_cc_server_id(tenant_id)
        server = await session.get(McpServer, server_id)
        if server is None:
            session.add(
                McpServer(
                    id=server_id,
                    tenant_id=tenant_id,
                    name="Control Center",
                    slug="cc",
                    description=(
                        "Control Center management capabilities — the "
                        "cc____ management and meta tools, grantable to "
                        "roles per tool"
                    ),
                    base_url="",
                    status=McpServerStatus.active,
                )
            )
            await session.flush()
            logger.info(
                "AssistantSeeder: provisioned per-tenant Control Center "
                "(cc) server for tenant %s",
                tenant_id,
            )
        else:
            # FIX-20261101-090438: the cc entity is system-managed — the
            # seeder is its ONLY writer.  Refresh drifted fields on every
            # run (idempotent); the system-managed marking itself is the
            # slug convention (SYSTEM_MANAGED_SERVER_SLUGS), kept stable
            # by never allowing the slug to drift.
            canonical_description = (
                "Control Center management capabilities — the "
                "cc____ management and meta tools, grantable to "
                "roles per tool"
            )
            if (
                server.name != "Control Center"
                or server.description != canonical_description
                or server.base_url != ""
                or server.status != McpServerStatus.active
            ):
                server.name = "Control Center"
                server.description = canonical_description
                server.base_url = ""
                server.status = McpServerStatus.active
                await session.flush()
                logger.info(
                    "AssistantSeeder: refreshed drifted Control Center "
                    "(cc) server for tenant %s",
                    tenant_id,
                )

        for entry in missing:
            tool_id = _tenant_management_tool_id(entry["id"], tenant_id)
            if await session.get(McpTool, tool_id) is not None:
                continue
            session.add(
                McpTool(
                    id=tool_id,
                    tenant_id=tenant_id,
                    server_id=server_id,
                    name=entry["name"],
                    original_name=entry["original_name"],
                    description=entry["description"],
                    input_schema=entry["input_schema"],
                    is_active=True,
                )
            )
            logger.info(
                "AssistantSeeder: provisioned management tool '%s' for "
                "tenant %s",
                entry["name"], tenant_id,
            )
        await session.flush()

    async def _seed_agent_type(self, session: AsyncSession, tenant_id: Any) -> str:
        """Create/update the assistant AgentType (is_system, conversational).

        The seeder never binds a model — per-tenant model selection is
        configured via the dedicated assistant-model endpoints.
        """
        from app.db.models.agents import (
            AgentInputType,
            AgentOutputType,
            AgentType,
            AgentTypeSkillBinding,
        )
        from app.db.models.skills import Skill

        agent_type = (
            await session.execute(
                select(AgentType).where(
                    AgentType.name == ASSISTANT_AGENT_TYPE_NAME,
                    AgentType.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if agent_type is None:
            agent_type = AgentType(
                tenant_id=tenant_id,
                name=ASSISTANT_AGENT_TYPE_NAME,
                description=(
                    "System-provided conversational assistant for Control Center "
                    "Agents-menu management."
                ),
                system_instruction=ASSISTANT_SYSTEM_INSTRUCTION,
                input_type=AgentInputType.conversation,
                output_type=AgentOutputType.auto,
                is_active=True,
                is_system=True,
                guardrail_max_iterations=ASSISTANT_GUARDRAIL_MAX_ITERATIONS,
            )
            session.add(agent_type)
            await session.flush()
            action = "created"
            logger.info("AssistantSeeder: created assistant agent type '%s'", ASSISTANT_AGENT_TYPE_NAME)
        else:
            action = "exists"
            updated = False
            if not agent_type.is_system:
                agent_type.is_system = True
                updated = True
            if agent_type.input_type != AgentInputType.conversation:
                agent_type.input_type = AgentInputType.conversation
                updated = True
            if agent_type.system_instruction != ASSISTANT_SYSTEM_INSTRUCTION:
                agent_type.system_instruction = ASSISTANT_SYSTEM_INSTRUCTION
                updated = True
            if not agent_type.is_active:
                agent_type.is_active = True
                updated = True
            if agent_type.guardrail_max_iterations != ASSISTANT_GUARDRAIL_MAX_ITERATIONS:
                # FIX-20261101-111439: refresh the raised iteration budget on
                # existing seeded rows (pre-2026-11 rows carry the default 10).
                agent_type.guardrail_max_iterations = ASSISTANT_GUARDRAIL_MAX_ITERATIONS
                updated = True
            if updated:
                logger.info("AssistantSeeder: updated assistant agent type '%s'", ASSISTANT_AGENT_TYPE_NAME)

        # Bind the management skill to the assistant.
        skill = (
            await session.execute(
                select(Skill).where(
                    Skill.name == MANAGEMENT_SKILL_NAME,
                    Skill.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if skill is not None:
            existing = (
                await session.execute(
                    select(AgentTypeSkillBinding).where(
                        AgentTypeSkillBinding.agent_type_id == agent_type.id,
                        AgentTypeSkillBinding.skill_id == skill.id,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    AgentTypeSkillBinding(
                        agent_type_id=agent_type.id,
                        skill_id=skill.id,
                        order=0,
                    )
                )
                logger.info(
                    "AssistantSeeder: bound assistant '%s' → skill '%s'",
                    ASSISTANT_AGENT_TYPE_NAME, MANAGEMENT_SKILL_NAME,
                )

        return action
