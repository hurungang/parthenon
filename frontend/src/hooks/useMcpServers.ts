import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type { McpServer, McpSession, McpTool, SyncResult, ToolPermission } from '../types'

const MCP_SERVERS_KEY = ['mcp', 'servers']

export function useMcpServers() {
  return useQuery<McpServer[]>({
    queryKey: MCP_SERVERS_KEY,
    queryFn: async () => {
      const { data } = await apiClient.get<McpServer[]>('/mcp/servers')
      return data
    },
  })
}

export function useMcpServer(serverId: string) {
  return useQuery<McpServer>({
    queryKey: ['mcp', 'servers', serverId],
    queryFn: async () => {
      const { data } = await apiClient.get<McpServer>(`/mcp/servers/${serverId}`)
      return data
    },
    enabled: !!serverId,
  })
}

export function useServerTools(serverId: string) {
  return useQuery<McpTool[]>({
    queryKey: ['mcp', 'servers', serverId, 'tools'],
    queryFn: async () => {
      const { data } = await apiClient.get<McpTool[]>(`/mcp/servers/${serverId}/tools`)
      return data
    },
    enabled: !!serverId,
  })
}

export function useServerSessions(serverId: string) {
  return useQuery<McpSession[]>({
    queryKey: ['mcp', 'servers', serverId, 'sessions'],
    queryFn: async () => {
      const { data } = await apiClient.get<McpSession[]>(`/mcp/servers/${serverId}/sessions`)
      return data
    },
    enabled: !!serverId,
  })
}

export function useSyncServer() {
  const queryClient = useQueryClient()
  return useMutation<SyncResult, Error, string>({
    mutationFn: async (serverId) => {
      const { data } = await apiClient.post<SyncResult>(`/mcp/servers/${serverId}/sync`)
      return data
    },
    onSuccess: (_data, serverId) => {
      void queryClient.invalidateQueries({ queryKey: ['mcp', 'servers', serverId, 'tools'] })
      void queryClient.invalidateQueries({ queryKey: MCP_SERVERS_KEY })
    },
  })
}

export function useToolPermissions(toolId: string) {
  return useQuery<ToolPermission[]>({
    queryKey: ['mcp', 'tools', toolId, 'permissions'],
    queryFn: async () => {
      const { data } = await apiClient.get<ToolPermission[]>(`/mcp/tools/${toolId}/permissions`)
      return data
    },
    enabled: !!toolId,
  })
}
