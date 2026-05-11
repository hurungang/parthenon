/**
 * LogPresenter — pure transformation layer.
 *
 * Converts a raw ExecutionLogRead + ExecutionLogEntry[] into a StructuredLog
 * containing a LogSummary, ordered WorkingStepSpan array (hierarchical), a
 * flat WorkingStep array (for backward-compat / raw access), and a raw log
 * string.  No side effects, no network calls.
 */
import type {
  AgentJobStatus,
  ExecutionLogEntry,
  ExecutionLogRead,
  LogSummary,
  StructuredLog,
  WorkingStep,
  WorkingStepSpan,
  WorkingStepIconType,
} from '../types'

// ── Type guards ────────────────────────────────────────────────────────────────

export function isWorkingStepSpan(
  child: WorkingStep | WorkingStepSpan
): child is WorkingStepSpan {
  return 'children' in child && Array.isArray((child as WorkingStepSpan).children)
}

// ── Entry-level helpers ────────────────────────────────────────────────────────

/** Event types that are too verbose to show as individual steps (debug noise). */
const SKIP_EVENT_TYPES = new Set([
  'llm_request_detail',
  'llm_response_detail',
])

/** Event types that belong to the Preparation span. */
const PREPARATION_EVENT_TYPES = new Set([
  'session_started',
  'tools_resolved',
  'sops_skills_loaded',
  'sop_loaded',
  'mcp_context_loaded',
  'plan_injected',
  'prompt_captured',
])

/** Event types that belong to the Completion span. */
const COMPLETION_EVENT_TYPES = new Set([
  'task_loop_completed',
  'session_completed',
  'save_result',
  'error',
  'system',
])

/** Event types that occur within an iteration (after observe). */
const ITERATION_EVENT_TYPES = new Set([
  'observe',
  'llm_request',
  'llm_response',
  'tool_call',
])

function iconTypeFromEntry(entry: ExecutionLogEntry): WorkingStepIconType {
  const et = entry.event_type.toLowerCase()
  const ll = entry.log_level.toUpperCase()
  if (et === 'llm_call' || et === 'llm_start' || et === 'llm_end' || et === 'llm_request' || et === 'llm_response') return 'llm'
  if (et === 'tool_call' || et === 'tool_start' || et === 'tool_end') return 'tool'
  if (et === 'error' || ll === 'ERROR' || ll === 'CRITICAL') return 'error'
  if (
    et === 'agent_finish' ||
    et === 'task_complete' ||
    et === 'session_complete' ||
    et === 'session_completed' ||
    et === 'chain_end' ||
    et === 'save_result' ||
    et === 'task_loop_completed'
  )
    return 'success'
  return 'info'
}

function entryToWorkingStep(entry: ExecutionLogEntry): WorkingStep {
  const iconType = iconTypeFromEntry(entry)
  const hasData = Object.keys(entry.data).length > 0
  const detail = hasData
    ? {
        label:
          (entry.data['tool_name'] as string | undefined) ??
          (entry.data['tool'] as string | undefined) ??
          (entry.data['function_name'] as string | undefined) ??
          entry.event_type,
        content: JSON.stringify(entry.data, null, 2),
      }
    : null

  return {
    id: entry.id,
    iconType,
    message: entry.message,
    timestamp: entry.timestamp,
    detail,
  }
}

function formatRawLine(entry: ExecutionLogEntry): string {
  const ts = new Date(entry.timestamp).toISOString()
  const dataStr =
    Object.keys(entry.data).length > 0 ? ' | ' + JSON.stringify(entry.data) : ''
  return `[${ts}] [${entry.log_level}] [${entry.event_type}] ${entry.message}${dataStr}`
}

// ── Summary extraction ─────────────────────────────────────────────────────────

/**
 * Count numbered plan steps from system_instruction text.
 * Matches both traditional "1. Step" / "1) Step" and injected "**Step 1**" formats.
 */
function countPlanSteps(text: string): number {
  const traditional = text.match(/^\s*(?:step\s+)?\d+[.)]\s+\S/gim)?.length ?? 0
  const injected = text.match(/^\s*\*\*Step\s+\d+\*\*/gim)?.length ?? 0
  return Math.max(traditional, injected)
}

function buildSummary(
  executionLog: ExecutionLogRead,
  entries: ExecutionLogEntry[],
  sessionStatus?: AgentJobStatus
): LogSummary {
  const sysInstr = executionLog.system_instruction ?? ''

  // Extract structured fields from execution log entries (not system_instruction text parsing)
  const sessionStartedEntry = entries.find((e) => e.event_type === 'session_started')
  const llmRequestEntry = entries.find((e) => e.event_type === 'llm_request')
  const sopsSkillsEntry = entries.find((e) => e.event_type === 'sops_skills_loaded')

  // Model: prefer session_started.data.model_id, fall back to first llm_request.data.model_id
  const modelFromSession = sessionStartedEntry?.data?.['model_id']
  const modelFromLLM = llmRequestEntry?.data?.['model_id']
  const model =
    (typeof modelFromSession === 'string' ? modelFromSession : null) ??
    (typeof modelFromLLM === 'string' ? modelFromLLM : null)

  // Identity & role: added to session_started event by the runtime executor
  const identityData = sessionStartedEntry?.data?.['identity_name']
  const roleData = sessionStartedEntry?.data?.['role_name']
  const identity = typeof identityData === 'string' ? identityData : null
  const role = typeof roleData === 'string' ? roleData : null

  // SOPs and Skills: from the sops_skills_loaded event (has names, not just IDs)
  let sopsSkills: string[] = []
  if (sopsSkillsEntry && sopsSkillsEntry.data) {
    const sopsData = sopsSkillsEntry.data['sops']
    const skillsData = sopsSkillsEntry.data['skills']
    
    const sops = Array.isArray(sopsData) ? sopsData : []
    const skills = Array.isArray(skillsData) ? skillsData : []
    
    sopsSkills = [
      ...sops.map((s: any) => s?.name).filter((name): name is string => typeof name === 'string'),
      ...skills.map((s: any) => s?.name).filter((name): name is string => typeof name === 'string'),
    ].filter((v, i, arr) => arr.indexOf(v) === i) // deduplicate
  }

  // Plan progress: planCompleted = observe events run, planTotal from system_instruction plan steps
  const planCompleted = entries.filter((e) => e.event_type === 'observe').length
  const planTotal = countPlanSteps(sysInstr)

  // Result status: prefer actual session status if provided, otherwise infer from log entries
  let resultStatus: LogSummary['resultStatus']
  if (sessionStatus) {
    // Map AgentJobStatus to LogSummary resultStatus
    if (sessionStatus === 'completed') {
      resultStatus = 'success'
    } else if (sessionStatus === 'failed') {
      resultStatus = 'failure'
    } else if (sessionStatus === 'running') {
      resultStatus = 'running'
    } else {
      resultStatus = 'unknown' // queued or other
    }
  } else {
    // Fallback: infer from log entries
    const hasSessionCompleted = entries.some((e) => e.event_type === 'session_completed')
    const hasError = entries.some(
      (e) =>
        e.event_type === 'error' ||
        e.log_level.toUpperCase() === 'ERROR' ||
        e.log_level.toUpperCase() === 'CRITICAL'
    )
    if (entries.length === 0) {
      resultStatus = 'unknown'
    } else if (hasSessionCompleted) {
      resultStatus = 'success'
    } else if (hasError) {
      resultStatus = 'failure'
    } else {
      resultStatus = 'running'
    }
  }

  const startedAt = entries.length > 0 ? entries[0].timestamp : null
  const completedAt = entries.length > 0 ? entries[entries.length - 1].timestamp : null
  
  // Calculate duration in milliseconds
  let durationMs: number | null = null
  if (startedAt && completedAt) {
    try {
      const start = new Date(startedAt).getTime()
      const end = new Date(completedAt).getTime()
      durationMs = end - start
    } catch {
      durationMs = null
    }
  }

  return {
    identity,
    role,
    model,
    sopsSkills,
    planCompleted,
    planTotal,
    resultStatus,
    startedAt,
    completedAt,
    durationMs,
  }
}

// ── Span building ──────────────────────────────────────────────────────────────

function makeIterationSpan(number: number, steps: WorkingStep[]): WorkingStepSpan {
  return {
    id: `iteration-${number}`,
    title: `Iteration ${number}`,
    iconType: 'llm',
    children: steps,
    collapsed: false,
  }
}

/**
 * Extract iteration number from event data or message.
 * Returns null if no iteration number found.
 */
function extractIterationNumber(entry: ExecutionLogEntry): number | null {
  // Try data.iteration first
  if (typeof entry.data?.['iteration'] === 'number') {
    return entry.data['iteration']
  }
  
  // Try parsing from message (e.g., "Starting iteration 2")
  const match = entry.message.match(/iteration\s+(\d+)/i)
  if (match) {
    return parseInt(match[1], 10)
  }
  
  return null
}

/**
 * Group entries into a hierarchical span tree:
 *   ▶ Preparation
 *   ▶ Agent Actions
 *       ▶ Iteration 1
 *       ▶ Iteration 2
 *   ▶ Completion
 */
function buildSpans(entries: ExecutionLogEntry[]): WorkingStepSpan[] {
  const prepSteps: WorkingStep[] = []
  const iterationSpans: WorkingStepSpan[] = []
  const completionSteps: WorkingStep[] = []

  let currentIterSteps: WorkingStep[] | null = null
  let currentIterNumber: number | null = null

  for (const entry of entries) {
    const et = entry.event_type.toLowerCase()
    if (SKIP_EVENT_TYPES.has(et)) continue

    const step = entryToWorkingStep(entry)

    if (PREPARATION_EVENT_TYPES.has(et)) {
      prepSteps.push(step)
    } else if (COMPLETION_EVENT_TYPES.has(et)) {
      // Close any open iteration before adding completion steps
      if (currentIterSteps && currentIterSteps.length > 0 && currentIterNumber !== null) {
        iterationSpans.push(makeIterationSpan(currentIterNumber + 1, currentIterSteps))
        currentIterSteps = null
        currentIterNumber = null
      }
      completionSteps.push(step)
    } else if (et === 'observe') {
      // Each observe event marks the start of a new iteration
      // Close previous iteration if any
      if (currentIterSteps && currentIterSteps.length > 0 && currentIterNumber !== null) {
        iterationSpans.push(makeIterationSpan(currentIterNumber + 1, currentIterSteps))
      }
      
      // Start new iteration - extract iteration number from event
      const iterNum = extractIterationNumber(entry)
      currentIterNumber = iterNum !== null ? iterNum : (currentIterNumber !== null ? currentIterNumber + 1 : 0)
      currentIterSteps = [step]
    } else if (et === 'iteration_complete') {
      // iteration_complete closes the current iteration
      if (currentIterSteps !== null) {
        currentIterSteps.push(step)
        // Close this iteration
        if (currentIterNumber !== null) {
          iterationSpans.push(makeIterationSpan(currentIterNumber + 1, currentIterSteps))
        }
        currentIterSteps = null
        currentIterNumber = null
      } else {
        // Edge case: iteration_complete without an open iteration - skip or add to completion
        completionSteps.push(step)
      }
    } else if (ITERATION_EVENT_TYPES.has(et)) {
      // llm_request, llm_response, tool_call
      if (currentIterSteps !== null) {
        currentIterSteps.push(step)
      } else {
        // No iteration started yet (edge case) — put in preparation
        prepSteps.push(step)
      }
    } else {
      // Unknown event type — put in preparation if no iteration started, else current iteration
      if (currentIterSteps !== null) {
        currentIterSteps.push(step)
      } else {
        prepSteps.push(step)
      }
    }
  }

  // Close last open iteration if any
  if (currentIterSteps && currentIterSteps.length > 0 && currentIterNumber !== null) {
    iterationSpans.push(makeIterationSpan(currentIterNumber + 1, currentIterSteps))
  }

  const spans: WorkingStepSpan[] = []

  if (prepSteps.length > 0) {
    spans.push({
      id: 'span-preparation',
      title: 'Preparation',
      iconType: 'info',
      children: prepSteps,
      collapsed: false,
    })
  }

  if (iterationSpans.length > 0) {
    spans.push({
      id: 'span-agent-actions',
      title: 'Agent Actions',
      iconType: 'llm',
      children: iterationSpans,
      collapsed: true,
    })
  }

  if (completionSteps.length > 0) {
    const hasError = completionSteps.some((s) => s.iconType === 'error')
    spans.push({
      id: 'span-completion',
      title: 'Completion',
      iconType: hasError ? 'error' : 'success',
      children: completionSteps,
      collapsed: false,
    })
  }

  return spans
}

// ── Main export ────────────────────────────────────────────────────────────────

export function presentLog(
  executionLog: ExecutionLogRead,
  entries: ExecutionLogEntry[],
  options?: { sessionStatus?: AgentJobStatus }
): StructuredLog {
  const sysInstr = executionLog.system_instruction ?? ''

  const summary = buildSummary(executionLog, entries, options?.sessionStatus)

  // Flat working steps — kept for backward compatibility and test access
  const workingSteps: WorkingStep[] = entries
    .filter((e) => !SKIP_EVENT_TYPES.has(e.event_type.toLowerCase()))
    .map(entryToWorkingStep)

  // Hierarchical spans
  const spans = buildSpans(entries)

  // Raw log string
  const rawParts: string[] = []
  if (sysInstr) rawParts.push(`=== System Instruction ===\n${sysInstr}`)
  if (executionLog.user_prompt) rawParts.push(`=== User Prompt ===\n${executionLog.user_prompt}`)
  if (entries.length > 0) {
    rawParts.push('=== Execution Log ===')
    rawParts.push(...entries.map(formatRawLine))
  }
  const rawLog = rawParts.join('\n\n')

  return {
    summary,
    spans,
    workingSteps,
    rawLog,
  }
}
