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
  AgentInputType,
  ExecutionLogEntry,
  ExecutionLogRead,
  GuardrailUsage,
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
  'binding_content_loaded',
  'plan_injected',
  'prompt_captured',
  'agent_initialized',
])

// ── Preparation group sets (for 4-step collapsing) ─────────────────────────
const PREP_GROUP_SESSION = new Set(['session_started'])
const PREP_GROUP_CHECK = new Set(['tools_resolved', 'sops_skills_loaded', 'sop_loaded'])
const PREP_GROUP_INIT = new Set(['mcp_context_loaded', 'binding_content_loaded', 'plan_injected', 'prompt_captured'])
const PREP_GROUP_READY = new Set(['agent_initialized'])

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
  'delegation_started',
  'delegation_waiting',
  'delegation_resumed',
  'delegation_depth_blocked',
  'delegation_timeout',
  'delegation_failed',
  'delegation_merged',
])

function iconTypeFromEntry(entry: ExecutionLogEntry): WorkingStepIconType {
  const et = entry.event_type.toLowerCase()
  const ll = entry.log_level.toUpperCase()
  if (et === 'llm_call' || et === 'llm_start' || et === 'llm_end' || et === 'llm_request' || et === 'llm_response') return 'llm'
  if (et === 'tool_call' || et === 'tool_start' || et === 'tool_end') return 'tool'
  if (et === 'error' || ll === 'ERROR' || ll === 'CRITICAL') return 'error'
  if (et === 'delegation_started') return 'delegating'
  if (et === 'delegation_waiting') return 'waiting'
  if (et === 'delegation_merged') {
    const finalEt = entry.data?.['delegation_final_event_type'] as string | undefined
    if (finalEt === 'delegation_resumed') return 'success'
    if (finalEt === 'delegation_timeout' || finalEt === 'delegation_failed' || finalEt === 'delegation_depth_blocked') return 'error'
    return 'info'
  }
  if (
    et === 'agent_finish' ||
    et === 'task_complete' ||
    et === 'session_complete' ||
    et === 'session_completed' ||
    et === 'chain_end' ||
    et === 'save_result' ||
    et === 'task_loop_completed' ||
    et === 'delegation_resumed'
  )
    return 'success'
  if (
    et === 'delegation_depth_blocked' ||
    et === 'delegation_timeout' ||
    et === 'delegation_failed'
  )
    return 'error'
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
          (entry.data['sub_agent'] as string | undefined) ??
          (entry.data['agent_type'] as string | undefined) ??
          (entry.data['delegation_target'] as string | undefined) ??
          entry.event_type,
        content: JSON.stringify(entry.data, null, 2),
        eventType: entry.event_type,
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

function toNullableString(value: unknown): string | null {
  return typeof value === 'string' && value.trim().length > 0 ? value : null
}

function toNullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function toRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }

  return value as Record<string, unknown>
}

function extractGuardrailPayload(entry: ExecutionLogEntry | undefined): Record<string, unknown> | null {
  if (!entry) {
    return null
  }

  const directGuardrail = toRecord(entry.data?.['guardrail'])
  if (directGuardrail) {
    return directGuardrail
  }

  if (
    entry.event_type === 'guardrail.runtime.snapshot' ||
    entry.event_type.startsWith('guardrail.runtime.snapshot.') ||
    entry.event_type === 'guardrail.runtime.conversational_token_usage_snapshot' ||
    'token_usage_current_session' in entry.data
  ) {
    return entry.data
  }

  return null
}

function extractGuardrailCurrentPayload(entry: ExecutionLogEntry | undefined): Record<string, unknown> | null {
  if (!entry) {
    return null
  }

  const directPayload = extractGuardrailPayload(entry)
  if (entry.event_type === 'task_loop_completed' && directPayload) {
    return directPayload
  }

  const currentValue = toRecord(entry.data?.['current_value'])
  if (currentValue) {
    return currentValue
  }

  return directPayload
}

function extractGuardrailThresholdPayload(entry: ExecutionLogEntry | undefined): Record<string, unknown> | null {
  if (!entry) {
    return null
  }

  return toRecord(entry.data?.['threshold_value'])
}

function extractGuardrailUsage(entries: ExecutionLogEntry[]): GuardrailUsage | null {
  const latestCompletionEntry = [...entries]
    .reverse()
    .find((entry) => entry.event_type === 'task_loop_completed' && extractGuardrailPayload(entry) != null)
  const latestSnapshotEntry = [...entries]
    .reverse()
    .find(
      (entry) =>
        entry.event_type === 'guardrail.runtime.snapshot' ||
        entry.event_type.startsWith('guardrail.runtime.snapshot.') ||
        entry.event_type === 'guardrail.runtime.conversational_token_usage_snapshot',
    )

  const currentPayload =
    extractGuardrailCurrentPayload(latestCompletionEntry) ?? extractGuardrailCurrentPayload(latestSnapshotEntry)
  const thresholdPayload = extractGuardrailThresholdPayload(latestSnapshotEntry)
  const payload =
    extractGuardrailPayload(latestCompletionEntry) ??
    extractGuardrailPayload(latestSnapshotEntry) ??
    currentPayload ??
    thresholdPayload

  if (!payload) {
    return null
  }

  const currentIterations = toNullableNumber(currentPayload?.['cumulative_iterations'])
  const maxIterations = toNullableNumber(thresholdPayload?.['max_iterations'])
  const currentDelegatedSteps = toNullableNumber(currentPayload?.['delegated_steps'])
  const maxDelegatedSteps = toNullableNumber(thresholdPayload?.['max_delegated_steps'])
  const currentDelegationDepth = toNullableNumber(currentPayload?.['delegation_depth'])
  const maxDelegationDepth = toNullableNumber(thresholdPayload?.['max_delegation_depth'])
  const tokenUsageCurrentSession = toNullableNumber(currentPayload?.['token_usage_current_session'])
  const tokenBudget = toNullableNumber(thresholdPayload?.['token_budget'])

  return {
    policySnapshotId: toNullableString(payload['policy_snapshot_id']),
    cumulativeIterations: currentIterations ?? toNullableNumber(payload['cumulative_iterations']),
    maxIterations,
    delegatedSteps: currentDelegatedSteps ?? toNullableNumber(payload['delegated_steps']),
    maxDelegatedSteps,
    delegationDepth: currentDelegationDepth ?? toNullableNumber(payload['delegation_depth']),
    maxDelegationDepth,
    elapsedSeconds: toNullableNumber(payload['elapsed_seconds']),
    tokenUsageCurrentSession: tokenUsageCurrentSession ?? toNullableNumber(payload['token_usage_current_session']),
    tokenBudget: tokenBudget ?? toNullableNumber(payload['token_budget']),
    executionTimeoutSeconds: toNullableNumber(thresholdPayload?.['execution_timeout_seconds']),
  }
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
  const inputTypeData = sessionStartedEntry?.data?.['input_type']
  const identity = typeof identityData === 'string' ? identityData : null
  const role = typeof roleData === 'string' ? roleData : null
  const inputType =
    inputTypeData === 'none' || inputTypeData === 'typed' || inputTypeData === 'conversation'
      ? (inputTypeData as AgentInputType)
      : null

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
    } else if (sessionStatus === 'terminated') {
      // Phase 3.12: operator-initiated terminations are
      // distinct from "failed" — they show a neutral "Terminated"
      // badge instead of a red "Failed" badge.
      resultStatus = 'terminated'
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
    inputType,
    sopsSkills,
    planCompleted,
    planTotal,
    resultStatus,
    startedAt,
    completedAt,
    durationMs,
    guardrailUsage: extractGuardrailUsage(entries),
  }
}

// ── Span building ──────────────────────────────────────────────────────────────
/**
 * Collapse a group of preparation events into a single synthetic summary step.
 */
function makePrepSummaryStep(
  id: string,
  label: string,
  events: ExecutionLogEntry[]
): WorkingStep {
  const first = events[0]
  const aggregated: Record<string, unknown> = { _event_types: events.map((e) => e.event_type) }
  for (const e of events) {
    Object.assign(aggregated, e.data)
  }
  return {
    id,
    iconType: 'info',
    message: label,
    timestamp: first.timestamp,
    detail: {
      label,
      content: JSON.stringify(aggregated, null, 2),
      eventType: events.map((e) => e.event_type).join(', '),
    },
  }
}

/**
 * Collapse raw preparation events into 4 logical summary steps:
 *   1. Preparation (session_started)
 *   2. Pre-checking (tools, SOPs, skills)
 *   3. Initializing (MCP context, bindings, plan, prompt)
 *   4. Initialized (agent_initialized)
 */
function buildPreparationSteps(prepEvents: ExecutionLogEntry[]): WorkingStep[] {
  if (prepEvents.length === 0) return []

  const g1 = prepEvents.filter((e) => PREP_GROUP_SESSION.has(e.event_type.toLowerCase()))
  const g2 = prepEvents.filter((e) => PREP_GROUP_CHECK.has(e.event_type.toLowerCase()))
  const g3 = prepEvents.filter((e) => PREP_GROUP_INIT.has(e.event_type.toLowerCase()))
  const g4 = prepEvents.filter((e) => PREP_GROUP_READY.has(e.event_type.toLowerCase()))

  // Catch-all: any prep events not in the four groups (edge cases / future event types)
  const knownGroups = new Set([...PREP_GROUP_SESSION, ...PREP_GROUP_CHECK, ...PREP_GROUP_INIT, ...PREP_GROUP_READY])
  const ungrouped = prepEvents.filter((e) => !knownGroups.has(e.event_type.toLowerCase()))

  const steps: WorkingStep[] = []
  if (g1.length > 0) steps.push(makePrepSummaryStep('prep-g1', 'Preparing agent data', g1))
  if (g2.length > 0) steps.push(makePrepSummaryStep('prep-g2', 'Loading tools and skills', g2))
  if (g3.length > 0) steps.push(makePrepSummaryStep('prep-g3', 'Setting up context', g3))
  if (g4.length > 0) steps.push(makePrepSummaryStep('prep-g4', 'Agent ready', g4))
  // Preserve ungrouped prep events as individual steps (backward compat)
  for (const e of ungrouped) steps.push(entryToWorkingStep(e))
  return steps
}
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
  const mergedEntries = mergeDelegationEntries(entries)

  const prepEvents: ExecutionLogEntry[] = []
  const iterationSpans: WorkingStepSpan[] = []
  const completionSteps: WorkingStep[] = []

  let currentIterSteps: WorkingStep[] | null = null
  let currentIterNumber: number | null = null

  for (const entry of mergedEntries) {
    const et = entry.event_type.toLowerCase()
    if (SKIP_EVENT_TYPES.has(et)) continue

    const step = entryToWorkingStep(entry)

    if (PREPARATION_EVENT_TYPES.has(et)) {
      prepEvents.push(entry)
    } else if (COMPLETION_EVENT_TYPES.has(et)) {
      // Close any open iteration before adding completion steps
      if (currentIterSteps && currentIterSteps.length > 0 && currentIterNumber !== null) {
        iterationSpans.push(makeIterationSpan(currentIterNumber, currentIterSteps))
        currentIterSteps = null
        currentIterNumber = null
      }
      completionSteps.push(step)
    } else if (et === 'llm_request') {
      // LangChain AR path: each llm_request with a new data.iteration starts a new iteration
      const iterNum = extractIterationNumber(entry)
      const isNewIter = currentIterSteps === null || (iterNum !== null && iterNum !== currentIterNumber)
      if (isNewIter) {
        if (currentIterSteps && currentIterSteps.length > 0 && currentIterNumber !== null) {
          iterationSpans.push(makeIterationSpan(currentIterNumber, currentIterSteps))
        }
        currentIterNumber = iterNum ?? (currentIterNumber !== null ? currentIterNumber + 1 : 1)
        currentIterSteps = [step]
      } else {
        currentIterSteps!.push(step)
      }
    } else if (et === 'observe') {
      // Legacy CC-path observe event — marks the start of a new iteration
      if (currentIterSteps && currentIterSteps.length > 0 && currentIterNumber !== null) {
        iterationSpans.push(makeIterationSpan(currentIterNumber, currentIterSteps))
      }
      const iterNum = extractIterationNumber(entry)
      currentIterNumber = iterNum !== null ? iterNum : (currentIterNumber !== null ? currentIterNumber + 1 : 1)
      currentIterSteps = [step]
    } else if (et === 'iteration_complete') {
      // iteration_complete closes the current iteration
      if (currentIterSteps !== null) {
        currentIterSteps.push(step)
        if (currentIterNumber !== null) {
          iterationSpans.push(makeIterationSpan(currentIterNumber, currentIterSteps))
        }
        currentIterSteps = null
        currentIterNumber = null
      } else {
        completionSteps.push(step)
      }
    } else if (ITERATION_EVENT_TYPES.has(et)) {
      // llm_response, tool_call, delegation_* etc.
      if (currentIterSteps !== null) {
        currentIterSteps.push(step)
      } else {
        // No iteration open yet — start one implicitly
        currentIterNumber = currentIterNumber !== null ? currentIterNumber + 1 : 1
        currentIterSteps = [step]
      }
    } else {
      // Unknown event type — add to current iteration or defer to ungrouped prep
      if (currentIterSteps !== null) {
        currentIterSteps.push(step)
      } else {
        prepEvents.push(entry)
      }
    }
  }

  // Close last open iteration if any
  if (currentIterSteps && currentIterSteps.length > 0 && currentIterNumber !== null) {
    iterationSpans.push(makeIterationSpan(currentIterNumber, currentIterSteps))
  }

  const prepSteps = buildPreparationSteps(prepEvents)
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
      collapsed: false,
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

// ── Delegation event merging ────────────────────────────────────────────────────

/** Delegation event types that are part of a single delegation lifecycle. */
const DELEGATION_LIFECYCLE_TYPES = new Set([
  'delegation_started',
  'delegation_waiting',
  'human_intervene',
  'delegation_resumed',
  'delegation_timeout',
  'delegation_failed',
  'delegation_depth_blocked',
])

/**
 * Merge delegation lifecycle events for the same target into a single
 * `delegation_merged` entry so the UI renders one consolidated block.
 *
 * Unlike the previous consecutive-only approach, this scans the full list and
 * groups events by target slug, so parallel delegations (agent fires two agent
 * tools simultaneously) are handled correctly: each target's events are merged
 * regardless of position interleaving with other targets' events.
 */
function mergeDelegationEntries(entries: ExecutionLogEntry[]): ExecutionLogEntry[] {
  // 1. Group all delegation lifecycle events by target slug (preserving order)
  const byTarget = new Map<string, ExecutionLogEntry[]>()
  for (const e of entries) {
    if (!DELEGATION_LIFECYCLE_TYPES.has(e.event_type) && e.event_type !== 'delegation_started') continue
    const target: string | undefined =
      e.event_type === 'human_intervene'
        ? (e.data?.['agent_type'] as string | undefined)
        : (e.data?.['delegation_target'] as string | undefined)
    if (!target) continue
    if (!byTarget.has(target)) byTarget.set(target, [])
    byTarget.get(target)!.push(e)
  }

  // 2. For targets with 2+ events, build a merged replacement for the
  //    delegation_started entry and mark subsequent lifecycle entries for removal.
  const replacements = new Map<string, ExecutionLogEntry>()
  const toRemove = new Set<string>()

  for (const [, group] of byTarget) {
    if (group.length < 2) continue
    const startEvent = group.find((e) => e.event_type === 'delegation_started')
    if (!startEvent) continue

    const lastEvent = group[group.length - 1]
    const receiverSessionId =
      (lastEvent.data?.['receiver_session_id'] as string | undefined) ??
      (group
        .find((e) => e.event_type === 'delegation_waiting')
        ?.data?.['receiver_session_id'] as string | undefined)

    const merged: ExecutionLogEntry = {
      id: startEvent.id,
      timestamp: startEvent.timestamp,
      log_level: startEvent.log_level,
      event_type: 'delegation_merged',
      message: startEvent.message,
      data: {
        ...startEvent.data,
        ...(receiverSessionId ? { receiver_session_id: receiverSessionId } : {}),
        delegation_events: group.map((e) => ({
          event_type: e.event_type,
          message: e.message,
          timestamp: e.timestamp,
        })),
        delegation_final_event_type: lastEvent.event_type,
        delegation_final_message: lastEvent.message,
      },
    }

    replacements.set(startEvent.id, merged)
    for (const e of group) {
      if (e.id !== startEvent.id) toRemove.add(e.id)
    }
  }

  // 3. Build result — replace start entries, skip removed entries.
  const result: ExecutionLogEntry[] = []
  for (const entry of entries) {
    if (toRemove.has(entry.id)) continue
    result.push(replacements.get(entry.id) ?? entry)
  }
  return result
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
