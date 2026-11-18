"""Optimization mode — the optimizer as a *mode of the agent itself*.

An optimization conversation is an ordinary ``ConversationSession`` whose
``agent_type_id`` is the agent type being optimized and whose free-form
``channel`` carries ``"optimization"``. There is no seeded optimizer agent
type, no second identity and no scope column: the session's own agent type is
the subject *and* the identity/role/grant envelope that runs the turns.

This module owns the mode-facing decisions (all Control-Center-only, because
they read PostgreSQL):

* :data:`OPTIMIZATION_CHANNEL` / :data:`BUSINESS_CHANNEL_DEFAULT` — the only
  source of the channel value (``ConversationSession.channel`` is already
  ``String(50)``; the value is not an enum, column or constraint).
* :func:`resolve_optimization_mode` — load the session once per turn / tool
  call and expose ``(tenant_id, agent_type_id, channel, owner)``.
* :func:`require_subject_match` — server-side guard that a requested
  ``agent_type_id`` is this conversation's subject; a mismatch returns the
  structured ``out_of_scope`` refusal and writes nothing. Absent conversation
  id / non-optimization session keep the legacy (unguarded) behaviour.
* :func:`compose_optimization_mission` — the optimization mission (the stored
  ``optimize-and-verify`` command prompt with the subject interpolated) plus
  the conversational rules. It replaces the business instruction/SOP/skills
  for the duration of the conversation.
* :func:`get_optimization_conversation_availability` — computed availability
  (subject plan/execution state + optimizer model state + operator permission)
  for the conversation entry, the gate and the API. Nothing is stored.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversations import ConversationSession

if TYPE_CHECKING:
    from app.db.models.agents import AgentType

logger = logging.getLogger(__name__)

#: ``ConversationSession.channel`` value marking an optimization conversation.
OPTIMIZATION_CHANNEL = "optimization"
#: Default channel of an ordinary business conversation (existing behaviour).
BUSINESS_CHANNEL_DEFAULT = "web"

#: Mode value carried in the optimization context / availability payloads.
OPTIMIZATION_MODE = "optimization"

#: ``reason_code`` — the operator may not start work on this agent type.
REASON_PERMISSION_DENIED = "permission_denied"
#: ``reason_code`` — no completed reference execution exists yet.
REASON_NO_SUCCESSFUL_EXECUTION = "no_successful_execution"

#: Structured tool result returned by every out-of-scope optimization call.
OUT_OF_SCOPE_STATUS = "out_of_scope"


@dataclass(frozen=True)
class OptimizationMode:
    """The resolved mode of one conversation session.

    ``channel == OPTIMIZATION_CHANNEL`` is the mode check; ``agent_type_id`` is
    simultaneously the subject agent type and the runner.
    """

    conversation_session_id: uuid.UUID
    tenant_id: uuid.UUID | None
    agent_type_id: uuid.UUID | None
    channel: str
    owner_user_id: uuid.UUID | None

    @property
    def is_optimization(self) -> bool:
        return self.channel == OPTIMIZATION_CHANNEL


@dataclass(frozen=True)
class OptimizerModelProjection:
    """Read-only optimizer-model state surfaced in availability payloads."""

    model_id: str | None
    effective_model_id: str | None
    source: str | None
    configured: bool
    enabled: bool
    reason_code: str | None


@dataclass(frozen=True)
class OptimizationConversationAvailability:
    """Computed (never stored) availability of an optimization conversation.

    ``available`` / ``can_start_work`` answer "may optimization work start
    now?" — a missing optimized plan is *information*, never a block. Opening
    the conversation always succeeds; the reason describes what a turn would
    need.
    """

    available: bool
    reason_code: str | None
    reason: str | None
    can_start_work: bool
    plan_present: bool
    optimized_plan_status: str | None
    successful_executions: int
    optimizer_model: OptimizerModelProjection


def _parse_uuid(value: Any) -> uuid.UUID | None:
    """Parse a UUID-ish value, returning None instead of raising."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def resolve_optimization_mode(
    db: AsyncSession, conversation_session_id: Any
) -> OptimizationMode | None:
    """Load a conversation session and return its mode.

    Returns ``None`` when the id is absent / unparseable, the session does not
    exist in the calling tenant, or the session is not an optimization
    conversation. Callers treat ``None`` as "not optimization mode" and keep
    the legacy behaviour.
    """
    session_id = _parse_uuid(conversation_session_id)
    if session_id is None:
        return None
    session = await db.get(ConversationSession, session_id)
    if session is None:
        return None
    channel = session.channel or BUSINESS_CHANNEL_DEFAULT
    return OptimizationMode(
        conversation_session_id=session.id,
        tenant_id=session.tenant_id,
        agent_type_id=session.agent_type_id,
        channel=channel,
        owner_user_id=session.triggered_by_user_id,
    )


def _out_of_scope_result(subject_agent_type_id: uuid.UUID | None) -> dict[str, Any]:
    subject = (
        f" this conversation's subject agent type ({subject_agent_type_id})"
        if subject_agent_type_id is not None
        else " this conversation's agent type"
    )
    return {
        "status": OUT_OF_SCOPE_STATUS,
        "reason_code": OUT_OF_SCOPE_STATUS,
        "reason": (
            "Out of scope: optimization is limited to" + subject + ". "
            "The requested agent type is not this conversation's subject, so "
            "nothing was read, written or changed. Start a separate "
            "optimization conversation for a different agent type."
        ),
        "subject_agent_type_id": (
            str(subject_agent_type_id) if subject_agent_type_id is not None else None
        ),
    }


async def require_subject_match(
    db: AsyncSession,
    conversation_session_id: Any,
    requested_agent_type_id: Any,
) -> dict[str, Any] | None:
    """Enforce the inherent scoping of an optimization conversation.

    Returns ``None`` when the call is allowed (or must keep legacy behaviour),
    or the structured ``{"status": "out_of_scope", "reason": ...}`` tool result
    when the requested agent type is not this conversation's subject — in which
    case the caller must return it unchanged and write nothing.

    Legacy behaviour (no new guard) applies when:

    * there is no ``conversation_session_id`` (one-shot ``__command`` runs and
      other internal callers), or
    * the session does not exist in this tenant, or
    * the session's channel is not ``"optimization"``.
    """
    mode = await resolve_optimization_mode(db, conversation_session_id)
    if mode is None or not mode.is_optimization:
        return None

    requested = _parse_uuid(requested_agent_type_id)
    if requested is not None and requested == mode.agent_type_id:
        return None

    logger.warning(
        "Optimization out-of-scope refusal: conversation=%s subject=%s requested=%s",
        mode.conversation_session_id,
        mode.agent_type_id,
        requested_agent_type_id,
    )
    return _out_of_scope_result(mode.agent_type_id)


#: Conversational additions appended to the stored command mission. The mission
#: is the single instruction for the turn; these rules make the one-agent,
#: replay-only, ask-instead-of-assume contract explicit in the prompt (defence
#: in depth — the server guard is what makes the scope guarantee real).
OPTIMIZATION_CONVERSATION_RULES = """
## Optimization conversation rules (mandatory)

You are running as the agent type being optimized, in an optimization
conversation — not a business run. The person you are talking to is the
operator who is watching your work.

Two verification modes exist, and only one of them may contact a real
integration:

* REPLAY (default) — `execute_script` re-runs a script against the reference
  execution's recorded tool responses. Safe, repeatable, never live.
* ONE APPROVED LIVE SCRIPT RUN — the operator consents to running ONE saved
  script once, end to end, against live MCP tools. MCP tools are assumed to
  work; the point is to prove the SCRIPT, not the tools. The operator may
  explicitly ask for a live run even when replay passes — that is a valid
  reason; propose it and let them approve the details.

1. ONE AGENT TYPE ONLY. Everything you read or change must belong to
   `{agent_type_id}` — its optimized plan, its scripts, its base plan and its
   execution history. Never touch another agent type's plan, scripts or logs,
   and never claim you did. Out-of-scope requests are refused by the platform
   and nothing is changed.
2. REPLAY-ONLY BY DEFAULT. `execute_script` verifies by replaying recorded
   reference data. It never contacts a live integration and never changes
   data. Do not describe a replay as a live test, and do not describe a live
   script run as a per-tool check.
3. ASK INSTEAD OF ASSUMING. When you are blocked or a decision is genuinely
   ambiguous, ask the operator with the human-intervene tool (a question, a
   choice, or an approval) and stop until they answer. Never guess, never
   assume consent, and never retry in the background.
4. LIVE TESTS RUN THE SCRIPT — NEVER AN INDIVIDUAL TOOL. A live test verifies
   the SCRIPT you authored, end to end, in ONE run. It is not a per-tool test
   and MCP tools are assumed to work: never ask to call a tool "just to see
   what it returns". Use it when replay (`execute_script`) cannot prove the
   script, **or when the operator explicitly asks for a live verification** —
   do NOT refuse an explicit operator request solely because replay passed.
   In either case, first SAVE the exact version you want tested:
   a. call `generate_script` with the working source and note the returned
      `version_id`;
   b. then call `request_live_test` with `script_version_id=<that version_id>`
      and a `reason` saying what replay could not prove. Do NOT send an
      operation list — the approval card's tool-call preview ("it will call:
      …") is derived from your script's own `tools.call(...)` lines by the
      platform.
   The operator must approve that request. The script then runs ONCE in the
   real sandbox as this agent (same identity, tenant and existing grants), with
   the reference input, and its result and telemetry come back to you. Never
   request a live test for a single tool, for an unsaved draft, for a repeat of
   an earlier approval, for a session-long live mode, or for access beyond this
   agent type's existing grants.
5. NEVER DELETE. Deleting, retiring or removing plans, scripts or data is not
   supported here. Refuse such requests with a clear explanation.
6. NEVER HANDLE SENSITIVE MATERIAL. Never request, print or store identity
   tokens, credentials, database connection details or decrypted secrets.
7. PLAN OUTCOMES. Persist the plan through `generate_optimized_plan` with
   status `ready`, `failed`, or `needs_feedback` (never `requires_fix`). A
   `needs_feedback` outcome MUST include a specific, actionable `error`
   describing exactly what is missing — that text is shown to the operator.
   Steps stay flat with an `order`; when a step is genuinely a sub-step of
   another, set its optional `parent_order` to the parent's `order` (the plan
   renders as a tree). Omit `parent_order` for top-level steps. A step's
   `type` is `sop_invocation`/`skill_invocation`/`tool_call` ONLY when it
   actually invokes an existing SOP/skill/tool; validation, selection,
   formatting and other non-entity steps are `processing`.
8. OBSERVABLE WORK. Work in small, visible steps: state what you are doing,
   use the self-context tools to read before writing, and finish each turn
   with a short, operator-facing report of what you found, what you changed
   and what you need next.
""".strip()


async def compose_optimization_mission(
    db: AsyncSession, agent_type_id: uuid.UUID | str | None
) -> str:
    """Compose the optimization mission for a turn (business prompt replaced).

    Built from the stored ``optimize-and-verify`` command prompt — preserving
    operator edits to it — with the subject ``agent_type_id`` interpolated
    (``build_command_mission``), then extended with the conversational rules.
    """
    from app.services.agents.command_prompts import (
        OPTIMIZE_AND_VERIFY_SLUG,
        build_command_mission,
        get_command_prompt,
    )

    prompt = await get_command_prompt(db, OPTIMIZE_AND_VERIFY_SLUG)
    prompt_text = str(getattr(prompt, "prompt_text", "") or "")
    mission = build_command_mission(prompt_text, agent_type_id=agent_type_id)
    rules = OPTIMIZATION_CONVERSATION_RULES.replace(
        "{agent_type_id}", str(agent_type_id or "")
    )
    return f"{mission.strip()}\n\n{rules}"


async def _count_successful_executions(
    db: AsyncSession, agent_type_id: uuid.UUID
) -> int:
    """Completed normal executions of the subject (read-only)."""
    from app.db.models.agents import AgentJob, AgentJobStatus

    result = await db.execute(
        select(func.count())
        .select_from(AgentJob)
        .where(
            AgentJob.agent_type_id == agent_type_id,
            AgentJob.status == AgentJobStatus.completed,
        )
    )
    return int(result.scalar_one() or 0)


async def _plan_state(
    db: AsyncSession, agent_type_id: uuid.UUID
) -> tuple[bool, str | None]:
    """Return ``(plan_present, optimized_plan_status)`` for the subject.

    ``plan_present`` is true when a base or optimized plan exists. Neither is a
    precondition for opening the conversation — a missing plan is information.
    """
    from app.db.models.agents import AgentPlan
    from app.db.models.optimized_plan import OptimizedImplementationPlan

    optimized = (
        await db.execute(
            select(OptimizedImplementationPlan)
            .where(OptimizedImplementationPlan.agent_type_id == agent_type_id)
            .order_by(OptimizedImplementationPlan.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    base_exists = (
        await db.execute(
            select(AgentPlan.id)
            .where(AgentPlan.agent_type_id == agent_type_id)
            .limit(1)
        )
    ).scalar_one_or_none()

    status = None
    if optimized is not None:
        status = (
            optimized.status.value
            if hasattr(optimized.status, "value")
            else str(optimized.status)
        )
    return (optimized is not None or base_exists is not None), status


async def get_optimization_conversation_availability(
    db: AsyncSession,
    agent_type: "AgentType",
    *,
    successful_executions: int | None = None,
    can_start_work: bool | None = None,
) -> OptimizationConversationAvailability:
    """Compose the optimization conversation availability for a subject.

    Composed from the subject's execution/plan state, the optimizer-model state
    and (when supplied) the operator's permission. Nothing is stored; every
    server check recomputes it so the UI and the server agree.

    ``can_start_work`` is ``None`` for internal callers that cannot evaluate
    operator permissions (prepare-turn); those report the non-permission
    preconditions only.
    """
    from app.services.agents.optimizer_model_settings import (
        get_optimizer_model_state,
    )

    model_state = await get_optimizer_model_state(db)
    if successful_executions is None:
        successful_executions = await _count_successful_executions(db, agent_type.id)
    plan_present, optimized_status = await _plan_state(db, agent_type.id)

    reason: str | None = None
    reason_code: str | None = None
    if can_start_work is False:
        reason_code = REASON_PERMISSION_DENIED
        reason = (
            "You do not have permission to optimize and execute this agent type. "
            "Ask an administrator for the execute grant on this agent."
        )
    elif not model_state.usable:
        reason_code = model_state.reason_code
        reason = model_state.reason
    elif successful_executions < 1:
        reason_code = REASON_NO_SUCCESSFUL_EXECUTION
        reason = (
            "Optimization needs at least one successful execution of this agent "
            "as a reference run. Run the agent successfully first."
        )

    available = reason_code is None
    return OptimizationConversationAvailability(
        available=available,
        reason_code=reason_code,
        reason=reason,
        can_start_work=available,
        plan_present=plan_present,
        optimized_plan_status=optimized_status,
        successful_executions=successful_executions,
        optimizer_model=OptimizerModelProjection(
            model_id=model_state.model_id,
            effective_model_id=model_state.effective_model_id,
            source=model_state.source,
            configured=model_state.configured,
            enabled=model_state.enabled,
            reason_code=model_state.reason_code,
        ),
    )
