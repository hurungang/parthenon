"""RecursionValidationService — centralized SOP delegation graph cycle and dead-loop check.

Implements the Control Center authority for recursion/dead-loop validation across
agent create, update, and run contexts. Persists findings to SopRecursionValidationCheck
and SopRecursionValidationFinding for audit and compliance workflows.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.agents import AgentType, AgentRecursionValidationMode, AgentRecursionValidationStatus
from app.db.models.skills import SopStep, SopStepType, Sop
from app.db.models.sop_recursion_validation_check import (
    SopRecursionCheckContext,
    SopRecursionCheckOutcome,
    SopRecursionValidationCheck,
)
from app.db.models.sop_recursion_validation_finding import (
    SopRecursionFindingSeverity,
    SopRecursionFindingType,
    SopRecursionValidationFinding,
)
from app.services.agents.guardrails import detect_cycle_path

logger = logging.getLogger(__name__)

_MAX_GRAPH_NODES = 512


@dataclass(frozen=True)
class RecursionValidationResult:
    """Result of a recursion/dead-loop validation run."""

    passed: bool
    summary: str
    findings: list["RecursionFinding"] = field(default_factory=list)

    def is_blocking(self, mode: AgentRecursionValidationMode) -> bool:
        """Return True when the validation outcome should block the requested operation."""
        return not self.passed and mode == AgentRecursionValidationMode.strict_block


@dataclass(frozen=True)
class RecursionFinding:
    """Single recursion/dead-loop finding within a validation run."""

    finding_type: SopRecursionFindingType
    severity: SopRecursionFindingSeverity
    involved_sop_id: uuid.UUID | None
    involved_sop_step_id: uuid.UUID | None
    path_signature: str | None
    recommendation: str


class RecursionValidationError(Exception):
    """Raised when recursion validation fails in strict_block mode."""

    def __init__(self, summary: str, findings: list[RecursionFinding]) -> None:
        super().__init__(summary)
        self.summary = summary
        self.findings = findings


class RecursionValidationService:
    """
    Validates SOP delegation graphs for cycles and dead-loop risk.

    The service builds an adjacency map from agent type → delegated agent types
    via SOP steps with step_type=agent_delegation, then runs DFS cycle detection.

    Validation output is persisted to SopRecursionValidationCheck /
    SopRecursionValidationFinding so compliance workflows can query findings.
    """

    async def validate_agent_type(
        self,
        agent_type_id: uuid.UUID,
        context: SopRecursionCheckContext,
        db: AsyncSession,
        *,
        checked_by_user_id: uuid.UUID | None = None,
    ) -> RecursionValidationResult:
        """
        Run a recursion/dead-loop validation check for the given agent type.

        Raises RecursionValidationError when the agent type is in strict_block mode
        and validation fails. Always persists the check record and any findings.

        Returns the RecursionValidationResult for informational use by callers.
        """
        agent_type = await db.get(AgentType, agent_type_id)
        if agent_type is None:
            # Agent type not found — nothing to validate; treat as pass
            return RecursionValidationResult(passed=True, summary="Agent type not found; skipped")

        mode = agent_type.recursion_validation_mode
        result = await self._run_validation(agent_type_id=agent_type_id, db=db)

        # Persist the check record
        check = SopRecursionValidationCheck(
            checked_agent_type_id=agent_type_id,
            check_context=context,
            check_outcome=(
                SopRecursionCheckOutcome.pass_ if result.passed else SopRecursionCheckOutcome.fail
            ),
            checked_by_user_id=checked_by_user_id,
            summary=result.summary,
        )
        db.add(check)
        await db.flush()

        # Persist individual findings
        for finding in result.findings:
            db.add(
                SopRecursionValidationFinding(
                    validation_check_id=check.id,
                    finding_type=finding.finding_type,
                    severity=finding.severity,
                    involved_sop_id=finding.involved_sop_id,
                    involved_sop_step_id=finding.involved_sop_step_id,
                    path_signature=finding.path_signature,
                    recommendation=finding.recommendation,
                )
            )

        # Update the agent type's last validation snapshot
        from datetime import datetime, UTC

        agent_type.last_recursion_validation_status = (
            AgentRecursionValidationStatus.pass_ if result.passed else AgentRecursionValidationStatus.fail
        )
        agent_type.last_recursion_validation_at = datetime.now(UTC)
        db.add(agent_type)

        await db.flush()

        logger.info(
            "Recursion validation for agent_type=%s context=%s outcome=%s findings=%d",
            agent_type_id,
            context.value,
            "pass" if result.passed else "fail",
            len(result.findings),
        )

        if result.is_blocking(mode):
            raise RecursionValidationError(
                summary=result.summary,
                findings=result.findings,
            )

        return result

    # ── Internal graph building and cycle detection ────────────────────────────

    async def _run_validation(
        self,
        agent_type_id: uuid.UUID,
        db: AsyncSession,
    ) -> RecursionValidationResult:
        """Build the delegation graph for the agent type and check for cycles."""
        adjacency: dict[str, list[str]] = {}
        step_map: dict[tuple[str, str], tuple[uuid.UUID | None, uuid.UUID | None]] = {}

        try:
            await self._build_adjacency(
                agent_type_id=agent_type_id,
                db=db,
                adjacency=adjacency,
                step_map=step_map,
                visited_types=set(),
            )
        except ValueError as exc:
            return RecursionValidationResult(
                passed=False,
                summary=f"Delegation graph traversal failed: {exc}",
                findings=[
                    RecursionFinding(
                        finding_type=SopRecursionFindingType.dead_loop_risk,
                        severity=SopRecursionFindingSeverity.error,
                        involved_sop_id=None,
                        involved_sop_step_id=None,
                        path_signature=None,
                        recommendation="Reduce the delegation graph size or depth.",
                    )
                ],
            )

        if not adjacency:
            return RecursionValidationResult(
                passed=True,
                summary="No delegation edges found; graph is cycle-free.",
            )

        root_node = str(agent_type_id)
        cycle_path = detect_cycle_path(adjacency, root_node, max_nodes=_MAX_GRAPH_NODES)

        if cycle_path is None:
            return RecursionValidationResult(
                passed=True,
                summary=(
                    f"Delegation graph validated: {len(adjacency)} node(s), no cycles detected."
                ),
            )

        # Resolve UUIDs in the cycle path to human-readable names
        name_map: dict[str, str] = {}
        for node in cycle_path:
            try:
                uid = uuid.UUID(node)
                at = await db.get(AgentType, uid)
                name_map[node] = at.name if at and at.name else node
            except (ValueError, Exception):
                name_map[node] = node
        named_path = [name_map[n] for n in cycle_path]
        path_sig = " → ".join(named_path)

        findings: list[RecursionFinding] = []
        for i, node in enumerate(cycle_path[:-1]):
            next_node = cycle_path[i + 1]
            sop_id, step_id = step_map.get((node, next_node), (None, None))
            findings.append(
                RecursionFinding(
                    finding_type=SopRecursionFindingType.cycle_detected,
                    severity=SopRecursionFindingSeverity.error,
                    involved_sop_id=sop_id,
                    involved_sop_step_id=step_id,
                    path_signature=path_sig,
                    recommendation=(
                        f"Remove the delegation step from agent '{name_map[node]}' "
                        f"to agent '{name_map[next_node]}' "
                        "to break the cycle, or restructure the SOP delegation graph."
                    ),
                )
            )

        return RecursionValidationResult(
            passed=False,
            summary=f"Cycle detected in delegation graph: {path_sig}",
            findings=findings,
        )

    async def _build_adjacency(
        self,
        agent_type_id: uuid.UUID,
        db: AsyncSession,
        adjacency: dict[str, list[str]],
        step_map: dict[tuple[str, str], tuple[uuid.UUID | None, uuid.UUID | None]],
        visited_types: set[str],
    ) -> None:
        """Recursively populate the adjacency map from SOP delegation steps."""
        node_key = str(agent_type_id)
        if node_key in visited_types:
            return
        visited_types.add(node_key)

        if len(adjacency) >= _MAX_GRAPH_NODES:
            raise ValueError(f"Graph node limit ({_MAX_GRAPH_NODES}) reached during traversal.")

        agent_type = await db.get(AgentType, agent_type_id)
        if agent_type is None or agent_type.role_id is None:
            adjacency.setdefault(node_key, [])
            return

        # Load bound SOPs/skills to determine which SOPs to check
        from app.db.models.agents import (
            AgentRoleSOP,
            AgentTypeSopBinding,
            AgentTypeSkillBinding,
        )

        has_sop_bindings = await db.execute(
            select(AgentTypeSopBinding.id).where(
                AgentTypeSopBinding.agent_type_id == agent_type.id
            )
        )
        has_skill_bindings = await db.execute(
            select(AgentTypeSkillBinding.id).where(
                AgentTypeSkillBinding.agent_type_id == agent_type.id
            )
        )
        has_explicit_bindings = (
            has_sop_bindings.first() is not None
            or has_skill_bindings.first() is not None
        )

        if has_explicit_bindings:
            # Only use bound SOPs — not the entire role's SOPs
            binding_result = await db.execute(
                select(AgentTypeSopBinding.sop_id).where(
                    AgentTypeSopBinding.agent_type_id == agent_type.id
                )
            )
            sop_ids = [row[0] for row in binding_result.fetchall()]
        else:
            # Fallback: use all role-assigned SOPs
            role_sop_result = await db.execute(
                select(AgentRoleSOP).where(AgentRoleSOP.role_id == agent_type.role_id)
            )
            role_sop_rows = role_sop_result.scalars().all()
            sop_ids = [row.sop_id for row in role_sop_rows]

        adjacency.setdefault(node_key, [])

        if not sop_ids:
            return

        # Load delegation steps from all SOPs assigned to this agent
        step_result = await db.execute(
            select(SopStep).where(
                SopStep.sop_id.in_(sop_ids),
                SopStep.step_type == SopStepType.agent_delegation,
                SopStep.target_agent_type_id.isnot(None),
            )
        )
        delegation_steps = step_result.scalars().all()

        for step in delegation_steps:
            target_id_str = str(step.target_agent_type_id)
            if target_id_str not in adjacency[node_key]:
                adjacency[node_key].append(target_id_str)
            step_map[(node_key, target_id_str)] = (step.sop_id, step.id)

            # Recurse into the target agent type
            await self._build_adjacency(
                agent_type_id=step.target_agent_type_id,
                db=db,
                adjacency=adjacency,
                step_map=step_map,
                visited_types=visited_types,
            )


_recursion_validation_service = RecursionValidationService()


def get_recursion_validation_service() -> RecursionValidationService:
    """Return the shared RecursionValidationService singleton."""
    return _recursion_validation_service
