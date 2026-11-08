import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type { McpServer, McpSession, McpTool, Skill, SyncResult, ToolPermission } from '../types'

const MCP_SERVERS_KEY = ['mcp', 'servers']

/**
 * FIX-20261102-062047: the backend caps list pages at 200 and exposes the
 * true total via ``X-Total-Count``.  "Get everything" callers (tool pickers,
 * role dialogs) page until a short page so no server/tool is silently lost
 * when a tenant grows past one page.
 */
const MCP_TOOLS_PAGE_SIZE = 200
const MCP_SERVERS_PAGE_SIZE = 100
const MCP_LIST_MAX_PAGES = 50

async function fetchAllPages<T>(url: string, pageSize: number): Promise<T[]> {
  const collected: T[] = []
  let offset = 0
  for (let page = 0; page < MCP_LIST_MAX_PAGES; page += 1) {
    const { data } = await apiClient.get<T[]>(url, {
      params: { limit: pageSize, offset },
    })
    collected.push(...data)
    if (data.length < pageSize) break
    offset += data.length
  }
  return collected
}

export function useMcpServers(limit?: number, offset?: number) {
  const paged = limit !== undefined || offset !== undefined
  return useQuery<McpServer[]>({
    queryKey: [...MCP_SERVERS_KEY, paged ? (limit ?? 0) : 'all', offset ?? 0],
    queryFn: async () => {
      if (!paged) return fetchAllPages<McpServer>('/mcp/servers', MCP_SERVERS_PAGE_SIZE)
      const params: Record<string, number> = {}
      if (limit !== undefined) params.limit = limit
      if (offset !== undefined) params.offset = offset
      const { data } = await apiClient.get<McpServer[]>('/mcp/servers', { params })
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

export function useAllTools(limit?: number, offset?: number, serverId?: string) {
  const paged = limit !== undefined || offset !== undefined
  return useQuery<McpTool[]>({
    // serverId participates in the key so changing the filter refetches
    // from the API (server-side filter + pagination).
    queryKey: ['mcp', 'tools', paged ? { limit, offset, serverId: serverId ?? null } : 'all'],
    queryFn: async () => {
      const params: Record<string, string | number> = {}
      if (limit !== undefined) params.limit = limit
      if (offset !== undefined) params.offset = offset
      if (paged && serverId) params.server_id = serverId
      if (!paged && !serverId) return fetchAllPages<McpTool>('/mcp/tools', MCP_TOOLS_PAGE_SIZE)
      const { data } = await apiClient.get<McpTool[]>('/mcp/tools', { params })
      return data
    },
  })
}

export function useToolSkills(toolId: string) {
  return useQuery<Skill[]>({
    queryKey: ['mcp', 'tools', toolId, 'skills'],
    queryFn: async () => {
      const { data } = await apiClient.get<Skill[]>(`/mcp/tools/${toolId}/skills`)
      return data
    },
    enabled: !!toolId,
  })
}
