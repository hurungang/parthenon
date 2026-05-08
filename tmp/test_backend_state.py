"""Test current backend runtime_executor state via HTTP."""
import asyncio
import httpx


async def test():
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        # Check health endpoint
        response = await client.get("/health")
        print(f"Backend health: {response.status_code}")
        
        # Try to trigger a module check
        print("\nDirect module test:")
        from app.services.agents.runtime_executor import _LANGGRAPH_AVAILABLE
        print(f"_LANGGRAPH_AVAILABLE = {_LANGGRAPH_AVAILABLE}")


if __name__ == "__main__":
    asyncio.run(test())
