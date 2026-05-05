import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockTools = [
  { id: 'tool-1', server_id: 'srv-1', name: 'search', original_name: 'search', description: 'Searches', is_active: true, input_schema: {}, server_slug: 'internal-tools', server_name: 'Internal Tools', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
]

const mockServers = [
  { id: 'srv-1', name: 'Internal Tools', slug: 'internal-tools', base_url: 'http://mcp.internal', status: 'active' },
]

const mockRoles = [
  { id: 'role-1', name: 'Admin Role', description: 'Admins', role_type: 'user', is_active: true, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
]

vi.mock('../hooks/useMcpServers', () => ({
  useAllTools: () => ({ data: mockTools, isLoading: false }),
  useMcpServers: () => ({ data: mockServers, isLoading: false }),
}))

vi.mock('../hooks/useSkills', () => ({
  useSkillRoles: () => ({ data: ['role-1'], isLoading: false }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn((url: string) => {
      console.log(`[TEST] apiClient.get called for: ${url}`)
      return Promise.resolve({ data: mockRoles })
    }),
    post: vi.fn().mockResolvedValue({ data: { id: 'sk-new', name: 'New Skill' } }),
    put: vi.fn().mockResolvedValue({ data: { id: 'sk-1', name: 'Updated Skill' } }),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: Infinity,
      },
    },
  })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('SkillEditor — render with no data', () => {
  it('renders with null skill', async () => {
    console.log('[TEST] Starting test')
    const { SkillEditor } = await import('../pages/skills/SkillEditor')
    console.log('[TEST] Component imported')
    
    const { container } = render(
      <SkillEditor skill={null} onClose={() => {}} onSaved={() => {}} />,
      { wrapper }
    )
    
    console.log('[TEST] Component rendered')
    expect(container).toBeDefined()
  })

  it('second test with same component', async () => {
    console.log('[TEST2] Starting test 2')
    const { SkillEditor } = await import('../pages/skills/SkillEditor')
    console.log('[TEST2] Component imported')
    
    const { container } = render(
      <SkillEditor skill={null} onClose={() => {}} onSaved={() => {}} />,
      { wrapper }
    )
    
    console.log('[TEST2] Component rendered')
    expect(container).toBeDefined()
  })
})
