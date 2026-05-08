"""Test runtime executor LangGraph availability."""
import asyncio
from app.services.agents.runtime_executor import AgentRuntimeExecutor, _LANGGRAPH_AVAILABLE


async def test():
    print(f"_LANGGRAPH_AVAILABLE = {_LANGGRAPH_AVAILABLE}")
    executor = AgentRuntimeExecutor()
    print(f"Executor instance created: {executor}")


if __name__ == "__main__":
    asyncio.run(test())
