import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type {
  AgentDataType,
  DataTypeCreate,
  DataTypeUpdate,
  DataTypeListResponse,
  ReferencingAgentType,
} from '../types'

const DATA_TYPES_KEY = ['data-types'] as const

export interface DataTypeQueryParams {
  page?: number
  page_size?: number
  search?: string
}

/**
 * React Query hook: paginated data type list.
 * Calls GET /api/v1/data-types with pagination and optional search params.
 */
export function useDataTypes(params?: DataTypeQueryParams) {
  return useQuery<DataTypeListResponse>({
    queryKey: [...DATA_TYPES_KEY, params ?? {}],
    queryFn: async () => {
      const queryParams: Record<string, string | number> = {}
      if (params?.page !== undefined) queryParams.page = params.page
      if (params?.page_size !== undefined) queryParams.page_size = params.page_size
      if (params?.search) queryParams.search = params.search
      const { data } = await apiClient.get<DataTypeListResponse>('/data-types', {
        params: queryParams,
      })
      return data
    },
  })
}

/**
 * React Query hook: data types with usage/enrichment info.
 * Calls GET /api/v1/data-types?usage=true.
 * Used by delete-guard UI to show referencing agent types.
 */
export function useDataTypesWithUsage() {
  return useQuery<DataTypeListResponse>({
    queryKey: [...DATA_TYPES_KEY, 'usage'],
    queryFn: async () => {
      const { data } = await apiClient.get<DataTypeListResponse>('/data-types', {
        params: { usage: true },
      })
      return data
    },
  })
}

/**
 * React Query hook: fetch a single data type by ID.
 */
export function useDataType(id: string) {
  return useQuery<AgentDataType>({
    queryKey: [...DATA_TYPES_KEY, id],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentDataType>(`/data-types/${id}`)
      return data
    },
    enabled: !!id,
  })
}

/**
 * React Query mutation: create a new data type.
 * Invalidates the data-types list query on success.
 */
export function useCreateDataType() {
  const queryClient = useQueryClient()
  return useMutation<AgentDataType, Error, DataTypeCreate>({
    mutationFn: async (payload) => {
      const { data } = await apiClient.post<AgentDataType>('/data-types', payload)
      return data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: DATA_TYPES_KEY })
    },
  })
}

/**
 * React Query mutation: update an existing data type.
 * Invalidates the data-types list and single-item queries on success.
 */
export function useUpdateDataType() {
  const queryClient = useQueryClient()
  return useMutation<AgentDataType, Error, { id: string; payload: DataTypeUpdate }>({
    mutationFn: async ({ id, payload }) => {
      const { data } = await apiClient.put<AgentDataType>(`/data-types/${id}`, payload)
      return data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: DATA_TYPES_KEY })
    },
  })
}

/**
 * React Query mutation: delete a data type.
 * Invalidates the data-types list and usage queries on success.
 */
export function useDeleteDataType() {
  const queryClient = useQueryClient()
  return useMutation<void, Error, string>({
    mutationFn: async (id) => {
      await apiClient.delete(`/data-types/${id}`)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: DATA_TYPES_KEY })
      void queryClient.invalidateQueries({ queryKey: [...DATA_TYPES_KEY, 'usage'] })
    },
  })
}

/**
 * Fetches usage info for a single data type (referencing agent types).
 * Can be used by the delete confirmation flow.
 */
export async function fetchDataTypeUsage(id: string): Promise<ReferencingAgentType[]> {
  const { data } = await apiClient.get<DataTypeListResponse>('/data-types', {
    params: { usage: true },
  })
  return data.referencing_agent_types?.[id] ?? []
}
