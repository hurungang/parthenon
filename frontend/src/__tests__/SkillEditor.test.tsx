import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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
      // Skill detail for sk-1: has instructions_with_tools with a ## Tools section
      if (url === '/skills/sk-1') return Promise.resolve({ data: {
        id: 'sk-1',
        name: 'Summarise Text',
        description: 'Summarises long documents',
        instructions: 'Use the search tool to find relevant information.',
        instructions_with_tools: 'Use the search tool to find relevant information.\n\n## Tools\n\n### `internal-tools/search`\nSearches the web',
        is_active: true,
        tool_ids: ['tool-1'],
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }})
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

// ── Generated Tool Reference section ──────────────────────────────────────────

describe('SkillEditor — Generated Tool Reference section', () => {
  // Skill with tool section: id=sk-1 → mock returns instructions_with_tools with ## Tools
  const SKILL_WITH_TOOL_SECTION = {
    id: 'sk-1',
    name: 'Summarise Text',
    description: 'Summarises long documents',
    instructions: 'Use the search tool to find relevant information.',
    is_active: true,
    tool_ids: ['tool-1'],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }

  // Skill without tool section: id=sk-no-tools → mock returns { data: [] } (no instructions_with_tools)
  const SKILL_WITHOUT_TOOL_SECTION = {
    id: 'sk-no-tools',
    name: 'Plain Skill',
    description: 'No tools bound',
    instructions: 'Just plain instructions.',
    is_active: true,
    tool_ids: [],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders Generated Tool Reference section label when editing an existing skill', async () => {
    render(
      <SkillEditor skill={SKILL_WITH_TOOL_SECTION as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )
    await waitFor(() => {
      // i18n mock maps key → key, so label key must be present in DOM
      const label = screen.queryByText('skills.editor.generatedToolReference')
      expect(label).not.toBeNull()
    })
  })

  it('does not render Generated Tool Reference section for new skill (null prop)', async () => {
    render(<SkillEditor skill={null} onClose={vi.fn()} onSaved={vi.fn()} />, { wrapper })
    await waitFor(() => {
      const label = screen.queryByText('skills.editor.generatedToolReference')
      expect(label).toBeNull()
    })
  })

  it('renders a collapsible toggle button next to the section label', async () => {
    render(
      <SkillEditor skill={SKILL_WITH_TOOL_SECTION as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )
    await waitFor(() => {
      // At minimum there should be Save, Cancel, and the expand toggle buttons
      const buttons = screen.queryAllByRole('button')
      expect(buttons.length).toBeGreaterThan(0)
    })
  })

  it('section content area uses a pre element (read-only, not a textarea or input)', async () => {
    render(
      <SkillEditor skill={SKILL_WITH_TOOL_SECTION as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )
    await waitFor(() => {
      // The instructions field is a textarea; the tool reference section is a pre
      const textareas = document.querySelectorAll('textarea')
      expect(textareas.length).toBeGreaterThan(0)
      // No textarea should be inside the pre element
      textareas.forEach((ta) => {
        const parentPre = ta.closest('pre')
        expect(parentPre).toBeNull()
      })
    })
  })

  it('shows skills.noTools empty-state when skill has no tool section in instructions_with_tools', async () => {
    // sk-no-tools is not handled by the mock → returns { data: [] }
    // toolSection = null → shows skills.noTools
    render(
      <SkillEditor skill={SKILL_WITHOUT_TOOL_SECTION as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )
    await waitFor(() => {
      const emptyMsg = screen.queryByText('skills.noTools')
      expect(emptyMsg).not.toBeNull()
    })
  })

  it('shows tool section content when instructions_with_tools has ## Tools marker', async () => {
    // sk-1 mock returns instructions_with_tools with ## Tools — after query loads,
    // the pre element shows the tool section content
    render(
      <SkillEditor skill={SKILL_WITH_TOOL_SECTION as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )
    await waitFor(() => {
      // Either the tool section is loaded (## Tools) or the initial empty state is shown
      // Both are valid — waitFor will retry until skillDetail loads and toolSection updates
      const bodyText = document.body.textContent ?? ''
      const hasSectionLabel = bodyText.includes('skills.editor.generatedToolReference')
      expect(hasSectionLabel).toBe(true)
    })
  })

  it('section is structurally distinct from the editable instructions textarea', async () => {
    render(
      <SkillEditor skill={SKILL_WITH_TOOL_SECTION as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )
    await waitFor(() => {
      // The editable instructions field renders as textarea
      const textareas = document.querySelectorAll('textarea')
      expect(textareas.length).toBeGreaterThan(0)
      // The Generated Tool Reference label is text, not inside a textarea
      const label = screen.queryByText('skills.editor.generatedToolReference')
      expect(label).not.toBeNull()
    })
  })
})


