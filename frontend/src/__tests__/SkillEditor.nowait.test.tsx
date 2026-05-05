import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
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
    get: vi.fn().mockResolvedValue({ data: mockRoles }),
    post: vi.fn().mockResolvedValue({ data: { id: 'sk-new', name: 'New Skill' } }),
    put: vi.fn().mockResolvedValue({ data: { id: 'sk-1', name: 'Updated Skill' } }),
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
  it('renders without waitFor', async () => {
    const { SkillEditor } = await import('../pages/skills/SkillEditor')
    
    const { container } = render(
      <SkillEditor skill={null} onClose={() => {}} onSaved={() => {}} />,
      { wrapper }
    )
    
    // NO waitFor - just check immediately
    expect(container).toBeDefined()
    
    // Check if there's an input field
    const inputs = container.querySelectorAll('input, textarea')
    console.log(`[TEST] Found ${inputs.length} input/textarea elements`)
    expect(inputs.length).toBeGreaterThan(0)
  })
  
  it('renders with instructions field', async () => {
    const { SkillEditor } = await import('../pages/skills/SkillEditor')
    
    render(
      <SkillEditor skill={null} onClose={() => {}} onSaved={() => {}} />,
      { wrapper }
    )
    
    // Check all textboxes immediately
    const textboxes = screen.queryAllByRole('textbox')
    console.log(`[TEST] Found ${textboxes.length} textbox elements`)
    expect(textboxes.length).toBeGreaterThan(0)
  })
})
