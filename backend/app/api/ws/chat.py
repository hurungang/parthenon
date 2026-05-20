"""WebSocket server — authenticates connections, runs conversational agent, persists turns."""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from app.core.oidc_client import OIDCError, get_oidc_client
from app.db.models.agents import AgentType
from app.db.models.conversations import ConversationSession, ConversationTurn, TurnRole
from app.db.session import AsyncSessionLocal
from app.services.agents.model_binding import ModelBindingError
from app.services.conversations.auto_namer import SessionAutoNamer
from app.services.conversations.store import ConversationStore

logger = logging.getLogger(__name__)

ws_router = APIRouter(tags=["WebSocket"])

_store = ConversationStore()


async def _build_augmented_system_instruction(
    agent_type: AgentType,
    db: Any,
) -> str | None:
    """Build system instruction augmented with SOP content, skills, and MCP session context.

    Conversation agents load SOPs, Skills, and MCP session context only.
    Plans are NOT injected here — plans are only for task agents (typed agents with
    structured input/output schemas) and are handled by AgentRuntimeExecutor._execute_job().
    Returns None if there is no instruction and no augmentation could be applied.
    """
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from sqlalchemy import select
    from app.db.models.agents import AgentRoleSOP, AgentRoleSkill
    from app.db.models.skills import Sop, Skill

    # Note: This is in Control Center context where db is available, data_client not needed
    executor = AgentRuntimeExecutor(data_client=None)
    instruction = agent_type.system_instruction or ""

    # Append SOP content if the agent has a primary SOP
    if agent_type.primary_sop_id:
        sop_content = await executor._load_sop_content(agent_type.primary_sop_id, db)
        if sop_content:
            instruction = f"{instruction}\n\n{sop_content}".strip()
            logger.debug(
                "Augmented instruction with primary SOP %s (%d chars)",
                agent_type.primary_sop_id,
                len(sop_content),
            )

    # Append ALL SOPs and Skills assigned to the agent's role
    if agent_type.role_id:
        # Load all SOPs for the role (skip primary_sop_id — already loaded above)
        try:
            sop_rows = await db.execute(
                select(Sop)
                .join(AgentRoleSOP, AgentRoleSOP.sop_id == Sop.id)
                .where(AgentRoleSOP.role_id == agent_type.role_id)
            )
            role_sops = list(sop_rows.scalars().all())
            for sop in role_sops:
                if sop.id == agent_type.primary_sop_id:
                    continue  # already included above
                sop_content = await executor._load_sop_content(sop.id, db)
                if sop_content:
                    instruction = f"{instruction}\n\n{sop_content}".strip()
                    logger.debug("Augmented instruction with role SOP %s", sop.id)
            logger.info(
                "Role %s has %d SOP(s) — injected into conversation agent instruction",
                agent_type.role_id,
                len(role_sops),
            )
        except Exception as exc:
            logger.warning(
                "Failed to load role SOPs for agent %s: %s", agent_type.id, exc
            )

        # Load all Skills for the role and inject their definitions
        try:
            skill_rows = await db.execute(
                select(Skill)
                .join(AgentRoleSkill, AgentRoleSkill.skill_id == Skill.id)
                .where(AgentRoleSkill.role_id == agent_type.role_id)
            )
            skills = list(skill_rows.scalars().all())
            if skills:
                skill_lines = [
                    "## Available Skills",
                    "You have been granted access to the following skills. "
                    "When the user asks you to use a skill, invoke it by name:",
                ]
                for skill in skills:
                    skill_lines.append(f"\n### {skill.name}")
                    if skill.description:
                        skill_lines.append(skill.description)
                    if skill.instructions:
                        skill_lines.append(f"\nInstructions: {skill.instructions}")
                skill_context = "\n".join(skill_lines)
                instruction = f"{instruction}\n\n{skill_context}".strip()
                logger.info(
                    "Augmented instruction with %d skill(s) for role %s: %s",
                    len(skills),
                    agent_type.role_id,
                    [s.name for s in skills],
                )
            else:
                logger.info(
                    "Role %s has no skills assigned — no skill context injected",
                    agent_type.role_id,
                )
        except Exception as exc:
            logger.warning(
                "Failed to load role skills for agent %s: %s", agent_type.id, exc
            )

        # Load MCP session context
        mcp_context = await executor._load_mcp_session_context(agent_type.role_id, db)
        if mcp_context:
            instruction = f"{instruction}\n\n{mcp_context}".strip()
            logger.debug("Augmented instruction with MCP session context for role %s", agent_type.role_id)

    logger.info(
        "Built augmented system instruction for agent %s: %d chars total (no plan for conversation agents)",
        agent_type.id,
        len(instruction),
    )

    return instruction or None


class WebSocketServer:
    """
    WebSocket endpoint handler.
    Authenticates the connection via token query param and returns claims.
    """

    @staticmethod
    async def authenticate(websocket: WebSocket) -> dict[str, Any] | None:
        """Validate the token query param and return claims, or None if invalid."""
        token = websocket.query_params.get("token")
        if not token:
            return None
        try:
            client = get_oidc_client()
            claims = await client.validate_token(token)
            return claims
        except OIDCError:
            return None


@ws_router.websocket("/ws/sessions/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str) -> None:
    """
    Conversational agent WebSocket endpoint.

    Authenticates the connection, processes each inbound user message by:
      1. Persisting a ConversationTurn (user role)
      2. Building message history from all session turns
      3. Calling the configured LLM via ModelBindingLayer
      4. Persisting the agent response as a ConversationTurn
      5. Returning the agent response to the client

    Auto-names the session on the first message.
    """
    server = WebSocketServer()
    claims = await server.authenticate(websocket)
    if not claims:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("WebSocket rejected: invalid token for session %s", session_id)
        return

    await websocket.accept()
    subject = claims.get("sub", "unknown")
    logger.info(
        "WebSocket connected: session=%s subject=%s",
        session_id,
        subject,
    )

    try:
        conv_session_id = uuid.UUID(session_id)
    except ValueError:
        await websocket.close(code=4003, reason="Invalid session ID format")
        return

    message_count = 0

    try:
        while True:
            raw_text = await websocket.receive_text()

            # Parse JSON payload — client sends {"message": "..."}
            try:
                payload = json.loads(raw_text)
                user_message: str = (
                    payload.get("message", raw_text)
                    if isinstance(payload, dict)
                    else raw_text
                )
            except (json.JSONDecodeError, AttributeError):
                user_message = raw_text

            user_message = user_message.strip()
            if not user_message:
                continue

            message_count += 1
            logger.debug(
                "Chat message %d for session %s: %.200s",
                message_count,
                session_id,
                user_message,
            )

            # Persist turns, call LLM, optionally auto-name
            agent_reply, session_title = await _process_message(
                conv_session_id=conv_session_id,
                user_message=user_message,
                is_first_message=(message_count == 1),
            )

            # Send agent response back to client
            await websocket.send_json(
                {
                    "sender_role": "agent",
                    "content": agent_reply,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

            # Push auto-generated title on first message
            if session_title:
                await websocket.send_json(
                    {"type": "title_update", "title": session_title}
                )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session=%s", session_id)
    except Exception as exc:
        logger.error("WebSocket error for session %s: %s", session_id, exc, exc_info=True)


async def _process_message(
    conv_session_id: uuid.UUID,
    user_message: str,
    is_first_message: bool,
) -> tuple[str, str | None]:
    """
    Persist user turn, call LLM, persist agent turn, optionally auto-name the session.

    Returns:
        (agent_reply, session_title) — session_title is set only on the first message.
    """
    conv_session: ConversationSession | None = None

    async with AsyncSessionLocal() as db:
        # Persist user turn (flush makes it visible to subsequent queries in this session)
        await _store.add_turn(conv_session_id, TurnRole.user, user_message, db)

        # Load conversation session to find the agent type
        conv_session = await db.get(ConversationSession, conv_session_id)

        agent_reply = _no_agent_message(conv_session)

        if conv_session and conv_session.agent_type_id:
            agent_type = await db.get(AgentType, conv_session.agent_type_id)
            if agent_type and agent_type.model_id:
                agent_reply = await _call_llm(
                    conv_session_id=conv_session_id,
                    agent_type=agent_type,
                    db=db,
                )

        # Persist agent turn
        await _store.add_turn(conv_session_id, TurnRole.agent, agent_reply, db)
        await db.commit()

    # Auto-name in a separate DB session to avoid mixing with turn commits
    session_title: str | None = None
    if is_first_message and conv_session and conv_session.agent_type_id:
        session_title = await _auto_name(
            conv_session_id=conv_session_id,
            first_message=user_message,
            agent_type_id=conv_session.agent_type_id,
        )

    return agent_reply, session_title


def _no_agent_message(conv_session: ConversationSession | None) -> str:
    """Return a graceful default reply when no agent is configured."""
    if conv_session is None:
        return "Conversation session not found."
    if conv_session.agent_type_id is None:
        return "No agent type is configured for this conversation session."
    return "No model is configured for this agent."


async def _call_llm(
    conv_session_id: uuid.UUID,
    agent_type: AgentType,
    db: Any,
) -> str:
    """Execute one conversation turn using the deep agent framework.

    Builds the full message history with an augmented system instruction (SOPs,
    Skills, MCP context) and delegates to
    ``AgentRuntimeExecutor.execute_conversation_turn()``, which runs the full
    observe-reason-act loop with tool-calling support.

    Returns the agent's text response, or a friendly error string on failure.
    """
    try:
        from app.services.agents.runtime_executor import AgentRuntimeExecutor

        # Note: This runs in Control Center context where db is available, data_client not needed
        executor = AgentRuntimeExecutor(data_client=None)

        # Build augmented system instruction (SOPs, skills, MCP context — no plan for conversation agents)
        system_instruction = await _build_augmented_system_instruction(agent_type, db)

        # Load all turns for message history (user turn just flushed is included)
        turns_result = await db.execute(
            select(ConversationTurn)
            .where(ConversationTurn.session_id == conv_session_id)
            .where(ConversationTurn.role.in_([TurnRole.user, TurnRole.agent]))
            .order_by(ConversationTurn.created_at)
        )
        turns = list(turns_result.scalars().all())

        messages: list[dict[str, str]] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        for turn in turns:
            role = "user" if turn.role == TurnRole.user else "assistant"
            messages.append({"role": role, "content": turn.content})

        logger.debug(
            "Delegating session %s to execute_conversation_turn (%d messages, system=%s)",
            conv_session_id,
            len(messages),
            bool(system_instruction),
        )
        return await executor.execute_conversation_turn(
            agent_type=agent_type,
            messages=messages,
            conv_session_id=conv_session_id,
            db=db,
        )

    except ModelBindingError as exc:
        logger.warning("Model binding error for session %s: %s", conv_session_id, exc)
        return f"Unable to process your message: {exc}"
    except Exception as exc:
        logger.error(
            "LLM call error for session %s: %s",
            conv_session_id,
            exc,
            exc_info=True,
        )
        return "An error occurred while processing your message. Please try again."


async def _auto_name(
    conv_session_id: uuid.UUID,
    first_message: str,
    agent_type_id: uuid.UUID,
) -> str | None:
    """Generate and persist a session title in a dedicated DB session."""
    try:
        async with AsyncSessionLocal() as db:
            namer = SessionAutoNamer()
            return await namer.generate_and_save(
                session_id=conv_session_id,
                first_user_message=first_message,
                agent_type_id=agent_type_id,
                db=db,
            )
    except Exception as exc:
        logger.warning("Auto-naming failed for session %s: %s", conv_session_id, exc)
        return None
