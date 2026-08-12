"""Test that system tools are not duplicated after fix."""
import asyncio
import httpx
import sys

async def test_agent_context():
    """Fetch agent context and verify no duplicate system tools."""
    
    # Get agent context from Control Center internal API
    # This requires service certificate but we'll test without for now
    url = "http://localhost:8000/api/v1/internal/data/agent-types/11ea1b70-2bb1-4e8a-9626-012d78979df7/context"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            
            if response.status_code == 401:
                print("❌ 401 Unauthorized - need service certificate")
                print("   Let me check logs from an actual agent execution instead...")
                return False
                
            response.raise_for_status()
            data = response.json()
            
            tool_definitions = data.get("tool_definitions", [])
            tool_names = [t.get("function", {}).get("name") for t in tool_definitions]
            
            print(f"\n=== Agent Context Test Results ===")
            print(f"Total tools: {len(tool_names)}")
            print(f"Tool names: {tool_names}")
            
            # Check for duplicates
            system_tools = [
                name for name in tool_names 
                if any(st in name for st in ["save_result", "send_notification", "get_recipient_group"])
            ]
            
            print(f"\nSystem-related tools found: {system_tools}")
            
            # Check if we have duplicates
            unique_base_names = set()
            duplicates = []
            
            for name in system_tools:
                base = name.replace("system_", "").replace("system/", "")
                if base in unique_base_names:
                    duplicates.append(name)
                unique_base_names.add(base)
            
            if duplicates:
                print(f"\n❌ FAIL: Found duplicate system tools: {duplicates}")
                return False
            else:
                print(f"\n✅ PASS: No duplicate system tools found")
                print(f"   Unique system tool base names: {unique_base_names}")
                return True
                
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_agent_context())
    sys.exit(0 if result else 1)
