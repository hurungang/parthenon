"""Test the logs endpoint."""
import asyncio
import httpx


async def test_logs_endpoint():
    # Test with the session that has logs
    session_id = "4fbf7c79-9a5d-4a7a-8163-1ba8d44fbd9e"
    
    # Get a token first by logging in
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        # Try to get logs (this will fail without auth, but we'll see if it's 404 or 401)
        print(f"Testing GET /api/v1/agents/sessions/{session_id}/logs")
        response = await client.get(f"/api/v1/agents/sessions/{session_id}/logs")
        print(f"Status: {response.status_code}")
        if response.status_code == 401:
            print("Response: Unauthorized (expected - needs auth)")
        elif response.status_code == 404:
            print("Response: 404 Not Found (PROBLEM - endpoint not registered)")
        elif response.status_code == 200:
            print(f"Response: {response.json()}")
        else:
            print(f"Response: {response.text}")


if __name__ == "__main__":
    asyncio.run(test_logs_endpoint())
