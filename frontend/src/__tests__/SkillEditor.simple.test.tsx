import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// CRITICAL: Inline all mock data inside vi.mock() to avoid hoisting issues
vi.mock('../hooks/useMcpServers', () => ({
  useAllTools: () => ({ 
    data: [
      { id: 'tool-1', server_id: 'srv-1', name: 'search', original_name: 'search', description: 'Searches', is_active: true, input_schema: {}, server_slug: 'internal-tools', server_name: 'Internal Tools', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    ], 
    isLoading: false 
  }),
  useMcpServers: () => ({ 
    data: [
      { id: 'srv-1', name: 'Internal Tools', slug: 'internal-tools', base_url: 'http://mcp.internal', status: 'active' },
    ], 
    isLoading: false 
  }),
}))

vi.mock('../hooks/useSkills', () => ({
  useSkillRoles: () => ({ data: ['role-1'], isLoading: false }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: () => Promise.resolve({ 
      data: [
        { id: 'role-1', name: 'Admin Role', description: 'Admins', role_type: 'user', is_active: true, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
      ] 
    }),
    post: () => Promise.resolve({ data: { id: 'sk-new', name: 'New Skill' } }),
    put: () => Promise.resolve({ data: { id: 'sk-1', name: 'Updated Skill' } }),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('SkillEditor', () => {
  it('renders without crashing', async () => {
    const { SkillEditor } = await import('../pages/skills/SkillEditor')
    
    const { container } = render(
      <SkillEditor skill={null} onClose={() => {}} onSaved={() => {}} />,
      { wrapper }
    )
    
    expect(container).toBeDefined()
    expect(container.querySelectorAll('input, textarea').length).toBeGreaterThan(0)
  })

  it('renders instructions field for new skill', async () => {
    const { SkillEditor } = await import('../pages/skills/SkillEditor')
    
    const { container } = render(
      <SkillEditor skill={null} onClose={() => {}} onSaved={() => {}} />,
      { wrapper }
    )
    
    const textareas = container.querySelectorAll('textarea')
    expect(textareas.length).toBeGreaterThan(0)
  })

  it('renders tool selection checkboxes', async () => {
    const { SkillEditor } = await import('../pages/skills/SkillEditor')
    
    const { container } = render(
      <SkillEditor skill={null} onClose={() => {}} onSaved={() => {}} />,
      { wrapper }
    )
    
    const checkboxes = container.querySelectorAll('input[type="checkbox"]')
    expect(checkboxes.length).toBeGreaterThan(0)
  })
})

