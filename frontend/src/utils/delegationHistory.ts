import type { DelegationHistoryHydration, DelegationSnippetLine } from '../hooks/useChatSession'
import type { ConversationTurn, ToolCallRecord } from '../types'

interface DelegationCycleHydrationShape {
  id: string
  startedAt: string
  snippets: DelegationSnippetLine[]
  snippetsCollapsed: boolean
  completed: boolean
  executionLogAvailable: boolean
  executionSessionId: string | null
}

interface HistoryMessage {
  id: string
  role: 'user' | 'agent' | 'system'
  content: string
  timestamp: string
}

function normalizeText(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null
  }
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

function toSnippetFromToolCall(toolCall: ToolCallRecord): DelegationSnippetLine | null {
  if (toolCall.tool_name !== 'chat_status') {
    return null
  }

  const output = toolCall.tool_output
  if (!output || typeof output !== 'object') {
    return null
  }

  const status = normalizeText((output as Record<string, unknown>)['status'])
  if (status !== 'delegating' && status !== 'waiting' && status !== 'using_tool') {
    return null
  }

  return {
    id: `history-${toolCall.id}`,
    kind: status,
    agentType: normalizeText((output as Record<string, unknown>)['agent_type']),
    toolName: normalizeText((output as Record<string, unknown>)['tool_name']),
    logTitle: null,
    timestamp:
      normalizeText((output as Record<string, unknown>)['timestamp']) ?? toolCall.created_at,
  }
}

function toEpochMs(value: string | null | undefined): number {
  if (!value) {
    return Number.MAX_SAFE_INTEGER
  }
  const ms = Date.parse(value)
  return Number.isNaN(ms) ? Number.MAX_SAFE_INTEGER : ms
}
export function buildDelegationHistoryFromTurns(
  turns: ConversationTurn[] | null | undefined,
): DelegationHistoryHydration {
  const cycles: DelegationCycleHydrationShape[] = []
  let activeCycle: DelegationCycleHydrationShape | null = null

  const ensureActiveCycle = (startedAt: string): DelegationCycleHydrationShape => {
    if (activeCycle) {
      return activeCycle
    }

    const cycle: DelegationCycleHydrationShape = {
      id: `history-cycle-${crypto.randomUUID()}`,
      startedAt,
      snippets: [],
      snippetsCollapsed: true,
      completed: true,
      executionLogAvailable: false,
      executionSessionId: null,
    }
    cycles.push(cycle)
    activeCycle = cycle
    return cycle
  }

  for (const turn of turns ?? []) {
    for (const toolCall of turn.tool_calls ?? []) {
      const snippet = toSnippetFromToolCall(toolCall)
      if (!snippet) {
        continue
      }

      const snippetTimestamp = snippet.timestamp || toolCall.created_at

      // A 'delegating' snippet always starts a fresh cycle.
      // 'waiting'/'using_tool' snippets continue the most recent cycle;
      // if there is no active cycle (e.g. after a status-only agent turn boundary),
      // reuse the last created cycle rather than starting a spurious second one.
      if (snippet.kind === 'delegating') {
        activeCycle = null
        ensureActiveCycle(snippetTimestamp)
      } else if (!activeCycle) {
        if (cycles.length > 0) {
          activeCycle = cycles[cycles.length - 1]
        } else {
          ensureActiveCycle(snippetTimestamp)
        }
      }

      const targetCycle = activeCycle!

      const output = toolCall.tool_output
      if (output && typeof output === 'object') {
        const receiverSessionId = normalizeText((output as Record<string, unknown>)['receiver_session_id'])
        if (receiverSessionId) {
          targetCycle.executionSessionId = receiverSessionId
          targetCycle.executionLogAvailable = true
        }
      }

      const last = targetCycle.snippets[targetCycle.snippets.length - 1]
      if (
        last &&
        last.kind === snippet.kind &&
        last.agentType === snippet.agentType &&
        last.toolName === snippet.toolName
      ) {
        continue
      }
      targetCycle.snippets.push(snippet)
      if (snippet.kind === 'waiting') {
        targetCycle.completed = true
      }
    }

    if (turn.role === 'agent' && activeCycle) {
      activeCycle.completed = true
      // Do NOT reset activeCycle here. Continuation agent turns (e.g. a response turn
      // that follows a status-only delegating turn) may still need to append 'waiting'
      // or 'using_tool' snippets to the same cycle. A new 'delegating' snippet will
      // reset activeCycle when a genuinely new delegation starts.
    }
  }

  return {
    cycles,
  }
}

function extractDelegatedAgentTypeFromTurn(turn: ConversationTurn): string | null {
  for (const toolCall of turn.tool_calls ?? []) {
    if (toolCall.tool_name !== 'chat_status') {
      continue
    }
    const output = toolCall.tool_output
    if (!output || typeof output !== 'object') {
      continue
    }
    const status = normalizeText((output as Record<string, unknown>)['status'])
    if (status !== 'delegating') {
      continue
    }
    const agentType = normalizeText((output as Record<string, unknown>)['agent_type'])
    if (agentType) {
      return agentType
    }
  }
  return null
}

function isDelegationStatusOnlyTurn(
  turn: ConversationTurn,
  formatDelegationMessage: (agentType: string) => string,
): boolean {
  if (turn.role !== 'agent') {
    return false
  }

  const content = normalizeText(turn.content)
  if (!content) {
    return false
  }

  const toolCalls = turn.tool_calls ?? []
  if (toolCalls.length === 0 || toolCalls.some((toolCall) => toolCall.tool_name !== 'chat_status')) {
    return false
  }

  const delegatedAgentType = extractDelegatedAgentTypeFromTurn(turn)
  if (delegatedAgentType && content === formatDelegationMessage(delegatedAgentType)) {
    return true
  }

  return content === 'delegating' || content === 'waiting' || content === 'using_tool'
}

export function buildHistoryMessagesFromTurns(
  turns: ConversationTurn[] | null | undefined,
  formatDelegationMessage: (agentType: string) => string,
): HistoryMessage[] {
  const history: HistoryMessage[] = []

  for (const turn of turns ?? []) {
    if (isDelegationStatusOnlyTurn(turn, formatDelegationMessage)) {
      continue
    }

    history.push({
      id: turn.id,
      role: turn.role === 'agent' ? 'agent' : turn.role === 'user' ? 'user' : 'system',
      content: turn.content,
      timestamp: turn.created_at,
    })
  }

  history.sort((a, b) => toEpochMs(a.timestamp) - toEpochMs(b.timestamp))

  return history
}
