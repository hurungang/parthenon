import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/apiClient'

export function useSkillRoles(skillId: string) {
  return useQuery<string[]>({
    queryKey: ['skills', skillId, 'roles'],
    queryFn: async () => {
      const { data } = await apiClient.get<string[]>(`/skills/${skillId}/roles`)
      return data
    },
    enabled: !!skillId,
  })
}

export function useSetSkillRoles() {
  const queryClient = useQueryClient()
  return useMutation<string[], Error, { skillId: string; role_ids: string[] }>({
    mutationFn: async ({ skillId, role_ids }) => {
      const { data } = await apiClient.put<string[]>(`/skills/${skillId}/roles`, { role_ids })
      return data
    },
    onSuccess: (_data, { skillId }) => {
      void queryClient.invalidateQueries({ queryKey: ['skills', skillId, 'roles'] })
    },
  })
}
