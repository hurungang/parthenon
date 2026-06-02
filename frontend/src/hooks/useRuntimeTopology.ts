import { useQuery } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type { RuntimeTopologyProjection } from '../types'

export function useRuntimeTopology(includeTerminal = false) {
  return useQuery<RuntimeTopologyProjection>({
    queryKey: ['agents', 'runtime', 'topology', includeTerminal],
    queryFn: async () => {
      const { data } = await apiClient.get<RuntimeTopologyProjection>(
        `/agents/runtime/topology?include_terminal=${includeTerminal ? 'true' : 'false'}`,
      )
      return data
    },
    refetchInterval: 5000,
  })
}
