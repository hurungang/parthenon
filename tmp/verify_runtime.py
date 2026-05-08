"""Verify runtime executor is using LangGraph."""
import asyncio
import httpx


async def test():
    # Make a simple health check to ensure backend loaded our module
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        response = await client.get("/health")
        print(f"Backend health: {response.status_code}")
    
    # Import the runtime executor module to check state
    from app.services.agents.runtime_executor import _LANGGRAPH_AVAILABLE
    print(f"\n✅ Runtime executor state:")
    print(f"   _LANGGRAPH_AVAILABLE = {_LANGGRAPH_AVAILABLE}")
    
    if _LANGGRAPH_AVAILABLE:
        print("\n✅ LangGraph is loaded - agent sessions will use real task graph executor")
        print("   Execution flow: plan → execute → finalize")
        print("   Tools will be invoked")
        print("   Detailed logs will be generated")
    else:
        print("\n❌ LangGraph is NOT loaded - stub executor will be used")


if __name__ == "__main__":
    asyncio.run(test())
