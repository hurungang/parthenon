# Skill & SOP Engine Test Plan

## What to Test
- Single-tool skill execution
- Multi-tool skill composition
- Step sequencing in SOPs
- Agent delegation and context passing

## Critical Scenarios
- Skill composes two tool calls
- SOP step delegates to a second agent type

## Edge Cases
- First tool succeeds, second fails (partial state)
- Circular agent delegation
- Delegated agent exceeds instance limit

## Test File References
- `backend/tests/unit/test_skill_executor.py`
- `backend/tests/unit/test_skill_sop.py`
- `e2e/tests/skills-sops.spec.ts`
