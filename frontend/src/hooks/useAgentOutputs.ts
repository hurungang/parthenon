import { useQuery, useMutation } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type {
  AgentOutputListResponse,
  AgentOutputQueryParams,
  AgentOutputExportParams,
} from '../types'

const AGENT_OUTPUTS_KEY = ['agent-outputs'] as const

/**
 * React Query hook: paginated agent outputs list with filters.
 * Calls GET /api/v1/agent-outputs with filter and pagination params.
 */
export function useAgentOutputs(params?: AgentOutputQueryParams) {
  return useQuery<AgentOutputListResponse>({
    queryKey: [...AGENT_OUTPUTS_KEY, params ?? {}],
    queryFn: async () => {
      const queryParams: Record<string, string | number> = {}
      if (params?.data_type_id) queryParams.data_type_id = params.data_type_id
      if (params?.agent_type_id) queryParams.agent_type_id = params.agent_type_id
      if (params?.date_from) queryParams.date_from = params.date_from
      if (params?.date_to) queryParams.date_to = params.date_to
      if (params?.page !== undefined) queryParams.page = params.page
      if (params?.page_size !== undefined) queryParams.page_size = params.page_size
      const { data } = await apiClient.get<AgentOutputListResponse>(
        '/agent-outputs',
        { params: queryParams },
      )
      return data
    },
  })
}

/**
 * React Query mutation: download CSV export of agent outputs.
 * Triggers a browser file download when successful.
 */
export function useExportAgentOutputs() {
  return useMutation<Blob, Error, AgentOutputExportParams>({
    mutationFn: async (filters) => {
      const queryParams: Record<string, string> = {}
      if (filters.data_type_id) queryParams.data_type_id = filters.data_type_id
      if (filters.agent_type_id) queryParams.agent_type_id = filters.agent_type_id
      if (filters.date_from) queryParams.date_from = filters.date_from
      if (filters.date_to) queryParams.date_to = filters.date_to
      const { data } = await apiClient.get<Blob>('/agent-outputs/export', {
        params: queryParams,
        responseType: 'blob',
      })
      return data
    },
    onSuccess: (data) => {
      // Trigger browser file download
      const url = window.URL.createObjectURL(data)
      const link = document.createElement('a')
      link.href = url
      const filename = `agent-outputs-${new Date().toISOString().slice(0, 10)}.csv`
      link.setAttribute('download', filename)
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)
    },
  })
}
