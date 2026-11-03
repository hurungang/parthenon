import { useQueryClient, useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import apiClient from '../api/apiClient'
import type { ConversationSession, ConversationSessionCreate } from '../types'

const conversationsKey = (agentTypeId: string) => ['conversations', agentTypeId]

/**
 * FIX-20261101-120618 Work Item 1 — paginated sessions listing params/shape.
 * Mirrors the backend GET /conversations/sessions contract.
 */
export interface ConversationSessionsPageParams {
  agentTypeId: string
  status: 'active' | 'ended' | 'all'
  dateFrom?: string // ISO
  dateTo?: string // ISO
  page: number
  pageSize: number
  allTime?: boolean
}

export interface ConversationSessionsPage {
  items: ConversationSession[]
  total: number
  page: number
  page_size: number
  default_window_days: number
}

/**
 * Paginated / filterable sessions query (time desc, total count, default
 * window enforced server-side).
 */
export function useConversationSessionsPage(params: ConversationSessionsPageParams) {
  const { agentTypeId, status, dateFrom, dateTo, page, pageSize, allTime } = params
  return useQuery<ConversationSessionsPage>({
    queryKey: ['conversations-page', agentTypeId, status, dateFrom ?? null, dateTo ?? null, page, pageSize, allTime ?? false],
    queryFn: async () => {
      const qs = new URLSearchParams({
        agent_type_id: agentTypeId,
        status,
        page: String(page),
        page_size: String(pageSize),
      })
      if (dateFrom) qs.set('date_from', dateFrom)
      if (dateTo) qs.set('date_to', dateTo)
      if (allTime) qs.set('all_time', 'true')
      const { data } = await apiClient.get<ConversationSessionsPage>(
        `/conversations/sessions?${qs.toString()}`,
      )
      return data
    },
    enabled: !!agentTypeId,
  })
}

/**
 * Fetch all conversation sessions for a given agent type, sorted by updated_at DESC.
 */
export function useConversationSessions(agentTypeId: string) {
  return useQuery<ConversationSession[]>({
    queryKey: conversationsKey(agentTypeId),
    queryFn: async () => {
      const { data } = await apiClient.get<ConversationSession[]>(
        `/conversations?agent_type_id=${agentTypeId}`,
      )
      return data
    },
    enabled: !!agentTypeId,
  })
}

/**
 * Mutation to end (close) a conversation session.
 * Invalidates the sessions list for the associated agent type.
 */
export function useEndConversationSession(agentTypeId: string) {
  const queryClient = useQueryClient()
  return useMutation<ConversationSession, Error, string>({
    mutationFn: async (sessionId) => {
      const { data } = await apiClient.post<ConversationSession>(
        `/conversations/${sessionId}/end`,
      )
      return data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: conversationsKey(agentTypeId) })
    },
  })
}

/**
 * Mutation to archive a conversation session.
 * Invalidates the sessions list for the associated agent type.
 */
export function useArchiveConversationSession(agentTypeId: string) {
  const queryClient = useQueryClient()
  return useMutation<ConversationSession, Error, string>({
    mutationFn: async (sessionId) => {
      const { data } = await apiClient.post<ConversationSession>(
        `/conversations/${sessionId}/archive`,
      )
      return data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: conversationsKey(agentTypeId) })
    },
  })
}

/**
 * Mutation to create a new conversation session.
 * Invalidates the sessions list and navigates to the new session's chat page.
 */
export function useCreateConversationSession(agentTypeId: string) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  return useMutation<ConversationSession, Error, void>({
    mutationFn: async () => {
      const body: ConversationSessionCreate = { agent_type_id: agentTypeId }
      const { data } = await apiClient.post<ConversationSession>('/conversations', body)
      return data
    },
    onSuccess: (session) => {
      void queryClient.invalidateQueries({ queryKey: conversationsKey(agentTypeId) })
      navigate(`/agents/${agentTypeId}/chat/${session.id}`)
    },
  })
}
