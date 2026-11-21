import type { ExecutionLogEntry } from '../types'

/**
 * Event types surfaced in the parent delegation card's DIRECT-CHILD progress peek.
 *
 * This allow-list is unchanged from the original inline filter — the peek shows
 * the delegated child's own initialization, tool, model, observation and
 * completion activity.
 */
export const DIRECT_CHILD_PEEK_EVENT_TYPES: ReadonlySet<string> = new Set([
  'agent_initialized',
  'tool_call',
  'tool_response',
  'llm_request',
  'llm_response',
  'observe',
  'session_completed',
])

/**
 * Delegation lifecycle event types. These always describe a delegation the
 * entry's own session performed, so they must never surface in a parent's
 * direct-child peek (the parent renders the child's delegation as a drill-in).
 */
export const DELEGATION_LIFECYCLE_EVENT_TYPES: ReadonlySet<string> = new Set([
  'delegation_started',
  'delegation_waiting',
  'delegation_resumed',
  'delegation_merged',
  'delegation_depth_blocked',
  'delegation_timeout',
  'delegation_failed',
])

/** Canonical delegation tool name prefix: `agent____<slug>`. */
const CANONICAL_DELEGATION_TOOL_PREFIX = 'agent____'

/** Legacy (sanitized) delegation tool name prefix: `agent__<slug>`. */
const LEGACY_DELEGATION_TOOL_PREFIX = 'agent__'

/** Tool-entry event types whose tool name can be inspected. */
const DELEGATION_CAPABLE_TOOL_EVENT_TYPES: ReadonlySet<string> = new Set([
  'tool_call',
  'tool_response',
])

/** `data` keys that may carry the tool name on a tool entry. */
const TOOL_NAME_DATA_KEYS = ['tool', 'tool_raw', 'tool_name', 'name', 'original_name'] as const

/**
 * True when a tool name identifies an agent-delegation target, matching the
 * canonical `agent____<slug>` prefix and the legacy `agent__<slug>` prefix
 * (sanitized names keep the prefix — only the slug's invalid characters change).
 */
export function isDelegationToolName(toolName: string | null | undefined): boolean {
  if (typeof toolName !== 'string') {
    return false
  }
  const candidate = toolName.trim()
  if (!candidate) {
    return false
  }
  return (
    candidate.startsWith(CANONICAL_DELEGATION_TOOL_PREFIX) ||
    candidate.startsWith(LEGACY_DELEGATION_TOOL_PREFIX)
  )
}

function readToolNames(entry: ExecutionLogEntry): string[] {
  const data = entry.data ?? {}
  const names: string[] = []
  for (const key of TOOL_NAME_DATA_KEYS) {
    const value = data[key]
    if (typeof value === 'string' && value) {
      names.push(value)
    }
  }
  return names
}

/**
 * True when the entry is a tool call/response that represents the child's own
 * delegation (the target slug is either carried in a tool-name field or recorded
 * directly on the entry as `delegation_target`).
 */
export function isDelegationToolEntry(entry: ExecutionLogEntry): boolean {
  if (!DELEGATION_CAPABLE_TOOL_EVENT_TYPES.has(entry.event_type)) {
    return false
  }
  if (readToolNames(entry).some(isDelegationToolName)) {
    return true
  }
  const delegationTarget = (entry.data ?? {}).delegation_target
  return typeof delegationTarget === 'string' && delegationTarget.length > 0
}

/**
 * Pure predicate: is this entry eligible for a parent's direct-child peek?
 *
 * Keeps the allow-list and additionally excludes the child's own delegation
 * activity (delegation lifecycle event types and delegation tool entries) so a
 * child's onward delegation never leaks into the parent's log peek.
 */
export function isDirectChildPeekEntry(entry: ExecutionLogEntry): boolean {
  if (!DIRECT_CHILD_PEEK_EVENT_TYPES.has(entry.event_type)) {
    return false
  }
  if (DELEGATION_LIFECYCLE_EVENT_TYPES.has(entry.event_type)) {
    return false
  }
  return !isDelegationToolEntry(entry)
}

/**
 * Pure projection returning only peek-eligible entries. Never mutates the input
 * and performs no I/O — independently unit-testable.
 */
export function filterDirectChildPeekEntries(
  entries: readonly ExecutionLogEntry[],
): ExecutionLogEntry[] {
  return entries.filter(isDirectChildPeekEntry)
}
