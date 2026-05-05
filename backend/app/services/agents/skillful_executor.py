"""Skillful Agent Executor — LLM reasoning loop with skill selection and invocation."""
import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentInstance, AgentType
from app.services.agents.model_binding import ModelBindingLayer
from app.services.skills.executor import SkillExecutor

logger = logging.getLogger(__name__)

MAX_TURNS = 10  # Safety limit for the reasoning loop


class SkillfulAgentError(Exception):
    """Raised when a skillful-agent execution fails."""


class SkillfulAgentExecutor:
    """
    Executes a user prompt for a skillful-agent instance using an LLM reasoning loop.

    The loop:
      1. Build skill definitions as LLM tool schemas.
      2. Send prompt + conversation history to the LLM.
      3. If LLM selects a skill, invoke it via SkillExecutor.
      4. Add skill result to context and repeat until LLM returns a final answer.
    """

    def __init__(
        self,
        model_layer: ModelBindingLayer | None = None,
        skill_executor: SkillExecutor | None = None,
    ) -> None:
        self._model = model_layer or ModelBindingLayer()
        self._skill_executor = skill_executor or SkillExecutor()

    async def execute(
        self,
        instance: AgentInstance,
        prompt: str,
        context: dict[str, Any] | None,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        Execute a prompt against a skillful-agent instance.

        Returns:
            Final response dict with answer and turn history.
        """
        agent_type = await db.get(AgentType, instance.agent_type_id)
        if not agent_type:
            raise SkillfulAgentError(f"Agent type {instance.agent_type_id} not found")

        # NOTE: mode check removed; mode-based routing superseded by AgentRole in this change.

        # Load available skills for this agent type
        skill_defs, skill_map = await self._load_skills(agent_type.id, db)

        # Build initial message history
        messages: list[dict[str, str]] = []
        if agent_type.system_instruction:
            messages.append({"role": "system", "content": agent_type.system_instruction})
        if context:
            messages.append(
                {"role": "system", "content": f"Context: {json.dumps(context)}"}
            )
        messages.append({"role": "user", "content": prompt})

        turn_history: list[dict[str, Any]] = []

        for turn in range(MAX_TURNS):
            response = await self._model.complete(
                agent_type=agent_type,
                messages=messages,
                tools=skill_defs if skill_defs else None,
            )

            tool_calls = ModelBindingLayer.extract_tool_calls(response, agent_type.llm_provider)
            text_response = ModelBindingLayer.extract_text(response, agent_type.llm_provider)

            if not tool_calls:
                # Final answer — LLM returned text without tool calls
                logger.info(
                    "skillful-agent %s completed in %d turns", instance.id, turn + 1
                )
                return {
                    "agent_type": agent_type.name,
                    "instance_id": str(instance.id),
                    "answer": text_response,
                    "turns": turn_history,
                }

            # Process tool calls
            for tc in tool_calls:
                skill_name = tc.get("function", {}).get("name", "")
                args_str = tc.get("function", {}).get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    args = {}

                skill_id = skill_map.get(skill_name)
                if not skill_id:
                    logger.warning("LLM requested unknown skill: %s", skill_name)
                    tool_result = {"error": f"Unknown skill: {skill_name}"}
                else:
                    logger.info(
                        "skillful-agent %s invoking skill '%s' (turn %d)",
                        instance.id, skill_name, turn + 1,
                    )
                    skill_results = await self._skill_executor.execute(
                        skill_id=skill_id,
                        tool_input=args,
                        db=db,
                    )
                    tool_result = {"skill": skill_name, "results": skill_results}

                turn_history.append({"turn": turn + 1, "skill": skill_name, "result": tool_result})

                # Add tool result to conversation
                messages.append({"role": "assistant", "content": text_response or ""})
                messages.append(
                    {
                        "role": "tool",
                        "content": json.dumps(tool_result),
                        "tool_call_id": tc.get("id", ""),
                    }
                )

        # Safety: exceeded turn limit
        logger.warning("skillful-agent %s exceeded turn limit (%d)", instance.id, MAX_TURNS)
        return {
            "agent_type": agent_type.name,
            "instance_id": str(instance.id),
            "answer": "Maximum reasoning turns reached without a final answer.",
            "turns": turn_history,
        }

    async def _load_skills(
        self, agent_type_id: Any, db: AsyncSession
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """
        Load skills for this agent type via its AgentRole.

        NOTE: Skill resolution via AgentRole is implemented in Phase 4 (PermissionManager).
        Returns empty lists until Phase 4 is complete.
        """
        # TODO Phase 4: resolve skills via AgentType.role → AgentRoleSkill/AgentRoleSOP
        return [], {}
