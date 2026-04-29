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
export function useChatSession(sessionId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [connected, setConnected] = useState(false)
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback(() => {
    if (!sessionId) return

    const token = localStorage.getItem('access_token')
    const wsUrl = `${API_CONFIG.WS_BASE_URL}/sessions/${sessionId}?token=${token ?? ''}`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)

    ws.onmessage = (event: MessageEvent<string>) => {
      try {
        const data = JSON.parse(event.data) as {
          sender_role: ChatRole
          content: string
          timestamp: string
        }
        const msg: ChatMessage = {
          id: crypto.randomUUID(),
          role: data.sender_role,
          content: data.content,
          timestamp: data.timestamp,
        }
        setMessages((prev) => [...prev, msg])
        if (data.sender_role === 'agent' && data.content.startsWith('?')) {
          setPendingQuestion(data.content)
        }
      } catch {
        // ignore parse errors
      }
    }

    ws.onclose = () => {
      setConnected(false)
      // Auto-reconnect after 3s
      reconnectTimerRef.current = setTimeout(connect, 3000)
    }

    ws.onerror = () => ws.close()
  }, [sessionId])

  useEffect(() => {
    connect()
    return () => {
      wsRef.current?.close()
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    }
  }, [connect])

  const sendMessage = useCallback((content: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(content)
      const msg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'user',
        content,
        timestamp: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, msg])
      setPendingQuestion(null)
    }
  }, [])

  const clearMessages = useCallback(() => setMessages([]), [])

  return { messages, connected, pendingQuestion, sendMessage, clearMessages }
}
