import { useEffect, useRef, useState } from 'react'
import { API_CONFIG } from '../api/API_CONFIG'
import type { AgentJobStatus, ExecutionLogEntry } from '../types'

export type ExecutionLogStreamConnectionState =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'fallback'

interface UseSessionExecutionLogStreamOptions {
  sessionId: string | null
  enabled: boolean
  sessionStatus?: AgentJobStatus
  reconnectAttempts?: number
  reconnectDelayMs?: number
}

interface StreamLogEntryEvent {
  type: 'log_entry'
  entry: ExecutionLogEntry
}

interface StreamCompletedEvent {
  type: 'stream_completed'
  session_id: string
  session_status: AgentJobStatus | 'failed'
}

type StreamEvent = StreamLogEntryEvent | StreamCompletedEvent

function isTerminalStatus(status: AgentJobStatus | undefined): boolean {
  return status === 'completed' || status === 'failed'
}

function toAbsoluteUrl(path: string): string {
  if (API_CONFIG.BASE_URL.startsWith('http://') || API_CONFIG.BASE_URL.startsWith('https://')) {
    return `${API_CONFIG.BASE_URL}${path}`
  }

  const base = window.location.origin
  const normalized = API_CONFIG.BASE_URL.startsWith('/') ? API_CONFIG.BASE_URL : `/${API_CONFIG.BASE_URL}`
  return `${base}${normalized}${path}`
}

export function useSessionExecutionLogStream({
  sessionId,
  enabled,
  sessionStatus,
  reconnectAttempts = 2,
  reconnectDelayMs = 1000,
}: UseSessionExecutionLogStreamOptions) {
  const [entries, setEntries] = useState<ExecutionLogEntry[]>([])
  const [connectionState, setConnectionState] = useState<ExecutionLogStreamConnectionState>('idle')

  const abortControllerRef = useRef<AbortController | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    setEntries([])
  }, [sessionId])

  useEffect(() => {
    if (!sessionId || !enabled || isTerminalStatus(sessionStatus)) {
      setConnectionState('idle')
      return
    }

    let cancelled = false
    const seenEntryIds = new Set<string>()

    const appendEntry = (entry: ExecutionLogEntry) => {
      if (seenEntryIds.has(entry.id)) {
        return
      }
      seenEntryIds.add(entry.id)
      setEntries((prev) => [...prev, entry])
    }

    const connect = async (attempt: number): Promise<void> => {
      if (cancelled) {
        return
      }

      setConnectionState(attempt === 0 ? 'connecting' : 'reconnecting')
      abortControllerRef.current = new AbortController()

      try {
        const token = localStorage.getItem('access_token')
        const url = toAbsoluteUrl(`/agents/sessions/${sessionId}/logs/stream`)
        const response = await fetch(url, {
          method: 'GET',
          headers: {
            Accept: 'application/x-ndjson',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          signal: abortControllerRef.current.signal,
        })

        if (!response.ok || !response.body) {
          throw new Error(`Stream request failed with status ${response.status}`)
        }

        setConnectionState('connected')
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (!cancelled) {
          const { done, value } = await reader.read()
          if (done) {
            break
          }

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''

          for (const rawLine of lines) {
            const line = rawLine.trim()
            if (!line) {
              continue
            }

            let event: StreamEvent | null = null
            try {
              event = JSON.parse(line) as StreamEvent
            } catch {
              event = null
            }

            if (!event) {
              continue
            }

            if (event.type === 'log_entry') {
              appendEntry(event.entry)
              continue
            }

            if (event.type === 'stream_completed') {
              setConnectionState('idle')
              return
            }
          }
        }

        if (!cancelled && !isTerminalStatus(sessionStatus)) {
          throw new Error('Stream closed before terminal marker')
        }
      } catch {
        if (cancelled) {
          return
        }

        if (attempt < reconnectAttempts) {
          reconnectTimerRef.current = setTimeout(() => {
            void connect(attempt + 1)
          }, reconnectDelayMs)
          return
        }

        setConnectionState('fallback')
      }
    }

    void connect(0)

    return () => {
      cancelled = true
      abortControllerRef.current?.abort()
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
      }
    }
  }, [enabled, reconnectAttempts, reconnectDelayMs, sessionId, sessionStatus])

  return {
    entries,
    connectionState,
    isFallback: connectionState === 'fallback',
  }
}
