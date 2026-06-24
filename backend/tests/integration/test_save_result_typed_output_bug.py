"""
Integration test to reproduce FIX-20260624-153000:
Bug — Agent types with output_data_type_id configured are NOT calling the save_result system tool

This test demonstrates the bug:
- An AgentType is configured with output_data_type_id (typed output)
- When get_agent_context is called for that agent type
- The response shows output_data_type_id but does NOT include save_result in allowed_tools
- This prevents the agent from calling save_result to persist typed outputs

The test SHOULD FAIL because the bug exists. Once fixed, it will pass.
"""
import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models.agents import AgentType, AgentInputType, AgentOutputType
from app.db.models.agent_data_type import AgentDataType
from app.api.v1.internal.agent_data import get_agent_context


@pytest.mark.asyncio
async def test_get_agent_context_with_typed_output_missing_save_result(db_session: AsyncSession):
    """
    Reproduce FIX-20260624-153000: get_agent_context doesn't include save_result
    in allowed_tools when agent type has output_data_type_id configured.
    
    This test demonstrates the BUG — it SHOULD FAIL initially to prove the bug exists.
    
    Setup:
      1. Create an AgentDataType (typed output schema)
      2. Create an AgentType with output_data_type_id set (typed agent)
      3. Call get_agent_context for the typed agent type
    
    Assertion:
      - output_data_type_id should be present in context ✓
      - save_result SHOULD be in allowed_tools (but currently ISN'T — THE BUG)
    """
    db = db_session
    
    print("\n" + "="*80)
    print("TEST: get_agent_context missing save_result for typed output")
    print("Bug: FIX-20260624-153000")
    print("="*80)
    
    # ──────────────────────────────────────────────────────────────────────────
    # STEP 1: Create an AgentDataType (typed output schema)
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[STEP 1] Creating AgentDataType...")
    data_type = AgentDataType(
        id=uuid.uuid4(),
        name="incident-report-output",
        slug="incident-report-output",
        description="Structured output for incident reports",
        fields=[
            {
                "name": "incident_id",
                "type": "string",
                "required": True,
                "description": "Unique incident identifier",
            },
            {
                "name": "severity",
                "type": "enum",
                "enum_values": ["critical", "high", "medium", "low"],
                "required": True,
                "description": "Incident severity level",
            },
            {
                "name": "description",
                "type": "string",
                "required": True,
                "description": "Incident description",
            },
        ]
    )
    db.add(data_type)
    await db.flush()
    print(f"✓ Created AgentDataType: {data_type.id}")
    print(f"  - name: {data_type.name}")
    print(f"  - fields: {len(data_type.fields)} fields")
    
    # ──────────────────────────────────────────────────────────────────────────
    # STEP 2: Create an AgentType WITH output_data_type_id (THE KEY PART)
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[STEP 2] Creating AgentType with output_data_type_id...")
    agent_type = AgentType(
        id=uuid.uuid4(),
        name="incident-analyzer-agent",
        description="Agent for analyzing and reporting incidents with typed output",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.typed,  # Non-conversational, typed output
        output_data_type_id=data_type.id,   # <-- KEY: Agent has typed output configured
        is_active=True,
    )
    db.add(agent_type)
    await db.flush()
    print(f"✓ Created AgentType with typed output")
    print(f"  - name: {agent_type.name}")
    print(f"  - output_type: {agent_type.output_type}")
    print(f"  - output_data_type_id: {agent_type.output_data_type_id}")
    
    # ──────────────────────────────────────────────────────────────────────────
    # STEP 3: Call get_agent_context and check for save_result
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[STEP 3] Calling get_agent_context()...")
    context = await get_agent_context(agent_type.id, db)
    
    print(f"✓ get_agent_context returned successfully")
    print(f"  - output_type: {context.output_type}")
    print(f"  - output_data_type_id: {context.output_data_type_id}")
    print(f"  - output_data_type_name: {context.output_data_type_name}")
    print(f"  - allowed_tools: {sorted(context.allowed_tools)}")
    
    # ──────────────────────────────────────────────────────────────────────────
    # ASSERTIONS: Check if save_result is in allowed_tools
    # ──────────────────────────────────────────────────────────────────────────
    print("\n" + "="*80)
    print("ASSERTION CHECKS")
    print("="*80)
    
    # This assertion should PASS
    assert context.output_data_type_id is not None, (
        "output_data_type_id should be present in context"
    )
    print(f"✓ Assertion 1 PASSED: output_data_type_id is present: {context.output_data_type_id}")
    
    # This assertion REPRODUCES THE BUG (should FAIL initially, PASS after fix)
    print(f"\nAssertion 2: Checking if 'system____save_result' is in allowed_tools...")
    print(f"  allowed_tools: {context.allowed_tools}")
    print(f"  ⚠ This assertion will FAIL if the bug exists (save_result missing from allowed_tools)")
    
    assert "system____save_result" in context.allowed_tools, (
        "BUG FIX-20260624-153000: save_result SHOULD be in allowed_tools when "
        "agent type has output_data_type_id configured.\n"
        f"\nExpected: 'system____save_result' in allowed_tools\n"
        f"Actual: allowed_tools = {sorted(context.allowed_tools)}\n\n"
        "ROOT CAUSE: The get_agent_context endpoint doesn't add save_result to allowed_tools "
        "when output_data_type_id is set. This prevents typed agents from calling save_result "
        "to persist their typed outputs."
    )
    print(f"✓ Assertion 2 PASSED: save_result is in allowed_tools")
    
    print("\n" + "="*80)
    print("✓ TEST PASSED (bug has been fixed!)")
    print("="*80)
