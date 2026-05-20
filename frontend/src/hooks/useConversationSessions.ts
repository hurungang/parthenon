import { useQueryClient, useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import apiClient from '../api/apiClient'
import type { ConversationSession, ConversationSessionCreate } from '../types'

const conversationsKey = (agentTypeId: string) => ['conversations', agentTypeId]

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
