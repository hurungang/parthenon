"""Optimization live-test ledger — validation, state machine, expiry and audit.

The conversational optimizer is **replay-only by default**. When replay cannot
prove a script it may ask the operator for consent to run **that script** once,
end to end, against the real integrations. This service owns that proposal's
whole lifecycle in Control Center (the only DB writer):

* :meth:`OptimizationLiveTestService.create_request` — validate the requested
  *saved script version* and record one ``pending`` row. The tool-call preview
  is derived server-side from the version's ``python_source`` (never supplied
  by the caller), and validation is deliberately strict and side-effect free:
  an invalid proposal is refused with a specific ``reason_code`` and **nothing
  is written**.
* :meth:`~OptimizationLiveTestService.mark_approved` /
  ``mark_denied`` — the domain projection of the operator's decision. Decision
  attribution itself stays on ``InterveneResponse`` (who/when/approve-deny is
  never duplicated here).
* :meth:`~OptimizationLiveTestService.begin_execution` — the single-shot
  transition. At most one caller can ever start an execution: the conditional
  ``UPDATE`` only matches a row whose execution has not started, so a second
  attempt finds nothing and returns the stored outcome instead of running.
* :meth:`~OptimizationLiveTestService.complete_execution` — persist the script
  run record once and the terminal ``executed`` / ``failed``.
* :meth:`~OptimizationLiveTestService.expire_overdue` /
  ``cancel_for_session`` — close a request that can never run. Expiry also
  resolves the paused turn as ``unresumable/expired`` and appends the bounded
  stop turn, so the conversation stays replay-only with no retry.
* :meth:`~OptimizationLiveTestService.session_audit` — replay-vs-live counts
  from the raw runtime tool log.

Safety invariants enforced here (all server-side, never from the request body):

* the **subject** is derived from the conversation session's ``agent_type_id``
  — a caller cannot name another agent type;
* the requested script version must belong to that subject agent type (its
  ``ScriptDefinition.agent_type_id``), so an approval can never run another
  agent's script;
* the script's statically extracted ``tools.call`` names are checked against
  the subject agent type's own grants (``AgentPermissionManager``) as defence
  in depth — the same check ``generate_script`` already applies at authoring
  time — so a live run can never reach further than a business run;
* the list is bounded (one pending request per conversation, a per-session
  approved-live cap, a decision TTL) and the preview is capped for the card;
* control flow never executes anything — the forward to
  ``CH → AR`` is orchestrated by ``turn_resolution`` after the approval is
  consumed.

Control-Center-only: Agent Runtime and Communication Hub never import this
module (they receive the already-authorized script through internal APIs).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.intervene import InterveneRequest, InterveneRequestStatus
from app.db.models.optimization_live_test import (
    OptimizationLiveTestRequest,
    OptimizationLiveTestStatus,
)
from app.db.models.tool_calls import (
    RuntimeToolCall,
    RuntimeToolCallSessionKind,
)
from app.services.agents.script_tool_names import (
    extract_tools_call_names,
    preview_entries,
)

logger = logging.getLogger(__name__)

# ── Bounds and refusal vocabulary ────────────────────────────────────────────

#: Hard cap on the tool names rendered/stored in the approval card preview.
#: The script itself is the unit of execution, so this only bounds the card —
#: remaining calls are reported as "+N more".
MAX_LIVE_TEST_PREVIEW_TOOLS = 12

#: Refusal codes returned to the model (and surfaced in the chat).
REFUSAL_OUT_OF_SCOPE = "out_of_scope"
REFUSAL_NOT_PERMITTED = "operation_not_permitted"
REFUSAL_INVALID_SCRIPT_VERSION = "invalid_script_version"
REFUSAL_SCRIPT_VERSION_NOT_FOUND = "script_version_not_found"
REFUSAL_NO_TOOL_CALLS = "no_tool_calls"
REFUSAL_ALREADY_PENDING = "live_test_already_pending"
REFUSAL_QUOTA = "live_test_quota_exhausted"

#: Statuses that count against the per-session approved-live cap.
_CONSUMED_STATUSES = (
    OptimizationLiveTestStatus.approved,
    OptimizationLiveTestStatus.executed,
    OptimizationLiveTestStatus.failed,
)

#: Terminal statuses — the single-use gate already holds for these rows.
TERMINAL_STATUSES = frozenset(
    {
        OptimizationLiveTestStatus.executed,
        OptimizationLiveTestStatus.failed,
        OptimizationLiveTestStatus.denied,
        OptimizationLiveTestStatus.expired,
        OptimizationLiveTestStatus.cancelled,
    }
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_tz(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def status_value(status: Any) -> str:
    """The wire/domain string of a status enum (or a raw value)."""
    return status.value if hasattr(status, "value") else str(status)


def _parse_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


# ── Typed projections ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LiveTestScriptTarget:
    """The saved script version a live test would run.

    ``tool_preview`` describes what the script will call (derived server-side
    from ``python_source``) — evidence for the approval card, never the unit of
    execution.
    """

    script_version_id: uuid.UUID
    script_definition_id: uuid.UUID | None
    script_name: str | None
    script_version_label: str | None
    python_source: str
    tool_preview: tuple[str, ...]

    def preview_entries(self) -> list[dict[str, Any]]:
        return preview_entries(
            list(self.tool_preview), limit=MAX_LIVE_TEST_PREVIEW_TOOLS
        )


@dataclass(frozen=True)
class LiveTestCreateResult:
    """Outcome of a create attempt (accepted → row id + expiry + target)."""

    accepted: bool
    request_id: uuid.UUID | None = None
    expires_at: datetime | None = None
    script: LiveTestScriptTarget | None = None
    reason_code: str | None = None
    reason: str | None = None

    def refusal(self) -> dict[str, Any]:
        """The structured tool result for a refused proposal."""
        return {
            "status": "refused",
            "reason_code": self.reason_code or REFUSAL_INVALID_SCRIPT_VERSION,
            "reason": self.reason or "This live test was refused.",
        }


@dataclass(frozen=True)
class LiveTestOutcome:
    """Read projection of a ledger row (status + script run evidence)."""

    request_id: uuid.UUID
    status: str
    conversation_session_id: uuid.UUID
    target_agent_type_id: uuid.UUID
    script_version_id: uuid.UUID | None
    intervene_request_id: uuid.UUID | None
    expires_at: datetime | None
    requested_operations: list[dict[str, Any]]
    executed_operations: list[dict[str, Any]] | None
    execution_started_at: datetime | None
    execution_finished_at: datetime | None

    @property
    def is_terminal(self) -> bool:
        return self.status in {status_value(s) for s in TERMINAL_STATUSES}

    @property
    def script_run(self) -> dict[str, Any] | None:
        """The single script-run record (``None`` before any execution)."""
        for entry in self.executed_operations or []:
            if isinstance(entry, dict):
                return entry
        return None

    def resume_payload(self) -> dict[str, Any]:
        """The values carried into the paused tool's resume result."""
        payload: dict[str, Any] = {"live_test_status": self.status}
        if self.executed_operations is not None:
            payload["executed_operations"] = self.executed_operations
        payload["live_test_request_id"] = str(self.request_id)
        if self.script_version_id is not None:
            payload["script_version_id"] = str(self.script_version_id)
        run = self.script_run
        if run is not None:
            payload["script_run"] = run
        return payload


def outcome_of(row: OptimizationLiveTestRequest) -> LiveTestOutcome:
    """Project an ORM row onto the immutable read view."""
    return LiveTestOutcome(
        request_id=row.id,
        status=status_value(row.status),
        conversation_session_id=row.conversation_session_id,
        target_agent_type_id=row.target_agent_type_id,
        script_version_id=row.script_version_id,
        intervene_request_id=row.intervene_request_id,
        expires_at=row.expires_at,
        requested_operations=list(row.requested_operations or []),
        executed_operations=(
            list(row.executed_operations) if row.executed_operations is not None else None
        ),
        execution_started_at=row.execution_started_at,
        execution_finished_at=row.execution_finished_at,
    )


# ── Argument validation helpers ──────────────────────────────────────────────


def _canonical_tool_name(name: str) -> str:
    """Canonicalize a tool identifier to ``server____tool`` where possible."""
    try:
        from app.services.agents.tool_naming import build_tool_name, parse_tool_name

        server_slug, bare = parse_tool_name(name)
        return build_tool_name(server_slug, bare)
    except Exception:  # noqa: BLE001 — unknown shapes stay verbatim
        return name


def render_script_live_test_reason(
    *,
    script_name: str | None,
    script_version_label: str | None,
    tool_preview: Iterable[str],
    reason: str | None,
    expires_at: datetime | None,
) -> str:
    """Render the approval-card text for a live *script* run.

    The text states the unit of approval plainly: **one run of this script**,
    end to end, as the agent — not a tool-by-tool test. It carries the script
    name/version, the tool-call preview derived from the script source, the
    expiry and the single-use rule.
    """
    name = (script_name or "this script").strip()
    label = (script_version_label or "").strip()
    title = f"`{name}`" + (f" (version `{label}`)" if label else "")
    preview = [str(tool) for tool in tool_preview if str(tool).strip()]
    if preview:
        shown = ", ".join(f"`{tool}`" for tool in preview[:MAX_LIVE_TEST_PREVIEW_TOOLS])
        remaining = len(preview) - MAX_LIVE_TEST_PREVIEW_TOOLS
        if remaining > 0:
            shown += f" and {remaining} more"
        calls_line = f"It will call: {shown}."
    else:
        calls_line = "No literal `tools.call(...)` was found in this script."

    expiry_line = (
        f"The approval expires at {expires_at.isoformat()}."
        if expires_at is not None
        else ""
    )
    lines = [
        "**Run this script live**",
        "",
        title,
        "",
        (reason or "").strip() or "Replay verification could not prove this script.",
        "",
        calls_line,
        "",
        "Approving runs this whole script ONCE, end to end, in the real sandbox "
        "as this agent — same identity, tenant and existing grants. MCP tools "
        "are assumed to work; this is not a per-tool test. Single use: nothing "
        "is remembered, and a denial or expiry keeps verification replay-only.",
    ]
    if expiry_line:
        lines.append("")
        lines.append(expiry_line)
    return "\n".join(lines)


# ── Service ──────────────────────────────────────────────────────────────────


class OptimizationLiveTestService:
    """Ledger persistence + state machine for optimization live tests."""

    # ── Creation ─────────────────────────────────────────────────────────────

    async def create_request(
        self,
        db: AsyncSession,
        *,
        conversation_session_id: uuid.UUID,
        script_version_id: Any,
        reason: str | None = None,
    ) -> LiveTestCreateResult:
        """Validate a saved script version and record one ``pending`` request.

        The subject is the session's own ``agent_type_id`` (never supplied by
        the caller) and the script version must belong to that subject. The
        tool-call preview is derived here from ``python_source`` — the caller
        never lists operations. An invalid proposal returns a refusal and
        writes nothing.
        """
        from app.db.models.conversations import ConversationSession
        from app.services.agents.optimization_mode import OPTIMIZATION_CHANNEL

        session = await db.get(ConversationSession, conversation_session_id)
        if session is None:
            return self._refuse(
                REFUSAL_OUT_OF_SCOPE,
                "This conversation no longer exists, so no live test was recorded.",
            )
        if (session.channel or "") != OPTIMIZATION_CHANNEL:
            return self._refuse(
                REFUSAL_OUT_OF_SCOPE,
                "A live test can only be requested inside an optimization "
                "conversation. Nothing was recorded.",
            )
        if session.agent_type_id is None:
            return self._refuse(
                REFUSAL_OUT_OF_SCOPE,
                "This conversation has no subject agent type, so no live test "
                "was recorded.",
            )
        subject_agent_type_id = session.agent_type_id

        target = await self._resolve_script_target(
            db,
            tenant_id=session.tenant_id,
            subject_agent_type_id=subject_agent_type_id,
            script_version_id=script_version_id,
        )
        if isinstance(target, LiveTestCreateResult):
            return target

        permitted = await self._allowed_tool_names(db, subject_agent_type_id)
        if permitted:
            denied = [
                name
                for name in target.tool_preview
                if _canonical_tool_name(name) not in permitted
            ]
            if denied:
                return self._refuse(
                    REFUSAL_NOT_PERMITTED,
                    f"This script calls {', '.join(sorted(set(denied)))}, which "
                    "this agent type has not been granted. A live test can only "
                    "run the agent's own script with its own existing tools, so "
                    "nothing was recorded. Fix the script in `generate_script` "
                    "or ask the operator for the grant.",
                )

        pending = await db.execute(
            select(OptimizationLiveTestRequest.id).where(
                OptimizationLiveTestRequest.conversation_session_id
                == conversation_session_id,
                OptimizationLiveTestRequest.status == OptimizationLiveTestStatus.pending,
            )
        )
        if pending.scalar_one_or_none() is not None:
            return self._refuse(
                REFUSAL_ALREADY_PENDING,
                "A live-test approval is already waiting for the operator in "
                "this conversation. Wait for that decision — nothing was "
                "recorded.",
            )

        approved_cap = max(1, int(get_settings().optimizer_live_test_approved_cap))
        consumed = (
            await db.execute(
                select(func.count())
                .select_from(OptimizationLiveTestRequest)
                .where(
                    OptimizationLiveTestRequest.conversation_session_id
                    == conversation_session_id,
                    OptimizationLiveTestRequest.status.in_(_CONSUMED_STATUSES),
                )
            )
        ).scalar_one()
        if int(consumed or 0) >= approved_cap:
            return self._refuse(
                REFUSAL_QUOTA,
                f"This conversation has already used its {approved_cap} "
                "approved live test(s). Verification stays replay-only; record "
                "`needs_feedback` with what is missing instead. Nothing was "
                "recorded.",
            )

        expires_at = _utcnow() + timedelta(
            minutes=max(1, int(get_settings().optimizer_live_test_decision_ttl_minutes))
        )
        row = OptimizationLiveTestRequest(
            tenant_id=session.tenant_id,
            conversation_session_id=conversation_session_id,
            target_agent_type_id=subject_agent_type_id,
            script_version_id=target.script_version_id,
            status=OptimizationLiveTestStatus.pending,
            requested_operations=target.preview_entries(),
            expires_at=expires_at,
        )
        db.add(row)
        await db.flush()
        logger.info(
            "Recorded live-test request %s for conversation %s (subject=%s, "
            "script_version=%s, script=%s, preview=%d, expires=%s)",
            row.id,
            conversation_session_id,
            subject_agent_type_id,
            target.script_version_id,
            target.script_name,
            len(target.tool_preview),
            expires_at.isoformat(),
        )
        return LiveTestCreateResult(
            accepted=True,
            request_id=row.id,
            expires_at=expires_at,
            script=target,
        )

    async def _resolve_script_target(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID | None,
        subject_agent_type_id: uuid.UUID,
        script_version_id: Any,
    ) -> LiveTestScriptTarget | LiveTestCreateResult:
        """Load the requested version and prove it belongs to the subject.

        Returns the resolved target, or a refusal (nothing written).
        """
        from app.services.script_registry import ScriptRegistryService

        version_id = _parse_uuid(script_version_id)
        if version_id is None:
            return self._refuse(
                REFUSAL_INVALID_SCRIPT_VERSION,
                "A live test must name the SAVED script version to run. Call "
                "`generate_script` first, then pass its `version_id` as "
                "`script_version_id`. Nothing was recorded.",
            )

        service = ScriptRegistryService()
        version = await service.get_version(db, version_id, tenant_id)
        if version is None or not (version.python_source or "").strip():
            return self._refuse(
                REFUSAL_SCRIPT_VERSION_NOT_FOUND,
                "That script version was not found in this workspace or has no "
                "`python_source` to run. Save the script with `generate_script` "
                "and pass the returned `version_id`. Nothing was recorded.",
            )

        definition = (
            await service.get_definition(db, version.script_definition_id, tenant_id)
            if version.script_definition_id
            else None
        )
        if definition is None or definition.agent_type_id != subject_agent_type_id:
            return self._refuse(
                REFUSAL_OUT_OF_SCOPE,
                "That script belongs to a different agent type. A live test can "
                "only run this conversation's subject agent's own script, so "
                "nothing was recorded.",
            )

        preview = extract_tools_call_names(version.python_source or "")
        if not preview:
            return self._refuse(
                REFUSAL_NO_TOOL_CALLS,
                "This script has no literal `tools.call(...)` lines, so a live "
                "run would prove nothing and MCP tools are assumed to work. "
                "Nothing was recorded — record `needs_feedback` instead.",
            )

        return LiveTestScriptTarget(
            script_version_id=version.id,
            script_definition_id=version.script_definition_id,
            script_name=definition.name,
            script_version_label=version.version_label,
            python_source=version.python_source or "",
            tool_preview=tuple(preview),
        )

    @staticmethod
    def _refuse(reason_code: str, reason: str) -> LiveTestCreateResult:
        return LiveTestCreateResult(accepted=False, reason_code=reason_code, reason=reason)

    async def _allowed_tool_names(
        self, db: AsyncSession, agent_type_id: uuid.UUID
    ) -> set[str]:
        """The subject agent type's OWN granted tools (canonical names)."""
        from app.services.agents.permission_manager import AgentPermissionManager

        try:
            allowed = await AgentPermissionManager().calculate_agent_allowed_tools(
                agent_type_id, db
            )
        except Exception:  # noqa: BLE001 — fail closed: an unreadable grant set permits nothing
            logger.warning(
                "Could not resolve the tool grants for agent type %s — live "
                "tests stay refused",
                agent_type_id,
                exc_info=True,
            )
            return set()
        return {_canonical_tool_name(name) for name in allowed}

    # ── Reads ────────────────────────────────────────────────────────────────

    async def get(
        self, db: AsyncSession, request_id: uuid.UUID
    ) -> OptimizationLiveTestRequest | None:
        return await db.get(OptimizationLiveTestRequest, request_id)

    async def get_for_intervention(
        self, db: AsyncSession, intervene_request_id: uuid.UUID
    ) -> OptimizationLiveTestRequest | None:
        result = await db.execute(
            select(OptimizationLiveTestRequest).where(
                OptimizationLiveTestRequest.intervene_request_id == intervene_request_id
            )
        )
        return result.scalars().first()

    async def list_for_session(
        self, db: AsyncSession, conversation_session_id: uuid.UUID
    ) -> list[OptimizationLiveTestRequest]:
        result = await db.execute(
            select(OptimizationLiveTestRequest)
            .where(
                OptimizationLiveTestRequest.conversation_session_id
                == conversation_session_id
            )
            .order_by(OptimizationLiveTestRequest.created_at.desc())
        )
        return list(result.scalars().all())

    async def find_replay(
        self,
        db: AsyncSession,
        *,
        conversation_session_id: uuid.UUID,
        script_version_id: Any,
    ) -> OptimizationLiveTestRequest | None:
        """Find the request recorded for the SAME saved script version.

        Agent Runtime replays the interrupted tool task on resume, so the
        request arrives again. Matching the version lets the replay return the
        stored outcome (and never create a second row or a second approval).
        """
        version_id = _parse_uuid(script_version_id)
        if version_id is None:
            return None
        rows = await self.list_for_session(db, conversation_session_id)
        for row in rows:
            if row.script_version_id == version_id:
                return row
        return None

    # ── Decision (domain projection only; attribution lives on the response) ──

    async def mark_approved(
        self, db: AsyncSession, row: OptimizationLiveTestRequest
    ) -> None:
        """Record the positive operator decision (no execution evidence yet)."""
        if row.status is not OptimizationLiveTestStatus.pending:
            return
        row.status = OptimizationLiveTestStatus.approved
        await db.flush()

    async def mark_denied(
        self, db: AsyncSession, row: OptimizationLiveTestRequest
    ) -> None:
        """Record the negative operator decision — nothing may ever run."""
        if row.status in TERMINAL_STATUSES or row.status is OptimizationLiveTestStatus.approved:
            return
        row.status = OptimizationLiveTestStatus.denied
        await db.flush()
        logger.info("Live-test request %s denied by the operator", row.id)

    def is_overdue(
        self, row: OptimizationLiveTestRequest, *, now: datetime | None = None
    ) -> bool:
        expires_at = _ensure_tz(row.expires_at)
        return expires_at is not None and expires_at <= (now or _utcnow())

    async def mark_expired(
        self, db: AsyncSession, row: OptimizationLiveTestRequest
    ) -> None:
        """Close an overdue pending request as ``expired`` (idempotent)."""
        if row.status is not OptimizationLiveTestStatus.pending:
            return
        row.status = OptimizationLiveTestStatus.expired
        await db.flush()
        logger.info("Live-test request %s expired without a decision", row.id)

    # ── Single-shot execution gate ───────────────────────────────────────────

    async def begin_execution(
        self, db: AsyncSession, request_id: uuid.UUID
    ) -> bool:
        """Claim the single execution attempt for this request.

        One conditional ``UPDATE`` performs the whole check: the row must be
        ``pending``/``approved``, unexpired, and must never have started. Only
        the first caller gets ``True``; every later attempt gets ``False`` and
        must return the stored outcome instead of running anything.
        """
        now = _utcnow()
        result = await db.execute(
            update(OptimizationLiveTestRequest)
            .where(
                OptimizationLiveTestRequest.id == request_id,
                OptimizationLiveTestRequest.status.in_(
                    (
                        OptimizationLiveTestStatus.pending,
                        OptimizationLiveTestStatus.approved,
                    )
                ),
                OptimizationLiveTestRequest.execution_started_at.is_(None),
            )
            .values(
                status=OptimizationLiveTestStatus.approved,
                execution_started_at=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        claimed = (result.rowcount or 0) == 1
        if claimed:
            logger.info("Live-test request %s execution claimed (single-shot)", request_id)
        else:
            logger.info(
                "Live-test request %s execution NOT claimed — already consumed "
                "or no longer approved",
                request_id,
            )
        return claimed

    async def complete_execution(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        *,
        executed_operations: list[dict[str, Any]],
        failed: bool,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> None:
        """Persist the script run record exactly once (terminal status)."""
        row = await db.get(OptimizationLiveTestRequest, request_id)
        if row is None:
            logger.warning("Live-test request %s disappeared before completion", request_id)
            return
        row.executed_operations = list(executed_operations or [])
        row.status = (
            OptimizationLiveTestStatus.failed
            if failed
            else OptimizationLiveTestStatus.executed
        )
        row.execution_started_at = row.execution_started_at or started_at
        row.execution_finished_at = finished_at or _utcnow()
        await db.flush()
        logger.info(
            "Live-test request %s finished → %s (script run recorded: %s)",
            request_id,
            status_value(row.status),
            bool(row.executed_operations),
        )

    @staticmethod
    def build_script_run_record(
        *,
        script_version_id: uuid.UUID | str | None,
        script_name: str | None,
        script_version_label: str | None,
        status: str,
        result_summary: str | None,
        tool_calls: list[dict[str, Any]] | None,
        telemetry: dict[str, Any] | None,
        duration_ms: int | None,
        error: str | None,
    ) -> dict[str, Any]:
        """The persisted ``executed_operations`` entry for one script run.

        One entry describes the whole run (the script is the unit of
        execution): bounded result summary, per-``tools.call`` outcomes,
        telemetry and duration. Never contains credentials.
        """
        return {
            "kind": "script_run",
            "script_version_id": (
                str(script_version_id) if script_version_id is not None else None
            ),
            "script_name": script_name,
            "script_version_label": script_version_label,
            "status": status,
            "result_summary": result_summary,
            "error": error,
            "duration_ms": duration_ms,
            "tool_calls": list(tool_calls or []),
            "telemetry": dict(telemetry or {}),
        }

    # ── Expiry / cancellation ────────────────────────────────────────────────

    async def expire_overdue(
        self,
        db: AsyncSession,
        *,
        conversation_session_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> int:
        """Close overdue ``pending`` rows and settle their paused turns.

        Each expired request also cancels/resolves the linked pause as
        ``unresumable/expired`` (exactly one bounded-stop turn) so the operator
        sees what happened and nothing is retried.
        """
        current = now or _utcnow()
        stmt = select(OptimizationLiveTestRequest).where(
            OptimizationLiveTestRequest.status == OptimizationLiveTestStatus.pending,
        )
        if conversation_session_id is not None:
            stmt = stmt.where(
                OptimizationLiveTestRequest.conversation_session_id
                == conversation_session_id
            )
        rows = list((await db.execute(stmt)).scalars().all())

        expired = 0
        for row in rows:
            if not self.is_overdue(row, now=current):
                continue
            await self.mark_expired(db, row)
            await self.settle_expired_pause(db, row)
            expired += 1

        abandoned = await self._reap_abandoned_runs(db, now=current)
        if abandoned:
            logger.warning(
                "Live-test sweep closed %d abandoned execution(s) as failed",
                abandoned,
            )
        return expired

    async def _reap_abandoned_runs(
        self, db: AsyncSession, *, now: datetime
    ) -> int:
        """Close a claimed-but-never-completed run as ``failed``.

        ``begin_execution`` commits the claim *before* the network run, so a
        process that dies mid-run leaves an ``approved`` row with
        ``execution_started_at`` but no evidence. Such a row must never look
        approvable again (nothing may re-run): after a generous grace bound it is
        closed as ``failed`` with an explicit note.
        """
        run_timeout = int(
            getattr(get_settings(), "optimizer_live_test_run_timeout_seconds", 120)
        )
        grace = timedelta(seconds=max(300, run_timeout * 2))
        result = await db.execute(
            select(OptimizationLiveTestRequest).where(
                OptimizationLiveTestRequest.status
                == OptimizationLiveTestStatus.approved,
                OptimizationLiveTestRequest.execution_started_at.isnot(None),
                OptimizationLiveTestRequest.execution_finished_at.is_(None),
            )
        )
        closed = 0
        for row in result.scalars().all():
            started_at = _ensure_tz(row.execution_started_at)
            if started_at is not None and started_at > now - grace:
                continue
            row.status = OptimizationLiveTestStatus.failed
            row.execution_finished_at = now
            row.executed_operations = row.executed_operations or [
                self.build_script_run_record(
                    script_version_id=row.script_version_id,
                    script_name=None,
                    script_version_label=None,
                    status="error",
                    result_summary=None,
                    tool_calls=None,
                    telemetry=None,
                    duration_ms=None,
                    error=(
                        "The live-test run did not report a result (the runner "
                        "stopped). Nothing was retried."
                    ),
                )
            ]
            await db.flush()
            closed += 1
        return closed

    async def settle_expired_pause(
        self, db: AsyncSession, row: OptimizationLiveTestRequest
    ) -> None:
        """Resolve the linked pause as expired (one bounded-stop turn)."""
        from app.services.conversations.turn_resolution import (
            REASON_EXPIRED,
            resolve_unresumable_turn,
        )

        # Expire the still-pending intervention in the SAME transaction so the
        # REST/WS pending reads stop offering a card that can never run.
        if row.intervene_request_id is not None:
            request = await db.get(InterveneRequest, row.intervene_request_id)
            if request is not None and request.status is InterveneRequestStatus.pending:
                request.status = InterveneRequestStatus.expired
                request.responded_at = _utcnow()
                await db.flush()

        await resolve_unresumable_turn(
            db,
            row.conversation_session_id,
            reason_code=REASON_EXPIRED,
            resume_id=row.resume_id,
            intervene_request_id=row.intervene_request_id,
        )

    async def cancel_for_session(
        self, db: AsyncSession, conversation_session_id: uuid.UUID
    ) -> int:
        """Cancel any pending request of a session (ending the conversation)."""
        rows = await self.list_for_session(db, conversation_session_id)
        cancelled = 0
        for row in rows:
            if row.status is not OptimizationLiveTestStatus.pending:
                continue
            row.status = OptimizationLiveTestStatus.cancelled
            await db.flush()
            if row.intervene_request_id is not None:
                request = await db.get(InterveneRequest, row.intervene_request_id)
                if request is not None and request.status is InterveneRequestStatus.pending:
                    request.status = InterveneRequestStatus.cancelled
                    request.responded_at = _utcnow()
                    await db.flush()
            cancelled += 1
        if cancelled:
            logger.info(
                "Cancelled %d pending live-test request(s) for conversation %s",
                cancelled,
                conversation_session_id,
            )
        return cancelled

    # ── Audit ────────────────────────────────────────────────────────────────

    async def pending_intervention_summaries(
        self,
        db: AsyncSession,
        intervene_request_ids: Iterable[uuid.UUID],
    ) -> dict[uuid.UUID, dict[str, Any]]:
        """Map intervention id → live-test approval summary (for the reads)."""
        ids = [request_id for request_id in intervene_request_ids if request_id]
        if not ids:
            return {}
        rows = list(
            (
                await db.execute(
                    select(OptimizationLiveTestRequest).where(
                        OptimizationLiveTestRequest.intervene_request_id.in_(ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        labels = await self.script_labels(
            db, [row.script_version_id for row in rows if row.script_version_id]
        )
        summaries: dict[uuid.UUID, dict[str, Any]] = {}
        for row in rows:
            script_name, script_version_label = labels.get(
                row.script_version_id, (None, None)
            )
            summaries[row.intervene_request_id] = {  # type: ignore[index]
                "live_test_request_id": row.id,
                "status": status_value(row.status),
                "expires_at": row.expires_at,
                # The approved script — the unit of approval.
                "script_version_id": row.script_version_id,
                "script_name": script_name,
                "script_version_label": script_version_label,
                # The tool-call PREVIEW of the script that will run — not the
                # unit of execution.
                "operations": list(row.requested_operations or []),
                "executed_operations": (
                    list(row.executed_operations)
                    if row.executed_operations is not None
                    else None
                ),
                "target_agent_type_id": row.target_agent_type_id,
            }
        return summaries

    async def script_labels(
        self,
        db: AsyncSession,
        version_ids: Iterable[uuid.UUID | None],
    ) -> dict[uuid.UUID, tuple[str | None, str | None]]:
        """Map script version id → ``(script name, version label)``.

        Read-side projection only: the ledger row names the approved *version*,
        and the approval card shows the script it belongs to. No write, no
        tenant-less path (ids come from this tenant's own ledger rows).
        """
        ids = {version_id for version_id in version_ids if version_id}
        if not ids:
            return {}

        from app.db.models.script_registry import ScriptDefinition, ScriptVersion

        versions = list(
            (
                await db.execute(
                    select(
                        ScriptVersion.id,
                        ScriptVersion.script_definition_id,
                        ScriptVersion.version_label,
                    ).where(ScriptVersion.id.in_(ids))
                )
            ).all()
        )
        definition_ids = {
            row.script_definition_id for row in versions if row.script_definition_id
        }
        names: dict[uuid.UUID, str] = {}
        if definition_ids:
            names = {
                definition_id: name
                for definition_id, name in (
                    await db.execute(
                        select(ScriptDefinition.id, ScriptDefinition.name).where(
                            ScriptDefinition.id.in_(definition_ids)
                        )
                    )
                ).all()
            }
        return {
            row.id: (names.get(row.script_definition_id), row.version_label)
            for row in versions
        }

    async def session_audit(
        self, db: AsyncSession, conversation_session_id: uuid.UUID
    ) -> dict[str, Any]:
        """Replay-vs-live projection for a conversation.

        Replay evidence is an ``execute_script`` call in the raw tool log; live
        work is a call carrying the ledger pointer (set only by an approved,
        single-use live test). Replay evidence rows
        (``VerificationRun`` / ``ScriptExecutionRecord``) are untouched.
        """
        rows = (
            await db.execute(
                select(
                    RuntimeToolCall.tool_name,
                    RuntimeToolCall.optimization_live_test_request_id,
                    RuntimeToolCall.created_at,
                ).where(
                    RuntimeToolCall.session_kind
                    == RuntimeToolCallSessionKind.conversation,
                    RuntimeToolCall.session_id == conversation_session_id,
                )
            )
        ).all()

        replay_verifications = 0
        live_operations = 0
        live_timestamps: list[datetime] = []
        for tool_name, live_request_id, created_at in rows:
            if live_request_id is not None:
                live_operations += 1
                if created_at is not None:
                    live_timestamps.append(created_at)
                continue
            if _is_execute_script_tool(tool_name):
                replay_verifications += 1

        return {
            "replay_verifications": replay_verifications,
            "live_operations": live_operations,
            "last_live_at": max(live_timestamps) if live_timestamps else None,
            "replay_only": live_operations == 0,
        }


def _is_execute_script_tool(tool_name: str | None) -> bool:
    """True for the replay verification primitive (canonical/sanitised names)."""
    if not tool_name:
        return False
    return (
        tool_name == "execute_script"
        or tool_name.endswith("____execute_script")
        or tool_name.endswith("__execute_script")
    )


_service: OptimizationLiveTestService | None = None


def get_live_test_service() -> OptimizationLiveTestService:
    """Return the process-wide ledger service singleton."""
    global _service
    if _service is None:
        _service = OptimizationLiveTestService()
    return _service


__all__ = [
    "LiveTestCreateResult",
    "LiveTestOutcome",
    "LiveTestScriptTarget",
    "MAX_LIVE_TEST_PREVIEW_TOOLS",
    "OptimizationLiveTestService",
    "REFUSAL_ALREADY_PENDING",
    "REFUSAL_INVALID_SCRIPT_VERSION",
    "REFUSAL_NOT_PERMITTED",
    "REFUSAL_NO_TOOL_CALLS",
    "REFUSAL_OUT_OF_SCOPE",
    "REFUSAL_QUOTA",
    "REFUSAL_SCRIPT_VERSION_NOT_FOUND",
    "TERMINAL_STATUSES",
    "get_live_test_service",
    "outcome_of",
    "render_script_live_test_reason",
    "status_value",
]
