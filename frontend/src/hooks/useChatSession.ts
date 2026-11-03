import { useCallback, useEffect, useRef, useState } from 'react'
import { API_CONFIG } from '../api/API_CONFIG'
import apiClient from '../api/apiClient'
import type { InterventionType, InterveneRequestMessage } from '../types'

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
  | 'waiting_for_human'
  | 'delegation_resumed'
  | 'timeout_or_failed'

export interface ChatStatus {
  kind: ChatStatusKind
  agentType: string | null
  toolName: string | null
  receiverSessionId: string | null
  timestamp: string
}

export interface DelegationSnippetLine {
  id: string
  kind: 'delegating' | 'waiting' | 'using_tool' | 'log_title'
  agentType: string | null
  toolName: string | null
  logTitle: string | null
  timestamp: string
}

export interface DelegationCycle {
  id: string
  startedAt: string
  snippets: DelegationSnippetLine[]
  snippetsCollapsed: boolean
  completed: boolean
  executionLogAvailable: boolean
  executionSessionId: string | null
}

export interface DelegationHistoryHydration {
  cycles: DelegationCycle[]
}

export interface ChatError {
  code: string
  message: string
}

interface ExecutionLogListEntry {
  id: string
  timestamp: string
  message?: string | null
}

function createDelegationCycle(startedAt: string): DelegationCycle {
  return {
    id: crypto.randomUUID(),
    startedAt,
    snippets: [],
    snippetsCollapsed: true,
    completed: false,
    executionLogAvailable: false,
    executionSessionId: null,
  }
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
    status !== 'timeout_or_failed' &&
    status !== 'delegation_resumed'
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
    receiverSessionId:
      typeof payload['receiver_session_id'] === 'string' && payload['receiver_session_id'].trim().length > 0
        ? payload['receiver_session_id'].trim()
        : null,
    timestamp,
  }
}

function toDelegationSnippetLine(status: ChatStatus): DelegationSnippetLine | null {
  if (status.kind === 'delegating' && status.agentType) {
    return {
      id: crypto.randomUUID(),
      kind: 'delegating',
      agentType: status.agentType,
      toolName: null,
      logTitle: null,
      timestamp: status.timestamp,
    }
  }

  if (status.kind === 'waiting' && status.agentType) {
    return {
      id: crypto.randomUUID(),
      kind: 'waiting',
      agentType: status.agentType,
      toolName: null,
      logTitle: null,
      timestamp: status.timestamp,
    }
  }

  // Note: 'using_tool' snippets are intentionally NOT added to the delegation
  // cycle panel — they represent regular MCP/system tool execution, not agent
  // delegation.  The standalone status line (statusUsingTool) handles them
  // separately in ConversationDialog.

  return null
}

function toNullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function pickRecordValue(payload: Record<string, unknown>, snakeKey: string, camelKey: string): unknown {
  if (snakeKey in payload) {
    return payload[snakeKey]
  }
  return payload[camelKey]
}

function parseGuardrailUsage(value: unknown): ConversationalGuardrailUsage | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }

  const payload = value as Record<string, unknown>
  return {
    policySnapshotId: (() => {
      const raw = pickRecordValue(payload, 'policy_snapshot_id', 'policySnapshotId')
      return typeof raw === 'string' ? raw : null
    })(),
    tokenUsageCurrentSession: toNullableNumber(
      pickRecordValue(payload, 'token_usage_current_session', 'tokenUsageCurrentSession'),
    ),
    tokenBudget: toNullableNumber(pickRecordValue(payload, 'token_budget', 'tokenBudget')),
    cumulativeIterations: toNullableNumber(
      pickRecordValue(payload, 'cumulative_iterations', 'cumulativeIterations'),
    ),
    maxIterations: toNullableNumber(pickRecordValue(payload, 'max_iterations', 'maxIterations')),
    delegatedSteps: toNullableNumber(pickRecordValue(payload, 'delegated_steps', 'delegatedSteps')),
    maxDelegatedSteps: toNullableNumber(
      pickRecordValue(payload, 'max_delegated_steps', 'maxDelegatedSteps'),
    ),
    delegationDepth: toNullableNumber(pickRecordValue(payload, 'delegation_depth', 'delegationDepth')),
    maxDelegationDepth: toNullableNumber(
      pickRecordValue(payload, 'max_delegation_depth', 'maxDelegationDepth'),
    ),
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
  const [chatError, setChatError] = useState<ChatError | null>(null)
  const [delegationCycles, setDelegationCycles] = useState<DelegationCycle[]>([])
  const [activeDelegationCycleId, setActiveDelegationCycleId] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const outboundQueueRef = useRef<string[]>([])
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // FIX-20261031-071721 (defect 1): live-delivery loss on unexpected WS close.
  // When the socket drops mid-turn (the reply is generated after the close, so
  // it is never transmitted and only shows up after exit/reopen), the hook now
  // (a) reconnects automatically with the SAME session id and (b) bumps
  // `recoveryEpoch` once reconnected while a turn was in flight, so the
  // dialog can refetch the persisted history and render the missed reply.
  const intentionalCloseRef = useRef(false)
  const reconnectAttemptsRef = useRef(0)
  const turnInFlightAtDisconnectRef = useRef(false)
  const [recoveryEpoch, setRecoveryEpoch] = useState(0)
  const chatStatusRef = useRef<ChatStatus | null>(null)
  const delegationCyclesRef = useRef<DelegationCycle[]>([])
  const activeDelegationCycleIdRef = useRef<string | null>(null)
  const seenExecutionLogIdsByCycleRef = useRef<Map<string, Set<string>>>(new Map())
  const pendingNewDelegationCycleRef = useRef(false)

  // Intervention state
  const [interventionRequest, setInterventionRequest] = useState<InterveneRequestMessage | null>(null)
  const [interventionQueueLength, _setInterventionQueueLength] = useState(0)
  const interventionActiveRef = useRef(false)

  useEffect(() => {
    chatStatusRef.current = chatStatus
  }, [chatStatus])

  useEffect(() => {
    delegationCyclesRef.current = delegationCycles
  }, [delegationCycles])

  useEffect(() => {
    activeDelegationCycleIdRef.current = activeDelegationCycleId
  }, [activeDelegationCycleId])

  const flushOutboundQueue = useCallback(() => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return
    if (outboundQueueRef.current.length === 0) return

    const queued = [...outboundQueueRef.current]
    outboundQueueRef.current = []
    for (const content of queued) {
      wsRef.current.send(JSON.stringify({ message: content }))
    }
  }, [])

  /** True when a conversational turn is still being processed (reply not yet received). */
  const isTurnInFlight = useCallback((): boolean => {
    const kind = chatStatusRef.current?.kind
    return (
      kind === 'thinking' ||
      kind === 'delegating' ||
      kind === 'waiting' ||
      kind === 'using_tool' ||
      kind === 'waiting_for_human' ||
      kind === 'delegation_resumed'
    )
  }, [])

  const connect = useCallback(() => {
    if (!sessionId) return
    intentionalCloseRef.current = false

    const token = localStorage.getItem('access_token')
    let wsUrl = `${API_CONFIG.WS_BASE_URL}/sessions/${sessionId}?token=${token ?? ''}`
    if (convSessionId) {
      wsUrl += `&conv_session_id=${convSessionId}`
    }
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      reconnectAttemptsRef.current = 0
      flushOutboundQueue()
      // If a turn was in flight while the socket was down, its reply may have
      // been missed — signal the dialog to refresh persisted history.
      if (turnInFlightAtDisconnectRef.current) {
        turnInFlightAtDisconnectRef.current = false
        setRecoveryEpoch((epoch) => epoch + 1)
      }
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
          request_id?: string
          intervention_type?: string
          reason?: string
          choices?: string[]
          delegation_depth?: number
          conversation_session_id?: string
          code?: string
          message?: string
        }

        // ── Handle intervention messages ───────────────────────────────────
        if (data.type === 'intervene_request') {
          const interveneMsg: InterveneRequestMessage = {
            type: 'intervene_request',
            request_id: data.request_id ?? '',
            intervention_type: (data.intervention_type as InterventionType) ?? 'approval',
            reason: data.reason ?? '',
            choices: data.choices,
            agent_type: data.agent_type,
            delegation_depth: data.delegation_depth ?? 0,
            conversation_session_id: data.conversation_session_id ?? '',
          }
          setInterventionRequest(interveneMsg)
          interventionActiveRef.current = true
          setChatStatus({
            kind: 'waiting_for_human',
            agentType: data.agent_type ?? null,
            toolName: null,
            receiverSessionId: null,
            timestamp: new Date().toISOString(),
          })
          return
        }

        if (data.type === 'intervene_status') {
          const statusVal = data.status
          if (statusVal === 'responded' || statusVal === 'cancelled' || statusVal === 'expired') {
            setInterventionRequest(null)
            interventionActiveRef.current = false
            setChatStatus((prev) => {
              const agentType = prev?.agentType ?? null
              return { kind: 'waiting', agentType, toolName: null, receiverSessionId: null, timestamp: new Date().toISOString() }
            })
          }
          return
        }

        if (data.type === 'chat_error') {
          const code = typeof data.code === 'string' ? data.code : ''
          if (code) {
            setChatError({
              code,
              message: typeof data.message === 'string' ? data.message : '',
            })
          }
          return
        }

        if (data.type === 'chat_blocked') {
          // Client tried to send a message while intervention is pending
          // The message is silently dropped; the UI blocks input anyway
          return
        }

        // FIX-20261031-091657: app-level keepalive from the CH while a turn is
        // in flight — no-op except refreshing the status timestamp so the
        // "thinking" indicator stays visibly alive during long turns.
        if (data.type === 'chat_status' && data.status === 'thinking_heartbeat') {
          setChatStatus((prev) => (prev ? { ...prev, timestamp: new Date().toISOString() } : prev))
          return
        }

        const parsedStatus = parseChatStatus(data)
        if (parsedStatus) {
          const isDelegationKind =
            parsedStatus.kind === 'delegating' ||
            parsedStatus.kind === 'waiting' ||
            parsedStatus.kind === 'using_tool'

          setChatStatus(parsedStatus)

          if (parsedStatus.kind === 'delegation_resumed') {
            const targetCycleId = activeDelegationCycleIdRef.current
            if (targetCycleId) {
              const resumeLine: DelegationSnippetLine = {
                id: crypto.randomUUID(),
                kind: 'waiting',
                agentType: parsedStatus.agentType,
                toolName: null,
                logTitle: null,
                timestamp: parsedStatus.timestamp,
              }
              setDelegationCycles((prev) =>
                prev.map((cycle) =>
                  cycle.id === targetCycleId
                    ? {
                        ...cycle,
                        snippets: [...cycle.snippets, resumeLine],
                      }
                    : cycle,
                ),
              )
            }
            return
          }

          if (!isDelegationKind) {
            return
          }

          let nextActiveCycleId = activeDelegationCycleIdRef.current
          const shouldStartNewCycle = pendingNewDelegationCycleRef.current || !nextActiveCycleId
          if (shouldStartNewCycle) {
            const startedAt = parsedStatus.timestamp ?? new Date().toISOString()
            const cycle = createDelegationCycle(startedAt)
            nextActiveCycleId = cycle.id
            activeDelegationCycleIdRef.current = cycle.id
            delegationCyclesRef.current = [...delegationCyclesRef.current, cycle]
            setDelegationCycles((prev) => [...prev, cycle])
            setActiveDelegationCycleId(cycle.id)
            seenExecutionLogIdsByCycleRef.current.set(cycle.id, new Set())
            pendingNewDelegationCycleRef.current = false
          }

          const targetCycleId = nextActiveCycleId
          if (!targetCycleId) {
            return
          }

          if (!seenExecutionLogIdsByCycleRef.current.has(targetCycleId)) {
            seenExecutionLogIdsByCycleRef.current.set(targetCycleId, new Set())
          }

          const snippetLine = toDelegationSnippetLine(parsedStatus)
          setDelegationCycles((prev) =>
            prev.map((cycle) => {
              if (cycle.id !== targetCycleId) {
                return cycle
              }

              let nextSnippets = cycle.snippets
              if (snippetLine) {
                const last = cycle.snippets[cycle.snippets.length - 1]
                if (
                  !last ||
                  last.kind !== snippetLine.kind ||
                  last.agentType !== snippetLine.agentType ||
                  last.toolName !== snippetLine.toolName
                ) {
                  nextSnippets = [...cycle.snippets, snippetLine]
                }
              }

              return {
                ...cycle,
                snippets: nextSnippets,
                executionSessionId: parsedStatus.receiverSessionId ?? cycle.executionSessionId,
                executionLogAvailable: cycle.executionLogAvailable || Boolean(parsedStatus.receiverSessionId),
              }
            }),
          )

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
          pendingNewDelegationCycleRef.current = false
          const statusKind = chatStatusRef.current?.kind
          const hadDelegationInFlight =
            statusKind === 'delegating' ||
            statusKind === 'waiting' ||
            statusKind === 'using_tool' ||
            statusKind === 'delegation_resumed' ||
            statusKind === 'waiting_for_human'

          const targetCycleId = activeDelegationCycleIdRef.current
          if (hadDelegationInFlight && targetCycleId) {
            setDelegationCycles((prev) =>
              prev.map((cycle) =>
                cycle.id === targetCycleId
                  ? {
                      ...cycle,
                      completed: true,
                      executionLogAvailable: cycle.executionLogAvailable || Boolean(cycle.executionSessionId),
                    }
                  : cycle,
              ),
            )
          }
        }

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
      // Unexpected close while a turn is still processing: remember it so the
      // reconnect can recover the missed reply, and reconnect automatically.
      // (Auto-reconnect is intentional here — without it a mid-turn disconnect
      // permanently loses the live response; intentional unmount closes are
      // marked via intentionalCloseRef and never reconnect.)
      if (isTurnInFlight()) {
        turnInFlightAtDisconnectRef.current = true
      }
      if (intentionalCloseRef.current || reconnectAttemptsRef.current >= 5) {
        return
      }
      reconnectAttemptsRef.current += 1
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = setTimeout(() => connect(), 1500)
    }

    ws.onerror = () => ws.close()
  }, [sessionId, convSessionId, flushOutboundQueue])

  const activeDelegationCycle =
    delegationCycles.find((cycle) => cycle.id === activeDelegationCycleId) ?? null

  useEffect(() => {
    if (!sessionId) {
      return
    }

    const shouldPollLogs =
      chatStatus?.kind === 'delegating' ||
      chatStatus?.kind === 'waiting' ||
      chatStatus?.kind === 'waiting_for_human' ||
      chatStatus?.kind === 'using_tool'

    if (!activeDelegationCycleId) {
      return
    }

    if (!activeDelegationCycle?.executionSessionId) {
      return
    }

    if (!shouldPollLogs) {
      return
    }

    // Skip polling in tests to prevent hangs from persistent intervals
    if ((typeof window !== 'undefined' && (window as any).__VITEST__)) {
      return
    }

    let cancelled = false

    const fetchExecutionLogTitles = async () => {
      try {
        const { data } = await apiClient.get<ExecutionLogListEntry[]>(
          `/agents/sessions/${activeDelegationCycle.executionSessionId}/logs`,
        )

        if (cancelled || !Array.isArray(data)) {
          return
        }

        const seenIds = seenExecutionLogIdsByCycleRef.current.get(activeDelegationCycleId) ?? new Set<string>()
        seenExecutionLogIdsByCycleRef.current.set(activeDelegationCycleId, seenIds)

        const newLines: DelegationSnippetLine[] = []
        for (const entry of data) {
          if (!entry?.id || seenIds.has(entry.id)) {
            continue
          }
          seenIds.add(entry.id)

          const title = typeof entry.message === 'string' ? entry.message.trim() : ''
          if (!title) {
            continue
          }

          newLines.push({
            id: `log-${entry.id}`,
            kind: 'log_title',
            agentType: null,
            toolName: null,
            logTitle: title,
            timestamp: entry.timestamp || new Date().toISOString(),
          })
        }

        if (newLines.length > 0) {
          setDelegationCycles((prev) =>
            prev.map((cycle) =>
              cycle.id === activeDelegationCycleId
                ? {
                    ...cycle,
                    executionLogAvailable: true,
                    snippets: [...cycle.snippets, ...newLines],
                  }
                : cycle,
            ),
          )
        }
      } catch {
        // Best-effort streaming enhancement only.
      }
    }

    void fetchExecutionLogTitles()
    const timer = setInterval(() => {
      void fetchExecutionLogTitles()
    }, 1500)

    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [sessionId, chatStatus?.kind, activeDelegationCycleId, activeDelegationCycle?.executionSessionId])

  useEffect(() => {
    connect()
    return () => {
      // Mark the close as intentional so onclose never schedules a reconnect
      // for a torn-down dialog.
      intentionalCloseRef.current = true
      wsRef.current?.close()
      outboundQueueRef.current = []
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    }
  }, [connect])

  const sendMessage = useCallback((content: string) => {
    if (!content.trim()) return false

    // Block messages when intervention is active
    if (interventionActiveRef.current) {
      return false
    }

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
    pendingNewDelegationCycleRef.current = true
    setMessages((prev) => [...prev, msg])
    setChatStatus({
      kind: 'thinking',
      agentType: null,
      toolName: null,
      receiverSessionId: null,
      timestamp: new Date().toISOString(),
    })
    setPendingQuestion(null)
    setChatError(null)
    return true
  }, [])

  const clearMessages = useCallback(() => {
    delegationCyclesRef.current = []
    activeDelegationCycleIdRef.current = null
    setMessages([])
    setDelegationCycles([])
    setActiveDelegationCycleId(null)
    seenExecutionLogIdsByCycleRef.current = new Map()
    pendingNewDelegationCycleRef.current = false
  }, [])

  const toggleDelegationSnippetsCollapsed = useCallback(() => {
    const targetCycleId = activeDelegationCycleIdRef.current
    if (!targetCycleId) {
      const cycle = createDelegationCycle(new Date().toISOString())
      cycle.snippetsCollapsed = false
      activeDelegationCycleIdRef.current = cycle.id
      delegationCyclesRef.current = [...delegationCyclesRef.current, cycle]
      setDelegationCycles((prev) => [...prev, cycle])
      setActiveDelegationCycleId(cycle.id)
      return
    }

    setDelegationCycles((prev) =>
      prev.map((cycle) =>
        cycle.id === targetCycleId
          ? { ...cycle, snippetsCollapsed: !cycle.snippetsCollapsed }
          : cycle,
      ),
    )
  }, [])

  const setDelegationSnippetsCollapsed = useCallback((collapsed: boolean) => {
    const targetCycleId = activeDelegationCycleIdRef.current
    if (!targetCycleId) {
      const cycle = createDelegationCycle(new Date().toISOString())
      cycle.snippetsCollapsed = collapsed
      activeDelegationCycleIdRef.current = cycle.id
      delegationCyclesRef.current = [...delegationCyclesRef.current, cycle]
      setDelegationCycles((prev) => [...prev, cycle])
      setActiveDelegationCycleId(cycle.id)
      return
    }

    setDelegationCycles((prev) =>
      prev.map((cycle) =>
        cycle.id === targetCycleId
          ? { ...cycle, snippetsCollapsed: collapsed }
          : cycle,
      ),
    )
  }, [])

  const hydrateDelegationFromHistory = useCallback((history: DelegationHistoryHydration) => {
    const nextCycles = Array.isArray(history.cycles)
      ? history.cycles.map((cycle) => ({
          ...cycle,
          snippets: Array.isArray(cycle.snippets) ? cycle.snippets : [],
          snippetsCollapsed: typeof cycle.snippetsCollapsed === 'boolean' ? cycle.snippetsCollapsed : true,
          completed: typeof cycle.completed === 'boolean' ? cycle.completed : true,
          executionLogAvailable: Boolean(cycle.executionLogAvailable),
          executionSessionId:
            typeof cycle.executionSessionId === 'string' && cycle.executionSessionId.trim().length > 0
              ? cycle.executionSessionId.trim()
              : null,
        }))
      : []

    seenExecutionLogIdsByCycleRef.current = new Map()
    for (const cycle of nextCycles) {
      seenExecutionLogIdsByCycleRef.current.set(cycle.id, new Set())
    }

    setDelegationCycles(nextCycles)
    setActiveDelegationCycleId(nextCycles.length > 0 ? nextCycles[nextCycles.length - 1].id : null)
    delegationCyclesRef.current = nextCycles
    activeDelegationCycleIdRef.current = nextCycles.length > 0 ? nextCycles[nextCycles.length - 1].id : null
    pendingNewDelegationCycleRef.current = false

    for (const cycle of nextCycles) {
      if (!cycle.executionSessionId) {
        continue
      }

      void apiClient
        .get<ExecutionLogListEntry[]>(`/agents/sessions/${cycle.executionSessionId}/logs`)
        .then(({ data }) => {
          if (!Array.isArray(data)) {
            return
          }

          const seenIds = seenExecutionLogIdsByCycleRef.current.get(cycle.id) ?? new Set<string>()
          seenExecutionLogIdsByCycleRef.current.set(cycle.id, seenIds)

          const logLines: DelegationSnippetLine[] = []
          for (const entry of data) {
            if (!entry?.id || seenIds.has(entry.id)) {
              continue
            }
            seenIds.add(entry.id)

            const title = typeof entry.message === 'string' ? entry.message.trim() : ''
            if (!title) {
              continue
            }

            logLines.push({
              id: `log-${entry.id}`,
              kind: 'log_title',
              agentType: null,
              toolName: null,
              logTitle: title,
              timestamp: entry.timestamp || new Date().toISOString(),
            })
          }

          if (logLines.length > 0) {
            setDelegationCycles((prev) =>
              prev.map((existingCycle) =>
                existingCycle.id === cycle.id
                  ? {
                      ...existingCycle,
                      completed: true,
                      executionLogAvailable: true,
                      snippets: [...existingCycle.snippets, ...logLines],
                    }
                  : existingCycle,
              ),
            )
          }
        })
        .catch(() => {
          // Best-effort hydration enhancement only.
        })
    }
  }, [])

  const delegationSnippets = activeDelegationCycle?.snippets ?? []
  const delegationSnippetsCollapsed = activeDelegationCycle?.snippetsCollapsed ?? true
  const delegationCompleted = activeDelegationCycle?.completed ?? false
  const delegationExecutionLogAvailable = activeDelegationCycle?.executionLogAvailable ?? false
  const delegationExecutionSessionId = activeDelegationCycle?.executionSessionId ?? null

  // ── Intervention actions ─────────────────────────────────────────────────

  const sendInterventionResponse = useCallback(
    (requestId: string, value: {
      approval_value?: boolean
      selected_choice?: string
      text_value?: string
    }) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({
            type: 'intervene_response',
            request_id: requestId,
            ...value,
          }),
        )
        setInterventionRequest(null)
        interventionActiveRef.current = false
        setChatStatus((prev) => ({
          kind: 'waiting',
          agentType: prev?.agentType ?? null,
          toolName: null,
          receiverSessionId: null,
          timestamp: new Date().toISOString(),
        }))
        return true
      }
      return false
    },
    [],
  )

  const cancelIntervention = useCallback((requestId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: 'intervene_cancel',
          request_id: requestId,
        }),
      )
      setInterventionRequest(null)
      interventionActiveRef.current = false
      setChatStatus((prev) => ({
        kind: 'waiting',
        agentType: prev?.agentType ?? null,
        toolName: null,
        receiverSessionId: null,
        timestamp: new Date().toISOString(),
      }))
      return true
    }
    return false
  }, [])

  return {
    messages,
    connected,
    pendingQuestion,
    sessionTitle,
    guardrailUsage,
    chatStatus,
    delegationCycles,
    activeDelegationCycleId,
    delegationSnippets,
    delegationSnippetsCollapsed,
    delegationCompleted,
    delegationExecutionLogAvailable,
    delegationExecutionSessionId,
    /** Bumped after a reconnect that happened while a turn was in flight —
     * consumers should refresh persisted history to recover missed replies. */
    recoveryEpoch,
    setDelegationSnippetsCollapsed,
    toggleDelegationSnippetsCollapsed,
    hydrateDelegationFromHistory,
    sendMessage,
    clearMessages,
    chatError,
    // Intervention
    interventionRequest,
    interventionQueueLength,
    sendInterventionResponse,
    cancelIntervention,
  }
}
