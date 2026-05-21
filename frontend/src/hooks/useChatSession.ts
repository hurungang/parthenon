import { useCallback, useEffect, useRef, useState } from 'react'
import { API_CONFIG } from '../api/API_CONFIG'

export type ChatRole = 'user' | 'agent' | 'system'

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  timestamp: string
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
        }

        // Handle title_update server event without adding it to messages
        if (data.type === 'title_update' && data.title) {
          setSessionTitle(data.title)
          return
        }

        const msg: ChatMessage = {
          id: crypto.randomUUID(),
          role: data.sender_role ?? 'agent',
          content: data.content ?? '',
          timestamp: data.timestamp ?? new Date().toISOString(),
        }
        setMessages((prev) => [...prev, msg])
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
    setPendingQuestion(null)
    return true
  }, [])

  const clearMessages = useCallback(() => setMessages([]), [])

  return { messages, connected, pendingQuestion, sessionTitle, sendMessage, clearMessages }
}
