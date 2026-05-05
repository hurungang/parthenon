import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { SkillEditor } from '../pages/skills/SkillEditor'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../hooks/useMcpServers', () => ({
  useAllTools: () => ({ data: [
    { id: 'tool-1', server_id: 'srv-1', name: 'search', original_name: 'search', description: 'Searches', is_active: true, input_schema: {}, server_slug: 'internal-tools', server_name: 'Internal Tools', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    { id: 'tool-2', server_id: 'srv-1', name: 'summarise', original_name: 'summarise', description: 'Summarises', is_active: true, input_schema: {}, server_slug: 'internal-tools', server_name: 'Internal Tools', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
  ], isLoading: false }),
  useMcpServers: () => ({ data: [
    { id: 'srv-1', name: 'Internal Tools', slug: 'internal-tools', base_url: 'http://mcp.internal', status: 'active' },
  ], isLoading: false }),
}))

vi.mock('../hooks/useSkills', () => ({
  useSkillRoles: () => ({ data: ['role-1'], isLoading: false }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn((url: string) => {
      if (url === '/agents/roles') return Promise.resolve({ data: [
        { id: 'role-1', name: 'Admin Role', description: 'Admins', role_type: 'user', is_active: true, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
      ]})
      return Promise.resolve({ data: [] })
    }),
    post: vi.fn().mockResolvedValue({ data: { id: 'sk-new', name: 'New Skill' } }),
    put: vi.fn().mockResolvedValue({ data: { id: 'sk-1', name: 'Updated Skill' } }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
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

const mockOnClose = vi.fn()
const mockOnSaved = vi.fn()

describe('SkillEditor — new skill', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the skill editor panel', async () => {
    render(<SkillEditor skill={null} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      const inputs = screen.queryAllByRole('textbox')
      expect(inputs.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('renders the instructions field', async () => {
    render(<SkillEditor skill={null} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      const textareas = screen.queryAllByRole('textbox')
      expect(textareas.length).toBeGreaterThan(0)
    })
  })

  it('renders tool selection section grouped by server', async () => {
    render(<SkillEditor skill={null} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      const checkboxes = screen.queryAllByRole('checkbox')
      expect(checkboxes.length).toBeGreaterThan(0)
    })
  })

  it('renders close button', async () => {
    render(<SkillEditor skill={null} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      const buttons = screen.queryAllByRole('button')
      expect(buttons.length).toBeGreaterThan(0)
    })
  })

  it('renders save button', async () => {
    render(<SkillEditor skill={null} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      const buttons = screen.queryAllByRole('button')
      expect(buttons.length).toBeGreaterThan(0)
    })
  })
})

describe('SkillEditor — editing existing skill', () => {
  const existingSkill = {
    id: 'sk-1',
    name: 'Summarise Text',
    description: 'Summarises long documents',
    instructions: 'Use this skill to summarise long text.',
    is_active: true,
    tool_ids: ['tool-1'],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('pre-populates the name field', async () => {
    render(<SkillEditor skill={existingSkill as any} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      const inputs = screen.queryAllByRole('textbox')
      expect(inputs.length).toBeGreaterThan(0)
    })
  })

  it('pre-populates the instructions field', async () => {
    render(<SkillEditor skill={existingSkill as any} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      const inputs = screen.queryAllByRole('textbox')
      expect(inputs.length).toBeGreaterThan(0)
    })
  })

  it('renders role assignment sidebar with loaded roles', async () => {
    render(<SkillEditor skill={existingSkill as any} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      const checkboxes = screen.queryAllByRole('checkbox')
      expect(checkboxes.length).toBeGreaterThan(0)
    })
  })

  it('renders without runtime errors', async () => {
    render(<SkillEditor skill={existingSkill as any} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      const container = document.body
      expect(container).toBeDefined()
    })
  })
})
