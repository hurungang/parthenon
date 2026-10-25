"""Command Prompt storage — the mission text for command-driven special agents.

A *command prompt* is a stored, named mission that drives a special agent
execution (e.g. ``optimize-and-verify``). Clicking a UI action ("Optimize &
Verify") launches a SIDE EXECUTION whose user prompt is this command's mission
(with the target ``agent_type_id`` interpolated), NOT the agent type's own
system instruction. The agent runs its usual deep-agent loop (model + tools),
but the *prompt* and *toolset* come from the command, not the agent type.

This is deliberately a small, purpose-built table rather than overloading the
Skill/SOP model: a command prompt is not a permission-grantable skill an agent
invokes — it is the mission a special execution runs. Keeping it separate
avoids conflating the two concepts and keeps the permission model intact.

Ownership invariant: Control-Center-owned (sole DB gateway).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CommandPrompt(Base):
    """A stored command mission for command-driven special agent executions."""

    __tablename__ = "command_prompts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Stable, human-readable slug (e.g. "optimize-and-verify").
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    # Display name (e.g. "Optimize & Verify").
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # The full mission text. ``{agent_type_id}`` is interpolated at launch time.
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", default=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<CommandPrompt id={self.id} slug={self.slug}>"
