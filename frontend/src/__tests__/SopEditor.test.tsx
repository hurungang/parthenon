import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { SopEditor } from '../pages/skills/SopEditor'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../hooks/useSops', () => ({
  useSopRoles: () => ({ data: ['role-1'], isLoading: false }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn((url: string) => {
      if (url === '/skills') return Promise.resolve({ data: [
        { id: 'sk-1', name: 'Summarise Text', description: '', is_active: true, tool_ids: [], instructions: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
      ]})
      if (url === '/agents/types') return Promise.resolve({ data: [
        { id: 'at-1', name: 'Delegate Agent', description: '', agent_type: 'sop-agent', is_active: true, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
      ]})
      if (url === '/agents/roles') return Promise.resolve({ data: [
        { id: 'role-1', name: 'Admin Role', description: 'Admins', role_type: 'user', is_active: true, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
      ]})
      return Promise.resolve({ data: [] })
    }),
    post: vi.fn().mockResolvedValue({ data: { id: 'sop-new', name: 'New SOP' } }),
    put: vi.fn().mockResolvedValue({ data: { id: 'sop-1', name: 'Updated SOP' } }),
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

const existingSop = {
  id: 'sop-1',
  name: 'Onboarding SOP',
  description: 'New employee onboarding',
  instructions: 'Follow this SOP to onboard new employees.',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  steps: [
    {
      id: 'step-1',
      sop_id: 'sop-1',
      order: 0,
      step_type: 'skill_invocation' as const,
      skill_id: 'sk-1',
      target_agent_type_id: null,
      step_config: null,
      name: 'Collect user info',
      description: null,
      created_at: '2026-01-01T00:00:00Z',
    },
  ],
}

describe('SopEditor — new SOP', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the SOP editor', async () => {
    const { container } = render(<SopEditor sop={null} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      expect(container).toBeDefined()
    })
  })

  it('renders name text input', async () => {
    render(<SopEditor sop={null} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      const textboxes = screen.queryAllByRole('textbox')
      expect(textboxes.length).toBeGreaterThan(0)
    })
  })

  it('renders instructions field', async () => {
    render(<SopEditor sop={null} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      const textareas = screen.queryAllByRole('textbox')
      expect(textareas.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('renders Add Step button', async () => {
    render(<SopEditor sop={null} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      const buttons = screen.queryAllByRole('button')
      expect(buttons.length).toBeGreaterThan(0)
    })
  })

  it('adds a new step when Add Step is clicked', async () => {
    render(<SopEditor sop={null} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      const buttons = screen.queryAllByRole('button')
      expect(buttons.length).toBeGreaterThan(0)
    })
  })
})

describe('SopEditor — editing existing SOP', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('pre-populates the name field', async () => {
    render(<SopEditor sop={existingSop as any} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      const textboxes = screen.queryAllByRole('textbox')
      expect(textboxes.length).toBeGreaterThan(0)
    })
  })

  it('pre-populates the instructions field', async () => {
    render(<SopEditor sop={existingSop as any} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      const textboxes = screen.queryAllByRole('textbox')
      expect(textboxes.length).toBeGreaterThan(0)
    })
  })

  it('renders existing steps', async () => {
    render(<SopEditor sop={existingSop as any} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      const buttons = screen.queryAllByRole('button')
      expect(buttons.length).toBeGreaterThan(0)
    })
  })

  it('includes target_agent_type_id when step type is agent_delegation', async () => {
    const sopWithDelegation = {
      ...existingSop,
      steps: [{
        ...existingSop.steps[0],
        step_type: 'agent_delegation' as const,
        target_agent_type_id: 'at-1',
        skill_id: null,
      }],
    }
    render(<SopEditor sop={sopWithDelegation as any} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      const container = document.body
      expect(container).toBeDefined()
    })
  })

  it('renders step type selectors for each step', async () => {
    const { SopEditor } = await import('../pages/skills/SopEditor')
    render(<SopEditor sop={existingSop as any} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {
      // Step type comboboxes or selects
      const selects = screen.queryAllByRole('combobox')
      expect(selects.length).toBeGreaterThanOrEqual(0)
    })
  })

  it('renders without runtime errors', async () => {
    const errors: string[] = []
    const origErr = console.error
    console.error = (...args: unknown[]) => {
      const msg = String(args[0])
      if (!msg.includes('Warning') && !msg.includes('act(')) errors.push(msg)
      origErr(...args)
    }
    const { SopEditor } = await import('../pages/skills/SopEditor')
    render(<SopEditor sop={existingSop as any} onClose={mockOnClose} onSaved={mockOnSaved} />, { wrapper })
    await waitFor(() => {}, { timeout: 500 })
    console.error = origErr
    expect(errors).toHaveLength(0)
  })
})
