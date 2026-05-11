import { describe, it, expect } from 'vitest'
import { presentLog, isWorkingStepSpan } from '../services/LogPresenter'
import type { ExecutionLogEntry, ExecutionLogRead } from '../types'

// ── Fixtures ───────────────────────────────────────────────────────────────────

function makeLog(overrides: Partial<ExecutionLogRead> = {}): ExecutionLogRead {
  return {
    id: 'log-1',
    session_id: 'sess-1',
    system_instruction: null,
    user_prompt: null,
    logged_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

let entryCounter = 0
function makeEntry(overrides: Partial<ExecutionLogEntry> = {}): ExecutionLogEntry {
  entryCounter++
  return {
    id: `entry-${entryCounter}`,
    timestamp: '2026-01-01T00:01:00Z',
    event_type: 'info',
    log_level: 'INFO',
    message: 'Test message',
    data: {},
    ...overrides,
  }
}

/** Creates a session_started entry the way the runtime executor does. */
function makeSessionStartedEntry(overrides: {
  model_id?: string
  identity_name?: string
  role_name?: string
} = {}): ExecutionLogEntry {
  return makeEntry({
    event_type: 'session_started',
    message: 'Session execution started',
    data: {
      agent_type_id: 'type-uuid',
      model_id: overrides.model_id ?? 'gpt-4o',
      input_type: 'typed',
      system_instruction_length: 100,
      identity_name: overrides.identity_name ?? null,
      role_name: overrides.role_name ?? null,
    },
  })
}

/** Creates a sops_skills_loaded entry the way the runtime executor does. */
function makeSopsSkillsEntry(
  sops: string[] = [],
  skills: string[] = []
): ExecutionLogEntry {
  return makeEntry({
    event_type: 'sops_skills_loaded',
    message: 'Loaded SOPs and Skills',
    data: {
      role_id: 'role-uuid',
      sops: sops.map((name) => ({ id: 'id', name })),
      skills: skills.map((name) => ({ id: 'id', name })),
    },
  })
}

const SYSTEM_INSTRUCTION_WITH_PLAN = `
You are a helpful assistant.

---
## Pre-Approved Implementation Plan

**Step 1** [tool] — Load Dataset
  Load the dataset from source.

**Step 2** [tool] — Validate Schema
  Validate the data schema.

**Step 3** [tool] — Run Analysis
  Run the analysis pipeline.

**Step 4** [tool] — Export Results
  Export the results.
---
`

const SYSTEM_INSTRUCTION_NUMBERED = `
Implementation Plan:
1. Load the dataset from the source
2. Validate the data schema
3. Run the analysis pipeline
4. Export the results
`

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('presentLog — summary: model, identity, role from entries', () => {
  it('extracts model from session_started entry data', () => {
    const result = presentLog(makeLog(), [makeSessionStartedEntry({ model_id: 'claude-3-opus' })])
    expect(result.summary.model).toBe('claude-3-opus')
  })

  it('extracts model from llm_request entry when no session_started', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ event_type: 'llm_request', data: { model_id: 'gpt-4-turbo' } }),
    ])
    expect(result.summary.model).toBe('gpt-4-turbo')
  })

  it('extracts identity_name from session_started entry data', () => {
    const result = presentLog(makeLog(), [
      makeSessionStartedEntry({ identity_name: 'data-agent@example.com' }),
    ])
    expect(result.summary.identity).toBe('data-agent@example.com')
  })

  it('extracts role_name from session_started entry data', () => {
    const result = presentLog(makeLog(), [
      makeSessionStartedEntry({ role_name: 'DataAnalyst' }),
    ])
    expect(result.summary.role).toBe('DataAnalyst')
  })

  it('returns null for identity when session_started entry has no identity_name', () => {
    const result = presentLog(makeLog(), [makeSessionStartedEntry()])
    expect(result.summary.identity).toBeNull()
  })

  it('returns null for role when session_started entry has no role_name', () => {
    const result = presentLog(makeLog(), [makeSessionStartedEntry()])
    expect(result.summary.role).toBeNull()
  })

  it('returns null for model when no entries', () => {
    const result = presentLog(makeLog(), [])
    expect(result.summary.model).toBeNull()
  })

  it('returns null for identity when no entries', () => {
    const result = presentLog(makeLog(), [])
    expect(result.summary.identity).toBeNull()
  })

  it('returns null for role when no entries', () => {
    const result = presentLog(makeLog(), [])
    expect(result.summary.role).toBeNull()
  })
})

describe('presentLog — summary: SOPs and skills from sops_skills_loaded entry', () => {
  it('extracts SOP names from sops_skills_loaded entry', () => {
    const result = presentLog(makeLog(), [
      makeSopsSkillsEntry(['DataPipeline', 'ReportGenerator'], []),
    ])
    expect(result.summary.sopsSkills).toContain('DataPipeline')
    expect(result.summary.sopsSkills).toContain('ReportGenerator')
  })

  it('extracts skill names from sops_skills_loaded entry', () => {
    const result = presentLog(makeLog(), [
      makeSopsSkillsEntry([], ['QueryTool', 'ExportTool']),
    ])
    expect(result.summary.sopsSkills).toContain('QueryTool')
    expect(result.summary.sopsSkills).toContain('ExportTool')
  })

  it('deduplicates sopsSkills', () => {
    const result = presentLog(makeLog(), [
      makeSopsSkillsEntry(['ToolA'], ['ToolA']),
    ])
    const count = result.summary.sopsSkills.filter((s) => s === 'ToolA').length
    expect(count).toBe(1)
  })

  it('returns empty sopsSkills when no sops_skills_loaded entry', () => {
    const result = presentLog(makeLog(), [makeSessionStartedEntry()])
    expect(result.summary.sopsSkills).toEqual([])
  })

  it('returns empty sopsSkills array when entries is empty', () => {
    const result = presentLog(makeLog(), [])
    expect(result.summary.sopsSkills).toEqual([])
  })
})

describe('presentLog — plan step counting (from system_instruction)', () => {
  it('counts **Step N** format (injected plan)', () => {
    const result = presentLog(
      makeLog({ system_instruction: SYSTEM_INSTRUCTION_WITH_PLAN }),
      []
    )
    expect(result.summary.planTotal).toBe(4)
  })

  it('counts traditional numbered steps "1. Step"', () => {
    const result = presentLog(
      makeLog({ system_instruction: SYSTEM_INSTRUCTION_NUMBERED }),
      []
    )
    expect(result.summary.planTotal).toBe(4)
  })

  it('returns 0 planTotal when no numbered steps in system_instruction', () => {
    const result = presentLog(makeLog({ system_instruction: 'You are a helpful agent.' }), [])
    expect(result.summary.planTotal).toBe(0)
  })

  it('returns 0 planTotal when system_instruction is null', () => {
    const result = presentLog(makeLog({ system_instruction: null }), [])
    expect(result.summary.planTotal).toBe(0)
  })

  it('counts observe events as planCompleted (iterations run)', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'observe' }),
      makeEntry({ id: 'e2', event_type: 'llm_request' }),
      makeEntry({ id: 'e3', event_type: 'observe' }),
      makeEntry({ id: 'e4', event_type: 'llm_request' }),
    ])
    expect(result.summary.planCompleted).toBe(2)
  })
})

describe('presentLog — entry classification (iconType)', () => {
  it('classifies llm_call as llm iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'llm_call' })])
    expect(result.workingSteps[0].iconType).toBe('llm')
  })

  it('classifies llm_start as llm iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'llm_start' })])
    expect(result.workingSteps[0].iconType).toBe('llm')
  })

  it('classifies llm_end as llm iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'llm_end' })])
    expect(result.workingSteps[0].iconType).toBe('llm')
  })

  it('classifies llm_request as llm iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'llm_request' })])
    expect(result.workingSteps[0].iconType).toBe('llm')
  })

  it('classifies llm_response as llm iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'llm_response' })])
    expect(result.workingSteps[0].iconType).toBe('llm')
  })

  it('classifies tool_call as tool iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'tool_call' })])
    expect(result.workingSteps[0].iconType).toBe('tool')
  })

  it('classifies tool_start as tool iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'tool_start' })])
    expect(result.workingSteps[0].iconType).toBe('tool')
  })

  it('classifies tool_end as tool iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'tool_end' })])
    expect(result.workingSteps[0].iconType).toBe('tool')
  })

  it('classifies error event_type as error iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'error' })])
    expect(result.workingSteps[0].iconType).toBe('error')
  })

  it('classifies ERROR log_level as error iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'info', log_level: 'ERROR' })])
    expect(result.workingSteps[0].iconType).toBe('error')
  })

  it('classifies CRITICAL log_level as error iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'info', log_level: 'CRITICAL' })])
    expect(result.workingSteps[0].iconType).toBe('error')
  })

  it('classifies agent_finish as success iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'agent_finish' })])
    expect(result.workingSteps[0].iconType).toBe('success')
  })

  it('classifies task_complete as success iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'task_complete' })])
    expect(result.workingSteps[0].iconType).toBe('success')
  })

  it('classifies session_complete as success iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'session_complete' })])
    expect(result.workingSteps[0].iconType).toBe('success')
  })

  it('classifies session_completed as success iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'session_completed' })])
    expect(result.workingSteps[0].iconType).toBe('success')
  })

  it('classifies chain_end as success iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'chain_end' })])
    expect(result.workingSteps[0].iconType).toBe('success')
  })

  it('classifies unknown event_type as info iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'context_loaded' })])
    expect(result.workingSteps[0].iconType).toBe('info')
  })

  it('skips llm_request_detail from workingSteps (debug noise)', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'llm_request_detail' }),
      makeEntry({ id: 'e2', event_type: 'llm_response' }),
    ])
    expect(result.workingSteps).toHaveLength(1)
    expect(result.workingSteps[0].iconType).toBe('llm')
  })

  it('skips llm_response_detail from workingSteps (debug noise)', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'llm_response_detail' }),
    ])
    expect(result.workingSteps).toHaveLength(0)
  })
})

describe('presentLog — result status derivation', () => {
  it('returns "unknown" when entries array is empty', () => {
    const result = presentLog(makeLog(), [])
    expect(result.summary.resultStatus).toBe('unknown')
  })

  it('returns "success" when session_completed event is present', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'llm_request' }),
      makeEntry({ id: 'e2', event_type: 'session_completed' }),
    ])
    expect(result.summary.resultStatus).toBe('success')
  })

  it('returns "failure" when error event is present', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'llm_request' }),
      makeEntry({ id: 'e2', event_type: 'error' }),
    ])
    expect(result.summary.resultStatus).toBe('failure')
  })

  it('returns "failure" when any entry has ERROR log_level', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'info', log_level: 'ERROR' }),
    ])
    expect(result.summary.resultStatus).toBe('failure')
  })

  it('returns "failure" when any entry has CRITICAL log_level', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'info', log_level: 'CRITICAL' }),
    ])
    expect(result.summary.resultStatus).toBe('failure')
  })

  it('returns "running" when no terminal event present', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'llm_request' }),
    ])
    expect(result.summary.resultStatus).toBe('running')
  })

  it('prefers success over failure when session_completed comes after an earlier error', () => {
    // In practice this should not happen, but success takes priority if session_completed exists
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'error' }),
      makeEntry({ id: 'e2', event_type: 'session_completed' }),
    ])
    expect(result.summary.resultStatus).toBe('success')
  })
})

describe('presentLog — step detail population', () => {
  it('sets detail to null when entry has no data', () => {
    const result = presentLog(makeLog(), [makeEntry({ data: {} })])
    expect(result.workingSteps[0].detail).toBeNull()
  })

  it('populates detail.content when entry has data', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ data: { tool_name: 'QueryDB', input: 'SELECT *' } }),
    ])
    expect(result.workingSteps[0].detail).not.toBeNull()
    expect(result.workingSteps[0].detail?.content).toContain('QueryDB')
  })

  it('uses tool_name as detail.label when present', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ data: { tool_name: 'ExportTool' } }),
    ])
    expect(result.workingSteps[0].detail?.label).toBe('ExportTool')
  })

  it('uses tool as detail.label when tool_name absent (tool_call event format)', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ event_type: 'tool_call', data: { tool: 'my_mcp_tool', args: {} } }),
    ])
    expect(result.workingSteps[0].detail?.label).toBe('my_mcp_tool')
  })

  it('uses function_name as detail.label when tool_name and tool absent', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ data: { function_name: 'processData' } }),
    ])
    expect(result.workingSteps[0].detail?.label).toBe('processData')
  })

  it('falls back to event_type as detail.label when no tool_name, tool, or function_name', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ event_type: 'tool_call', data: { some_key: 'value' } }),
    ])
    expect(result.workingSteps[0].detail?.label).toBe('tool_call')
  })
})

describe('presentLog — raw log string', () => {
  it('includes system instruction section when present', () => {
    const result = presentLog(makeLog({ system_instruction: 'Role: analyst' }), [])
    expect(result.rawLog).toContain('=== System Instruction ===')
    expect(result.rawLog).toContain('Role: analyst')
  })

  it('includes user prompt section when present', () => {
    const result = presentLog(
      makeLog({ user_prompt: 'Analyse the data' }),
      []
    )
    expect(result.rawLog).toContain('=== User Prompt ===')
    expect(result.rawLog).toContain('Analyse the data')
  })

  it('includes entry timestamp in raw log line', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ timestamp: '2026-01-01T00:01:00Z', message: 'Hello log' }),
    ])
    expect(result.rawLog).toContain('2026-01-01T00:01:00.000Z')
    expect(result.rawLog).toContain('Hello log')
  })

  it('includes entry log_level and event_type in raw log line', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ log_level: 'DEBUG', event_type: 'tool_call', message: 'calling tool' }),
    ])
    expect(result.rawLog).toContain('[DEBUG]')
    expect(result.rawLog).toContain('[tool_call]')
  })

  it('includes serialised data when entry has data', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ data: { key: 'val' } }),
    ])
    expect(result.rawLog).toContain('"key"')
    expect(result.rawLog).toContain('"val"')
  })

  it('includes skipped events (llm_request_detail) in raw log even though excluded from workingSteps', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ event_type: 'llm_request_detail', message: 'full request dump' }),
    ])
    expect(result.rawLog).toContain('full request dump')
    expect(result.workingSteps).toHaveLength(0)
  })

  it('returns empty string when no instruction, prompt, or entries', () => {
    const result = presentLog(makeLog(), [])
    expect(result.rawLog).toBe('')
  })
})

describe('presentLog — startedAt / completedAt', () => {
  it('sets startedAt from first entry timestamp', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', timestamp: '2026-01-01T10:00:00Z' }),
      makeEntry({ id: 'e2', timestamp: '2026-01-01T10:01:00Z' }),
    ])
    expect(result.summary.startedAt).toBe('2026-01-01T10:00:00Z')
  })

  it('sets completedAt from last entry timestamp', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', timestamp: '2026-01-01T10:00:00Z' }),
      makeEntry({ id: 'e2', timestamp: '2026-01-01T10:05:00Z' }),
    ])
    expect(result.summary.completedAt).toBe('2026-01-01T10:05:00Z')
  })

  it('returns null startedAt and completedAt for empty entries', () => {
    const result = presentLog(makeLog(), [])
    expect(result.summary.startedAt).toBeNull()
    expect(result.summary.completedAt).toBeNull()
  })
})

describe('presentLog — hierarchical spans', () => {
  it('produces a Preparation span for session_started and tools_resolved entries', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'session_started', message: 'Started' }),
      makeEntry({ id: 'e2', event_type: 'tools_resolved', message: 'Tools resolved' }),
    ])
    const prepSpan = result.spans.find((s) => s.id === 'span-preparation')
    expect(prepSpan).toBeDefined()
    expect(prepSpan!.children).toHaveLength(2)
  })

  it('produces an Agent Actions span with iteration sub-spans', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'observe', message: 'Observe 1' }),
      makeEntry({ id: 'e2', event_type: 'llm_request', message: 'LLM req 1' }),
      makeEntry({ id: 'e3', event_type: 'llm_response', message: 'LLM resp 1' }),
      makeEntry({ id: 'e4', event_type: 'iteration_complete', message: 'Iter 1 done' }),
    ])
    const actionsSpan = result.spans.find((s) => s.id === 'span-agent-actions')
    expect(actionsSpan).toBeDefined()
    expect(actionsSpan!.children).toHaveLength(1)
    const iter1 = actionsSpan!.children[0]
    expect(isWorkingStepSpan(iter1)).toBe(true)
    if (isWorkingStepSpan(iter1)) {
      expect(iter1.title).toBe('Iteration 1')
      expect(iter1.children).toHaveLength(4)
    }
  })

  it('groups multiple LLM iterations into separate sub-spans', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'observe', message: 'Obs 1' }),
      makeEntry({ id: 'e2', event_type: 'llm_request', message: 'LLM 1' }),
      makeEntry({ id: 'e3', event_type: 'observe', message: 'Obs 2' }),
      makeEntry({ id: 'e4', event_type: 'llm_request', message: 'LLM 2' }),
    ])
    const actionsSpan = result.spans.find((s) => s.id === 'span-agent-actions')
    expect(actionsSpan!.children).toHaveLength(2)
    const iter1 = actionsSpan!.children[0]
    const iter2 = actionsSpan!.children[1]
    expect(isWorkingStepSpan(iter1) && iter1.title).toBe('Iteration 1')
    expect(isWorkingStepSpan(iter2) && iter2.title).toBe('Iteration 2')
  })

  it('produces a Completion span for session_completed entry', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'session_completed', message: 'Done' }),
    ])
    const completionSpan = result.spans.find((s) => s.id === 'span-completion')
    expect(completionSpan).toBeDefined()
    expect(completionSpan!.iconType).toBe('success')
  })

  it('marks Completion span as error iconType when error step is present', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'error', log_level: 'ERROR', message: 'Failed' }),
    ])
    const completionSpan = result.spans.find((s) => s.id === 'span-completion')
    expect(completionSpan!.iconType).toBe('error')
  })

  it('Preparation span starts expanded (collapsed=false)', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'session_started', message: 'Started' }),
    ])
    const prepSpan = result.spans.find((s) => s.id === 'span-preparation')
    expect(prepSpan!.collapsed).toBe(false)
  })

  it('Agent Actions span starts collapsed (collapsed=true)', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'observe', message: 'Obs' }),
    ])
    const actionsSpan = result.spans.find((s) => s.id === 'span-agent-actions')
    expect(actionsSpan!.collapsed).toBe(true)
  })

  it('skips llm_request_detail from spans (debug noise)', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'observe', message: 'Obs' }),
      makeEntry({ id: 'e2', event_type: 'llm_request_detail', message: 'Debug dump' }),
      makeEntry({ id: 'e3', event_type: 'llm_response', message: 'Response' }),
    ])
    const actionsSpan = result.spans.find((s) => s.id === 'span-agent-actions')
    const iter1 = actionsSpan!.children[0]
    if (isWorkingStepSpan(iter1)) {
      // Should have observe + llm_response only (llm_request_detail skipped)
      expect(iter1.children).toHaveLength(2)
    }
  })
})

describe('isWorkingStepSpan type guard', () => {
  it('returns true for a WorkingStepSpan', () => {
    const span = {
      id: 'span-1',
      title: 'Test',
      iconType: 'info' as const,
      children: [],
      collapsed: false,
    }
    expect(isWorkingStepSpan(span)).toBe(true)
  })

  it('returns false for a WorkingStep', () => {
    const step = {
      id: 'step-1',
      iconType: 'info' as const,
      message: 'msg',
      timestamp: '2026-01-01T00:00:00Z',
      detail: null,
    }
    expect(isWorkingStepSpan(step)).toBe(false)
  })
})

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('presentLog — summary extraction', () => {
  it('extracts identity from session_started entry', () => {
    const entries = [makeSessionStartedEntry({ identity_name: 'agent@example.com' })]
    const result = presentLog(makeLog(), entries)
    expect(result.summary.identity).toBe('agent@example.com')
  })

  it('extracts role from session_started entry', () => {
    const entries = [makeSessionStartedEntry({ role_name: 'DataAnalyst' })]
    const result = presentLog(makeLog(), entries)
    expect(result.summary.role).toBe('DataAnalyst')
  })

  it('extracts model from session_started entry', () => {
    const entries = [makeSessionStartedEntry({ model_id: 'gpt-4o' })]
    const result = presentLog(makeLog(), entries)
    expect(result.summary.model).toBe('gpt-4o')
  })

  it('extracts SOPs and skills from sops_skills_loaded entry', () => {
    const entries = [
      makeSopsSkillsEntry(['DataPipeline', 'ReportGenerator'], ['QueryTool', 'ExportTool'])
    ]
    const result = presentLog(makeLog(), entries)
    expect(result.summary.sopsSkills).toContain('DataPipeline')
    expect(result.summary.sopsSkills).toContain('ReportGenerator')
    expect(result.summary.sopsSkills).toContain('QueryTool')
    expect(result.summary.sopsSkills).toContain('ExportTool')
  })

  it('deduplicates sopsSkills', () => {
    const entries = [makeSopsSkillsEntry(['Tool'], ['Tool'])]
    const result = presentLog(makeLog(), entries)
    const count = result.summary.sopsSkills.filter((s) => s === 'Tool').length
    expect(count).toBe(1)
  })

  it('returns null for identity when no session_started entry', () => {
    const result = presentLog(makeLog(), [])
    expect(result.summary.identity).toBeNull()
  })

  it('returns null for role when system_instruction is null', () => {
    const result = presentLog(makeLog({ system_instruction: null }), [])
    expect(result.summary.role).toBeNull()
  })

  it('returns null for model when system_instruction is null', () => {
    const result = presentLog(makeLog({ system_instruction: null }), [])
    expect(result.summary.model).toBeNull()
  })

  it('returns empty sopsSkills array when system_instruction is null', () => {
    const result = presentLog(makeLog({ system_instruction: null }), [])
    expect(result.summary.sopsSkills).toEqual([])
  })

  it('returns empty sopsSkills when instruction has no SOP/skill fields', () => {
    const result = presentLog(makeLog({ system_instruction: 'Identity: bot\nRole: helper' }), [])
    expect(result.summary.sopsSkills).toEqual([])
  })
})

describe('presentLog — plan step counting', () => {
  it('counts numbered plan steps from system_instruction', () => {
    const result = presentLog(makeLog({ system_instruction: SYSTEM_INSTRUCTION_WITH_PLAN }), [])
    expect(result.summary.planTotal).toBeGreaterThan(0)
  })

  it('returns 0 planTotal when no numbered steps', () => {
    const result = presentLog(makeLog({ system_instruction: 'No plan here' }), [])
    expect(result.summary.planTotal).toBe(0)
  })
})

describe('presentLog — entry classification (iconType)', () => {
  it('classifies llm_call as llm iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'llm_call' })])
    expect(result.workingSteps[0].iconType).toBe('llm')
  })

  it('classifies llm_start as llm iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'llm_start' })])
    expect(result.workingSteps[0].iconType).toBe('llm')
  })

  it('classifies llm_end as llm iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'llm_end' })])
    expect(result.workingSteps[0].iconType).toBe('llm')
  })

  it('classifies tool_call as tool iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'tool_call' })])
    expect(result.workingSteps[0].iconType).toBe('tool')
  })

  it('classifies tool_start as tool iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'tool_start' })])
    expect(result.workingSteps[0].iconType).toBe('tool')
  })

  it('classifies tool_end as tool iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'tool_end' })])
    expect(result.workingSteps[0].iconType).toBe('tool')
  })

  it('classifies error event_type as error iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'error' })])
    expect(result.workingSteps[0].iconType).toBe('error')
  })

  it('classifies ERROR log_level as error iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'info', log_level: 'ERROR' })])
    expect(result.workingSteps[0].iconType).toBe('error')
  })

  it('classifies CRITICAL log_level as error iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'info', log_level: 'CRITICAL' })])
    expect(result.workingSteps[0].iconType).toBe('error')
  })

  it('classifies agent_finish as success iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'agent_finish' })])
    expect(result.workingSteps[0].iconType).toBe('success')
  })

  it('classifies task_complete as success iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'task_complete' })])
    expect(result.workingSteps[0].iconType).toBe('success')
  })

  it('classifies session_complete as success iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'session_complete' })])
    expect(result.workingSteps[0].iconType).toBe('success')
  })

  it('classifies chain_end as success iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'chain_end' })])
    expect(result.workingSteps[0].iconType).toBe('success')
  })

  it('classifies unknown event_type as info iconType', () => {
    const result = presentLog(makeLog(), [makeEntry({ event_type: 'context_loaded' })])
    expect(result.workingSteps[0].iconType).toBe('info')
  })
})

describe('presentLog — result status derivation', () => {
  it('returns "unknown" when entries array is empty', () => {
    const result = presentLog(makeLog(), [])
    expect(result.summary.resultStatus).toBe('unknown')
  })

  it('returns "failure" when last entry has error iconType', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'llm_call' }),
      makeEntry({ id: 'e2', event_type: 'error' }),
    ])
    expect(result.summary.resultStatus).toBe('failure')
  })

  it('returns "success" when last entry has success iconType', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'llm_call' }),
      makeEntry({ id: 'e2', event_type: 'session_completed' }),
    ])
    expect(result.summary.resultStatus).toBe('success')
  })

  it('returns "running" when last entry is not terminal', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'llm_call' }),
    ])
    expect(result.summary.resultStatus).toBe('running')
  })

  it('returns "failure" when last entry has CRITICAL log_level', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', event_type: 'info', log_level: 'CRITICAL' }),
    ])
    expect(result.summary.resultStatus).toBe('failure')
  })
})

describe('presentLog — step detail population', () => {
  it('sets detail to null when entry has no data', () => {
    const result = presentLog(makeLog(), [makeEntry({ data: {} })])
    expect(result.workingSteps[0].detail).toBeNull()
  })

  it('populates detail.content when entry has data', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ data: { tool_name: 'QueryDB', input: 'SELECT *' } }),
    ])
    expect(result.workingSteps[0].detail).not.toBeNull()
    expect(result.workingSteps[0].detail?.content).toContain('QueryDB')
  })

  it('uses tool_name as detail.label when present', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ data: { tool_name: 'ExportTool' } }),
    ])
    expect(result.workingSteps[0].detail?.label).toBe('ExportTool')
  })

  it('uses function_name as detail.label when tool_name absent', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ data: { function_name: 'processData' } }),
    ])
    expect(result.workingSteps[0].detail?.label).toBe('processData')
  })

  it('falls back to event_type as detail.label when no tool_name or function_name', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ event_type: 'tool_call', data: { some_key: 'value' } }),
    ])
    expect(result.workingSteps[0].detail?.label).toBe('tool_call')
  })
})

describe('presentLog — raw log string', () => {
  it('includes system instruction section when present', () => {
    const result = presentLog(makeLog({ system_instruction: 'Role: analyst' }), [])
    expect(result.rawLog).toContain('=== System Instruction ===')
    expect(result.rawLog).toContain('Role: analyst')
  })

  it('includes user prompt section when present', () => {
    const result = presentLog(
      makeLog({ user_prompt: 'Analyse the data' }),
      []
    )
    expect(result.rawLog).toContain('=== User Prompt ===')
    expect(result.rawLog).toContain('Analyse the data')
  })

  it('includes entry timestamp in raw log line', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ timestamp: '2026-01-01T00:01:00Z', message: 'Hello log' }),
    ])
    expect(result.rawLog).toContain('2026-01-01T00:01:00.000Z')
    expect(result.rawLog).toContain('Hello log')
  })

  it('includes entry log_level and event_type in raw log line', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ log_level: 'DEBUG', event_type: 'tool_call', message: 'calling tool' }),
    ])
    expect(result.rawLog).toContain('[DEBUG]')
    expect(result.rawLog).toContain('[tool_call]')
  })

  it('includes serialised data when entry has data', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ data: { key: 'val' } }),
    ])
    expect(result.rawLog).toContain('"key"')
    expect(result.rawLog).toContain('"val"')
  })

  it('returns empty string when no instruction, prompt, or entries', () => {
    const result = presentLog(makeLog(), [])
    expect(result.rawLog).toBe('')
  })
})

describe('presentLog — startedAt / completedAt', () => {
  it('sets startedAt from first entry timestamp', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', timestamp: '2026-01-01T10:00:00Z' }),
      makeEntry({ id: 'e2', timestamp: '2026-01-01T10:01:00Z' }),
    ])
    expect(result.summary.startedAt).toBe('2026-01-01T10:00:00Z')
  })

  it('sets completedAt from last entry timestamp', () => {
    const result = presentLog(makeLog(), [
      makeEntry({ id: 'e1', timestamp: '2026-01-01T10:00:00Z' }),
      makeEntry({ id: 'e2', timestamp: '2026-01-01T10:05:00Z' }),
    ])
    expect(result.summary.completedAt).toBe('2026-01-01T10:05:00Z')
  })

  it('returns null startedAt and completedAt for empty entries', () => {
    const result = presentLog(makeLog(), [])
    expect(result.summary.startedAt).toBeNull()
    expect(result.summary.completedAt).toBeNull()
  })
})
