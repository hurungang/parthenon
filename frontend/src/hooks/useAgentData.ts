import { useQuery } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type {
  AgentDataListResponse,
  AgentDataQueryParams,
} from '../types'

const AGENT_DATA_KEY = ['agent-data'] as const

export function useAgentData(params?: AgentDataQueryParams) {
  return useQuery<AgentDataListResponse>({
    queryKey: [...AGENT_DATA_KEY, params ?? {}],
    queryFn: async () => {
      const queryParams: Record<string, string | number> = {}
      if (params?.data_name) queryParams.data_name = params.data_name
      if (params?.agent_type_id) queryParams.agent_type_id = params.agent_type_id
      if (params?.session_id) queryParams.session_id = params.session_id
      if (params?.page !== undefined) queryParams.page = params.page
      if (params?.page_size !== undefined) queryParams.page_size = params.page_size
      const { data } = await apiClient.get<AgentDataListResponse>(
        '/agent-data',
        { params: queryParams },
      )
      return data
    },
  })
}
