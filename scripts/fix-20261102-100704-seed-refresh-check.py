"""FIX-20261102-100704 — verify seeded assistant rows converge to the generic text.

Runs the SAME idempotent refresh the CC startup hook runs (``AssistantSeeder``)
against the configured database, reporting before/after counts per tenant, so
the generic instruction/digest refresh can be verified without waiting for a
stack restart.  Read/write is limited to the seeded system rows.

Usage:  .venv/bin/python scripts/fix-20261102-100704-seed-refresh-check.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.db.models.agents import AgentType  # noqa: E402
from app.db.models.skills import Skill  # noqa: E402
from app.db.models.tenant import Tenant  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.services.agents.assistant_seeder import (  # noqa: E402
    ASSISTANT_AGENT_TYPE_NAME,
    ASSISTANT_SYSTEM_INSTRUCTION,
    MANAGEMENT_SKILL_INSTRUCTIONS,
    MANAGEMENT_SKILL_NAME,
    AssistantSeeder,
)


async def _snapshot(session) -> dict[str, int]:
    tenants = (await session.execute(select(Tenant.id))).scalars().all()
    agents = (
        (await session.execute(
            select(AgentType).where(AgentType.name == ASSISTANT_AGENT_TYPE_NAME)
        )).scalars().all()
    )
    skills = (
        (await session.execute(
            select(Skill).where(Skill.name == MANAGEMENT_SKILL_NAME)
        )).scalars().all()
    )
    return {
        "tenants": len(tenants),
        "assistant_rows": len(agents),
        "agents_current": sum(
            1 for a in agents if a.system_instruction == ASSISTANT_SYSTEM_INSTRUCTION
        ),
        "skills_current": sum(
            1 for s in skills if s.instructions == MANAGEMENT_SKILL_INSTRUCTIONS
        ),
    }


async def main() -> int:
    async with AsyncSessionLocal() as session:
        before = await _snapshot(session)
        summary = await AssistantSeeder().run(session)
        await session.commit()
        after = await _snapshot(session)

    print("tenants:              ", before["tenants"])
    print("before  agents current:", before["agents_current"], "/", before["assistant_rows"])
    print("before  skills current:", before["skills_current"], "/", before["assistant_rows"])
    print("after   agents current:", after["agents_current"], "/", after["assistant_rows"])
    print("after   skills current:", after["skills_current"], "/", after["assistant_rows"])
    print("summary per tenant:   ", summary["per_tenant"])

    ok = (
        after["agents_current"] == after["assistant_rows"] == before["tenants"]
        and after["skills_current"] == after["assistant_rows"]
    )
    print("SEED-REFRESH:", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
