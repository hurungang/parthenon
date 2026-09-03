import { useQuery } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
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

/**
 * Fetch the live runtime topology projection.
 *
 * @param includeTerminal include ALL terminal jobs regardless of age.
 * @param recentMinutes width of the recent-terminal window in minutes
 *   (backend `recent_minutes` query param, default 30; `0` disables the
 *   window). Changing the value refetches — it is part of the query key.
 */
export function useRuntimeTopology(includeTerminal = false, recentMinutes = 30) {
  return useQuery<RuntimeTopologyProjection>({
    queryKey: ['agents', 'runtime', 'topology', includeTerminal, recentMinutes],
    queryFn: async () => {
      const { data } = await apiClient.get<RuntimeTopologyProjection>(
        `/agents/runtime/topology?include_terminal=${includeTerminal ? 'true' : 'false'}&recent_minutes=${recentMinutes}`,
      )
      return data
    },
    refetchInterval: 5000,
  })
}
