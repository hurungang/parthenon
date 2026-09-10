import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import { API_CONFIG } from '../api/API_CONFIG'
import type { RuntimeTopologyNode, RuntimeTopologyProjection } from '../types'

/**
 * Default-visibility predicate for the Agent Runtime Monitor.
 *
 * Active (non-sleep) nodes are visible by default.  Sleeping nodes are
 * only visible by default when they are awaiting human intervention
 * (`needs_intervention === true`); otherwise they are hidden so the map
 * is not dominated by idle conversations.
 */
export function isNodeVisibleByDefault(node: RuntimeTopologyNode): boolean {
  if (node.status === 'sleep') {
    return node.needs_intervention === true
  }
  return true
}

// Stream reconnect backoff bounds (2s → 4s → 8s … capped at 30s).  While the
// stream is down the 5s polling fallback keeps the cache fresh, so the view
// never silently goes stale.
const STREAM_RETRY_BASE_MS = 2000
const STREAM_RETRY_MAX_MS = 30000

/**
 * Fetch the live runtime topology projection, stream-first.
 *
 * An `EventSource` to `GET /agents/runtime/topology/stream` pushes each
 * changed projection payload straight into the React Query cache
 * (`setQueryData`), so map changes land within a second or two — no poll
 * cycle wait.  The 5s `refetchInterval` polling is retained purely as the
 * automatic fallback: it takes over while the stream is down and pauses
 * again once the stream (re)opens.
 *
 * @param includeTerminal include ALL terminal jobs regardless of age.
 * @param recentMinutes width of the recent-terminal window in minutes
 *   (backend `recent_minutes` query param, default 30; `0` disables the
 *   window). Changing the value refetches and reconnects the stream — it
 *   is part of the query key.
 */
export function useRuntimeTopology(includeTerminal = false, recentMinutes = 30) {
  const queryClient = useQueryClient()
  const queryKey = useMemo(
    () => ['agents', 'runtime', 'topology', includeTerminal, recentMinutes] as const,
    [includeTerminal, recentMinutes],
  )
  const [streamOpen, setStreamOpen] = useState(false)

  useEffect(() => {
    let source: EventSource | null = null
    let retryMs = STREAM_RETRY_BASE_MS
    let retryTimer: number | null = null
    let disposed = false

    const connect = () => {
      if (disposed) return
      // Read the token fresh on every attempt so a token refresh
      // mid-session is picked up on the next reconnect.  No token → the
      // stream cannot authenticate (EventSource cannot set headers), so the
      // hook stays in polling-only mode.
      const token = localStorage.getItem('access_token')
      if (!token) return
      const url =
        `${API_CONFIG.BASE_URL}/agents/runtime/topology/stream` +
        `?include_terminal=${includeTerminal ? 'true' : 'false'}` +
        `&recent_minutes=${recentMinutes}` +
        `&token=${encodeURIComponent(token)}`
      source = new EventSource(url)
      source.onopen = () => {
        retryMs = STREAM_RETRY_BASE_MS
        setStreamOpen(true)
      }
      source.onmessage = (event: MessageEvent<string>) => {
        try {
          const payload = JSON.parse(event.data) as RuntimeTopologyProjection
          queryClient.setQueryData(queryKey, payload)
        } catch {
          // Malformed frame — ignore; the poll fallback keeps the cache fresh.
        }
      }
      source.onerror = () => {
        // Stream down: close it, hand the refresh duty to the poll fallback,
        // and retry with a bounded backoff (fresh token on each attempt).
        source?.close()
        source = null
        setStreamOpen(false)
        if (disposed) return
        retryTimer = window.setTimeout(connect, retryMs)
        retryMs = Math.min(retryMs * 2, STREAM_RETRY_MAX_MS)
      }
    }

    connect()
    return () => {
      disposed = true
      if (retryTimer !== null) window.clearTimeout(retryTimer)
      source?.close()
      setStreamOpen(false)
    }
  }, [queryClient, queryKey, includeTerminal, recentMinutes])

  return useQuery<RuntimeTopologyProjection>({
    queryKey,
    queryFn: async () => {
      const { data } = await apiClient.get<RuntimeTopologyProjection>(
        `/agents/runtime/topology?include_terminal=${includeTerminal ? 'true' : 'false'}&recent_minutes=${recentMinutes}`,
      )
      return data
    },
    // Polling is the automatic fallback only: it refreshes the cache while
    // the live stream is down and pauses as soon as the stream (re)opens.
    refetchInterval: streamOpen ? false : 5000,
  })
}
