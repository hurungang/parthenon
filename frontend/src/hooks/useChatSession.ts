import { useCallback, useEffect, useRef, useState } from 'react'
import { API_CONFIG } from '../api/API_CONFIG'

export type ChatRole = 'user' | 'agent' | 'system'

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  timestamp: string
}

export interface ConversationalGuardrailUsage {
  policySnapshotId: string | null
  tokenUsageCurrentSession: number | null
  tokenBudget: number | null
  cumulativeIterations: number | null
  maxIterations: number | null
  delegatedSteps: number | null
  maxDelegatedSteps: number | null
  delegationDepth: number | null
  maxDelegationDepth: number | null
}

export type ChatStatusKind =
  | 'thinking'
  | 'delegating'
  | 'waiting'
  | 'using_tool'
  | 'timeout_or_failed'

export interface ChatStatus {
  kind: ChatStatusKind
  agentType: string | null
  toolName: string | null
  timestamp: string
}

function normalizeToolDisplayName(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null
  }

  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

function normalizeDelegatedAgentType(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null
  }

  const trimmed = value.trim()
  if (!trimmed) {
    return null
  }

  if (trimmed.startsWith('agent____') && trimmed.length > 'agent____'.length) {
    return trimmed.slice('agent____'.length)
  }

  if (trimmed.startsWith('agent__') && trimmed.length > 'agent__'.length) {
    return trimmed.slice('agent__'.length)
  }

  return trimmed
}

function parseChatStatus(value: unknown): ChatStatus | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }

  const payload = value as Record<string, unknown>
  const type = payload['type']
  if (type !== 'chat_status') {
    return null
  }

  const status = payload['status']
  if (
    status !== 'thinking' &&
    status !== 'delegating' &&
    status !== 'waiting' &&
    status !== 'using_tool' &&
    status !== 'timeout_or_failed'
  ) {
    return null
  }

  const timestamp = typeof payload['timestamp'] === 'string'
    ? payload['timestamp']
    : new Date().toISOString()

  return {
    kind: status,
    agentType: normalizeDelegatedAgentType(payload['agent_type']),
    toolName: normalizeToolDisplayName(payload['tool_name']),
    timestamp,
  }
}

function toNullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function parseGuardrailUsage(value: unknown): ConversationalGuardrailUsage | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }

  const payload = value as Record<string, unknown>
  return {
    policySnapshotId:
      typeof payload['policy_snapshot_id'] === 'string' ? payload['policy_snapshot_id'] : null,
    tokenUsageCurrentSession: toNullableNumber(payload['token_usage_current_session']),
    tokenBudget: toNullableNumber(payload['token_budget']),
    cumulativeIterations: toNullableNumber(payload['cumulative_iterations']),
    maxIterations: toNullableNumber(payload['max_iterations']),
    delegatedSteps: toNullableNumber(payload['delegated_steps']),
    maxDelegatedSteps: toNullableNumber(payload['max_delegated_steps']),
    delegationDepth: toNullableNumber(payload['delegation_depth']),
    maxDelegationDepth: toNullableNumber(payload['max_delegation_depth']),
  }
}

/**
 * Manages WebSocket connection lifecycle, inbound message queue,
 * pending question state, and reconnection for a chat session.
 */
export function useChatSession(sessionId: string | null, convSessionId?: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [connected, setConnected] = useState(false)
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null)
  const [sessionTitle, setSessionTitle] = useState<string | null>(null)
  const [guardrailUsage, setGuardrailUsage] = useState<ConversationalGuardrailUsage | null>(null)
  const [chatStatus, setChatStatus] = useState<ChatStatus | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const outboundQueueRef = useRef<string[]>([])
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const flushOutboundQueue = useCallback(() => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return
    if (outboundQueueRef.current.length === 0) return

    const queued = [...outboundQueueRef.current]
    outboundQueueRef.current = []
    for (const content of queued) {
      wsRef.current.send(JSON.stringify({ message: content }))
    }
  }, [])

  const connect = useCallback(() => {
    if (!sessionId) return

    const token = localStorage.getItem('access_token')
    let wsUrl = `${API_CONFIG.WS_BASE_URL}/sessions/${sessionId}?token=${token ?? ''}`
    if (convSessionId) {
      wsUrl += `&conv_session_id=${convSessionId}`
    }
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      flushOutboundQueue()
    }

    ws.onmessage = (event: MessageEvent<string>) => {
      try {
        const data = JSON.parse(event.data) as {
          type?: string
          title?: string
          sender_role?: ChatRole
          content?: string
          timestamp?: string
          guardrail_usage?: unknown
          status?: string
          agent_type?: string
        }

        const parsedStatus = parseChatStatus(data)
        if (parsedStatus) {
          setChatStatus(parsedStatus)
          return
        }

        // Handle title_update server event without adding it to messages
        if (data.type === 'title_update' && data.title) {
          setSessionTitle(data.title)
          return
        }

        if (data.type === 'guardrail_update') {
          const parsed = parseGuardrailUsage(data.guardrail_usage)
          if (parsed) {
            setGuardrailUsage(parsed)
          }
          return
        }

        const msg: ChatMessage = {
          id: crypto.randomUUID(),
          role: data.sender_role ?? 'agent',
          content: data.content ?? '',
          timestamp: data.timestamp ?? new Date().toISOString(),
        }
        setMessages((prev) => [...prev, msg])
        if (data.sender_role === 'agent') {
          setChatStatus((prev) => (prev?.kind === 'timeout_or_failed' ? prev : null))
        }
        if (data.sender_role === 'agent' && (data.content ?? '').startsWith('?')) {
          setPendingQuestion(data.content ?? null)
        }
      } catch {
        // ignore parse errors
      }
    }

    ws.onclose = () => {
      setConnected(false)
      // Don't auto-reconnect - let the component decide if it needs to reconnect
      // Auto-reconnect can cause issues when dialog is closed
    }

    ws.onerror = () => ws.close()
  }, [sessionId, convSessionId, flushOutboundQueue])

  useEffect(() => {
    connect()
    return () => {
      wsRef.current?.close()
      outboundQueueRef.current = []
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    }
  }, [connect])

  const sendMessage = useCallback((content: string) => {
    if (!content.trim()) return false

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ message: content }))
    } else {
      outboundQueueRef.current.push(content)
    }

    const msg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, msg])
    setChatStatus({
      kind: 'thinking',
      agentType: null,
      toolName: null,
      timestamp: new Date().toISOString(),
    })
    setPendingQuestion(null)
    return true
  }, [])

  const clearMessages = useCallback(() => setMessages([]), [])

  return {
    messages,
    connected,
    pendingQuestion,
    sessionTitle,
    guardrailUsage,
    chatStatus,
    sendMessage,
    clearMessages,
  }
}
