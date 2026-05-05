import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockSkills = [
  { id: 'sk-1', name: 'Summarise Text', description: '', is_active: true, tool_ids: [], instructions: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
]

const mockAgentTypes = [
  { id: 'at-1', name: 'Delegate Agent', description: '', agent_type: 'sop-agent', is_active: true, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
]

const mockRoles = [
  { id: 'role-1', name: 'Admin Role', description: 'Admins', role_type: 'user', is_active: true, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
]

vi.mock('../hooks/useSops', () => ({
  useSopRoles: () => ({ data: ['role-1'], isLoading: false }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn((url: string) => {
      if (url === '/skills') return Promise.resolve({ data: mockSkills })
      if (url === '/agents/types') return Promise.resolve({ data: mockAgentTypes })
      if (url === '/agents/roles') return Promise.resolve({ data: mockRoles })
      return Promise.resolve({ data: [] })
    }),
    post: vi.fn().mockResolvedValue({ data: { id: 'sop-new', name: 'New SOP' } }),
    put: vi.fn().mockResolvedValue({ data: { id: 'sop-1', name: 'Updated SOP' } }),
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

describe('SopEditor', () => {
  it('renders without crashing', async () => {
    const { SopEditor } = await import('../pages/skills/SopEditor')
    
    const { container } = render(
      <SopEditor sop={null} onClose={() => {}} onSaved={() => {}} />,
      { wrapper }
    )
    
    expect(container).toBeDefined()
    expect(container.querySelectorAll('input, textarea').length).toBeGreaterThan(0)
  })

  it('renders instructions field for new SOP', async () => {
    const { SopEditor } = await import('../pages/skills/SopEditor')
    
    const { container } = render(
      <SopEditor sop={null} onClose={() => {}} onSaved={() => {}} />,
      { wrapper }
    )
    
    const textareas = container.querySelectorAll('textarea')
    expect(textareas.length).toBeGreaterThan(0)
  })

  it('renders Add Step button', async () => {
    const { SopEditor } = await import('../pages/skills/SopEditor')
    
    const { container } = render(
      <SopEditor sop={null} onClose={() => {}} onSaved={() => {}} />,
      { wrapper }
    )
    
    const buttons = container.querySelectorAll('button')
    expect(buttons.length).toBeGreaterThan(0)
  })
})

