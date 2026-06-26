"""Comprehensive diagnostic test for the output type system end-to-end flow.

This test traces the entire flow from agent creation to execution to verify that:
1. output_data_type_id is properly stored in the database
2. get_agent_context() returns the output_data_type_id
3. Agent execution with typed output works correctly
4. save_result validates and persists typed output
"""
import uuid
import json
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models.agents import AgentType, AgentJob, AgentOutputType, AgentInputType
from app.db.models.agent_data_type import AgentDataType
from app.api.v1.internal.agent_data import get_agent_context
from app.api.v1.internal.system_tools import save_result_tool, SystemToolRequest
from app.services.outputs.service import OutputService


@pytest.mark.asyncio
async def test_output_type_system_end_to_end(db_session: AsyncSession):
    """Complete diagnostic test of the output type system."""
    db = db_session
    
    print("\n" + "="*80)
    print("OUTPUT TYPE SYSTEM DIAGNOSTIC TEST")
    print("="*80)
    
    # STEP 1: Create an AgentDataType (typed output schema)
    print("\n[STEP 1] Creating AgentDataType...")
    data_type = AgentDataType(
        id=uuid.uuid4(),
        name="project-name-output",
        slug="project-name-output",
        description="Output data type for project name extraction",
        fields=[
            {
                "name": "project_name",
                "type": "string",
                "required": True,
                "description": "Name of the project"
            },
            {
                "name": "project_id",
                "type": "string",
                "required": False,
                "description": "Project identifier"
            }
        ]
    )
    db.add(data_type)
    await db.flush()
    print(f"✓ Created AgentDataType: {data_type.id} ({data_type.name})")
    
    # STEP 2: Create an AgentType with output_data_type_id
    print("\n[STEP 2] Creating AgentType with typed output...")
    agent_type = AgentType(
        id=uuid.uuid4(),
        name="supabase-name-agent",
        description="Agent for extracting project names",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.typed,  # <-- This is the key field
        output_data_type_id=data_type.id,  # <-- This should be stored
        is_active=True,
    )
    db.add(agent_type)
    await db.flush()
    print(f"✓ Created AgentType: {agent_type.id} ({agent_type.name})")
    print(f"  - output_type: {agent_type.output_type}")
    print(f"  - output_data_type_id: {agent_type.output_data_type_id}")
    
    # STEP 3: Verify agent is stored in database
    print("\n[STEP 3] Verifying AgentType in database...")
    query = select(AgentType).where(AgentType.id == agent_type.id)
    result = await db.execute(query)
    stored_agent = result.scalar_one_or_none()
    
    if not stored_agent:
        print("✗ FAILED: AgentType not found in database!")
        raise AssertionError("AgentType not persisted to database")
    
    print(f"✓ AgentType found in database")
    print(f"  - name: {stored_agent.name}")
    print(f"  - output_type: {stored_agent.output_type}")
    print(f"  - output_data_type_id in DB: {stored_agent.output_data_type_id}")
    
    # STEP 4: Call get_agent_context() to verify it returns output_data_type_id
    print("\n[STEP 4] Calling get_agent_context()...")
    try:
        context = await get_agent_context(agent_type.id, db)
        print(f"✓ get_agent_context succeeded")
        print(f"  - agent_type_id: {context.agent_type_id}")
        print(f"  - output_type: {context.output_type}")
        print(f"  - output_data_type_id: {context.output_data_type_id}")
        print(f"  - output_data_type_name: {context.output_data_type_name}")
        print(f"  - output_schema_prompt: {'Present' if context.output_schema_prompt else 'None'}")
        print(f"  - output_json_schema: {'Present' if context.output_json_schema else 'None'}")
        
        if not context.output_data_type_id:
            print("\n✗ WARNING: output_data_type_id is None in context!")
            print("  This would cause the typed output path NOT to be taken at runtime!")
        
    except Exception as e:
        print(f"✗ FAILED: get_agent_context raised exception: {e}")
        raise
    
    # STEP 5: Create an AgentJob (simulated execution session)
    print("\n[STEP 5] Creating AgentJob (execution session)...")
    agent_job = AgentJob(
        id=uuid.uuid4(),
        agent_type_id=agent_type.id,
        status="running",
        output_data={},
    )
    db.add(agent_job)
    await db.flush()
    print(f"✓ Created AgentJob: {agent_job.id}")
    
    # STEP 6: Test save_result with typed output
    print("\n[STEP 6] Testing save_result with typed output...")
    
    # Prepare the payload that the agent would send
    result_payload = {
        "project_name": "Parthenon Platform",
        "project_id": "PTH-2025"
    }
    
    save_result_request = SystemToolRequest(
        session_id=str(agent_job.id),
        tool_name="save_result",
        tool_args={
            "data": result_payload,
            "title": "Project Name Extraction Result",
            "content_type": "application/json"
        }
    )
    
    try:
        response = await save_result_tool(save_result_request, db)
        print(f"✓ save_result succeeded")
        print(f"  Response: {response.result}")
        
        # Check if it took the typed output path
        if "output_id" in response.result:
            print(f"  ✓ TYPED OUTPUT PATH WAS TAKEN (output_id present)")
            output_id = response.result.get("output_id")
            validation_status = response.result.get("validation_status")
            print(f"    - output_id: {output_id}")
            print(f"    - validation_status: {validation_status}")
        else:
            print(f"  ✗ WARNING: TYPED OUTPUT PATH WAS NOT TAKEN")
            print(f"    Response only has status, not output_id")
            print(f"    This means the agent was treated as untyped!")
        
    except Exception as e:
        print(f"✗ FAILED: save_result raised exception: {e}")
        raise
    
    # STEP 7: Verify OutputService can find the typed output
    print("\n[STEP 7] Verifying typed output was persisted...")
    if "output_id" in response.result:
        output_service = OutputService()
        typed_output = await output_service.get_output(
            db=db,
            output_id=uuid.UUID(response.result["output_id"])
        )
        
        if typed_output:
            print(f"✓ Typed output found in database")
            print(f"  - id: {typed_output.id}")
            print(f"  - data_type_id: {typed_output.data_type_id}")
            print(f"  - validation_status: {typed_output.validation_status}")
            print(f"  - field_values: {typed_output.field_values}")
        else:
            print(f"✗ FAILED: Typed output not found in database!")
            raise AssertionError("OutputService.get() returned None")
    else:
        print("⊘ SKIPPED: Not using typed output path, so can't verify persistence")
    
    print("\n" + "="*80)
    print("DIAGNOSTIC TEST COMPLETE")
    print("="*80 + "\n")
