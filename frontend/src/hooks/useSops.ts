import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/apiClient'

export function useSopRoles(sopId: string) {
  return useQuery<string[]>({
    queryKey: ['sops', sopId, 'roles'],
    queryFn: async () => {
      const { data } = await apiClient.get<string[]>(`/sops/${sopId}/roles`)
      return data
    },
    enabled: !!sopId,
  })
}

export function useSetSopRoles() {
  const queryClient = useQueryClient()
  return useMutation<string[], Error, { sopId: string; role_ids: string[] }>({
    mutationFn: async ({ sopId, role_ids }) => {
      const { data } = await apiClient.put<string[]>(`/sops/${sopId}/roles`, { role_ids })
      return data
    },
    onSuccess: (_data, { sopId }) => {
      void queryClient.invalidateQueries({ queryKey: ['sops', sopId, 'roles'] })
    },
  })
}
