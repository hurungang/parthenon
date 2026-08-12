import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type {
  RuntimeTerminationCascadeOutcome,
  RuntimeTerminationRequest,
  RuntimeTerminationRequestPayload,
} from '../types'

export function useNodeTermination() {
  return useMutation<RuntimeTerminationRequest, unknown, RuntimeTerminationRequestPayload>({
    mutationFn: async (payload) => {
      const { data } = await apiClient.post<RuntimeTerminationRequest>(
        '/agents/runtime/terminate',
        payload,
      )
      return data
    },
  })
}

export function useTerminationOutcomes(requestId: string | null) {
  return useQuery<RuntimeTerminationCascadeOutcome[]>({
    queryKey: ['agents', 'runtime', 'terminate', requestId],
    queryFn: async () => {
      const { data } = await apiClient.get<RuntimeTerminationCascadeOutcome[]>(
        `/agents/runtime/terminate/${requestId}`,
      )
      return data
    },
    enabled: !!requestId,
    refetchInterval: 3000,
  })
}

export interface RuntimeTerminalJobPurgeResult {
  purged_count: number
  remaining_terminal_count: number
  cutoff: string
  statuses: string[]
}

export function usePurgeTerminalJobs() {
  const queryClient = useQueryClient()
  return useMutation<RuntimeTerminalJobPurgeResult, unknown, { olderThanHours?: number }>({
    mutationFn: async ({ olderThanHours = 0 } = {}) => {
      const { data } = await apiClient.post<RuntimeTerminalJobPurgeResult>(
        `/agents/runtime/terminal-jobs/purge?older_than_hours=${olderThanHours}`,
      )
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents', 'runtime', 'topology'] })
      queryClient.invalidateQueries({ queryKey: ['agents', 'runtime', 'policy-events'] })
    },
  })
}
