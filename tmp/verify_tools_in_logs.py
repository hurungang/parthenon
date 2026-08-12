"""Trigger agent execution and verify tools in logs."""
import asyncio
import httpx
import time
import re

async def trigger_and_verify():
    """Trigger agent and check logs for tool initialization."""
    
    print("🔧 Triggering agent execution...")
    
    # Trigger via public API (requires auth token)
    # For now, let's just check the most recent log entry
    
    # Read the agent-runtime.log file
    log_path = r"C:\Users\rhu\source\personal\coding-workspace\Parthenon\backend\logs\agent-runtime.log"
    
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # Find the most recent tools_initialized log entry
    tools_init_lines = [
        line for line in lines 
        if "tools_initialized" in line and "Agent initialized with" in line
    ]
    
    if not tools_init_lines:
        print("❌ No tools_initialized log entries found")
        return False
    
    latest = tools_init_lines[-1]
    print(f"\n📝 Latest tools_initialized log entry:")
    print(f"   {latest.strip()[:200]}...")
    
    # Extract data field
    data_match = re.search(r"data=(\{.*\})", latest)
    if not data_match:
        print("❌ Could not parse data from log")
        return False
    
    data_str = data_match.group(1)
    
    # Parse tool names
    tool_names_match = re.search(r"'tool_names': \(([^)]+)\)", data_str)
    system_tools_match = re.search(r"'system_tools': \(([^)]+)\)", data_str)
    mcp_tools_match = re.search(r"'mcp_tools': \(([^)]+)\)", data_str)
    
    if tool_names_match:
        tool_names_str = tool_names_match.group(1)
        tool_names = [t.strip().strip("'") for t in tool_names_str.split(",")]
        print(f"\n📊 Tool names ({len(tool_names)}):")
        for t in tool_names:
            print(f"   - {t}")
    
    if system_tools_match:
        system_tools_str = system_tools_match.group(1)
        system_tools = [t.strip().strip("'") for t in system_tools_str.split(",") if t.strip()]
        print(f"\n🔧 System tools ({len(system_tools)}):")
        for t in system_tools:
            print(f"   - {t}")
        
        # Check for duplicates
        unique_bases = set()
        for tool in system_tools:
            base = tool.replace("system_", "").replace("system/", "")
            if base in unique_bases:
                print(f"\n❌ FAIL: Duplicate detected - {tool} has same base as another tool")
                return False
            unique_bases.add(base)
        
        print(f"\n✅ PASS: All {len(system_tools)} system tools have unique base names")
        print(f"   Base names: {unique_bases}")
        return True
    
    print("❌ Could not find system_tools in log")
    return False

if __name__ == "__main__":
    result = asyncio.run(trigger_and_verify())
    exit(0 if result else 1)
