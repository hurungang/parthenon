/**
 * React Query hooks for the Software 3.0 script registry APIs
 * (/api/v1/scripts). Permission-gated server-side by agent::scripts.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type {
  FallbackEventListResponse,
  HealthSummaryResponse,
  LifecycleTransitionRequest,
  RepairAttemptListResponse,
  ScriptDefinitionListResponse,
  ScriptLifecycleStatus,
  ScriptVersionResponse,
  VerificationRunListResponse,
} from '../types/scripts'

const SCRIPTS_KEY = ['scripts'] as const

export interface ScriptQueryParams {
  agent_type_id?: string
  lifecycle_status?: ScriptLifecycleStatus
  health_status?: string
}

export function useScripts(params?: ScriptQueryParams) {
  return useQuery<ScriptDefinitionListResponse>({
    queryKey: [...SCRIPTS_KEY, params ?? {}],
    queryFn: async () => {
      const queryParams: Record<string, string> = {}
      if (params?.agent_type_id) queryParams.agent_type_id = params.agent_type_id
      if (params?.lifecycle_status) queryParams.lifecycle_status = params.lifecycle_status
      if (params?.health_status) queryParams.health_status = params.health_status
      const { data } = await apiClient.get<ScriptDefinitionListResponse>('/scripts', {
        params: queryParams,
      })
      return data
    },
  })
}

export function useScriptVersions(definitionId: string | null) {
  return useQuery<ScriptVersionResponse[]>({
    queryKey: [...SCRIPTS_KEY, 'versions', definitionId],
    enabled: !!definitionId,
    queryFn: async () => {
      const { data } = await apiClient.get<ScriptVersionResponse[]>(
        `/scripts/${definitionId}/versions`,
      )
      return data
    },
  })
}

export function useScriptVerifications(definitionId: string | null) {
  return useQuery<VerificationRunListResponse>({
    queryKey: [...SCRIPTS_KEY, 'verifications', definitionId],
    enabled: !!definitionId,
    queryFn: async () => {
      const { data } = await apiClient.get<VerificationRunListResponse>(
        `/scripts/${definitionId}/verifications`,
      )
      return data
    },
  })
}

export function useScriptFallbacks(definitionId: string | null) {
  return useQuery<FallbackEventListResponse>({
    queryKey: [...SCRIPTS_KEY, 'fallbacks', definitionId],
    enabled: !!definitionId,
    queryFn: async () => {
      const { data } = await apiClient.get<FallbackEventListResponse>(
        `/scripts/${definitionId}/fallbacks`,
      )
      return data
    },
  })
}

export function useScriptHealth(definitionId: string | null) {
  return useQuery<HealthSummaryResponse>({
    queryKey: [...SCRIPTS_KEY, 'health', definitionId],
    enabled: !!definitionId,
    queryFn: async () => {
      const { data } = await apiClient.get<HealthSummaryResponse>(
        `/scripts/${definitionId}/health`,
      )
      return data
    },
  })
}

export function useScriptRepairs(definitionId: string | null) {
  return useQuery<RepairAttemptListResponse>({
    queryKey: [...SCRIPTS_KEY, 'repairs', definitionId],
    enabled: !!definitionId,
    queryFn: async () => {
      const { data } = await apiClient.get<RepairAttemptListResponse>(
        `/scripts/${definitionId}/repairs`,
      )
      return data
    },
  })
}

function useLifecycleMutation(invalidateDefinitionId: string | null) {
  void invalidateDefinitionId
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      definitionId,
      versionId,
      body,
    }: {
      definitionId: string
      versionId: string
      body: LifecycleTransitionRequest
    }) => {
      const { data } = await apiClient.post<ScriptVersionResponse>(
        `/scripts/${definitionId}/versions/${versionId}/promote`,
        body,
      )
      return data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: SCRIPTS_KEY })
      if (invalidateDefinitionId) {
        void queryClient.invalidateQueries({
          queryKey: [...SCRIPTS_KEY, 'versions', invalidateDefinitionId],
        })
      }
    },
  })
}

/** Promote (or demote via target_status) a script version. */
export function usePromoteScriptVersion(definitionId: string | null) {
  return useLifecycleMutation(definitionId)
}

export function useRetireScriptVersion(definitionId: string | null) {
  const queryClient = useQueryClient()
  void definitionId
  return useMutation({
    mutationFn: async ({
      definitionId: defId,
      versionId,
    }: {
      definitionId: string
      versionId: string
    }) => {
      const { data } = await apiClient.post<ScriptVersionResponse>(
        `/scripts/${defId}/versions/${versionId}/retire`,
      )
      return data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: SCRIPTS_KEY })
    },
  })
}
