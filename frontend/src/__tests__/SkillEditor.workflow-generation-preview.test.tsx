import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { SkillEditor } from '../pages/skills/SkillEditor'
import apiClient from '../api/apiClient'
import { useAllTools, useMcpServers } from '../hooks/useMcpServers'
import { useSkillRoles } from '../hooks/useSkills'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, vars?: Record<string, string>) => {
    if (k === 'skills.editor.workflowPreviewTitle') return `skills.editor.workflowPreviewTitle ${vars?.model ?? ''}`
    return k
  } }),
}))

vi.mock('../hooks/useMcpServers', () => ({
  useAllTools: vi.fn(),
  useMcpServers: vi.fn(),
}))

vi.mock('../hooks/useSkills', () => ({
  useSkillRoles: vi.fn(),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

const TOOLS = [
  { id: 'tool-1', server_id: 'srv-1', name: 'search', original_name: 'search', description: 'Search docs', input_schema: { type: 'object' } },
]
const SERVERS = [
  { id: 'srv-1', slug: 'internal', name: 'Internal', base_url: 'http://x', status: 'active' },
]
const SKILL_DETAIL = {
  id: 'sk-1',
  name: 'Skill One',
  description: 'desc',
  instructions: 'initial workflow',
  instructions_with_tools: 'initial workflow',
  is_active: true,
  tool_ids: ['tool-1'],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('SkillEditor workflow generation and preview', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useAllTools).mockReturnValue({ data: TOOLS } as any)
    vi.mocked(useMcpServers).mockReturnValue({ data: SERVERS } as any)
    vi.mocked(useSkillRoles).mockReturnValue({ data: [] } as any)
    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url === '/agents/roles') return Promise.resolve({ data: [] })
      if (url === '/skills/sk-1') return Promise.resolve({ data: SKILL_DETAIL })
      return Promise.resolve({ data: [] })
    })
  })

  afterEach(() => {
    vi.clearAllTimers()
  })

  it('generates workflow and updates the workflow field', async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: { workflow: 'generated workflow', model_id: 'gpt-4o' } } as never)

    render(
      <SkillEditor
        open={true}
        skill={{
          id: 'sk-1',
          name: 'Skill One',
          description: 'desc',
          instructions: 'initial workflow',
          is_active: true,
          is_system: false,
          tool_ids: ['tool-1'],
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }}
        mode="edit"
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />, { wrapper }
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'skills.editor.generateWorkflow' })).toBeDefined()
    })

    fireEvent.click(screen.getByRole('button', { name: 'skills.editor.generateWorkflow' }))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/skills/workflow/generate', expect.any(Object))
      expect((screen.getByRole('textbox', { name: 'skills.editor.workflow' }) as HTMLInputElement).value).toContain('generated workflow')
    })
  })

  it('opens workflow preview with model header', async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: {
        instruction_file: '# Skill Workflow File',
        model_id: 'gpt-4o-mini',
        selected_tools: [],
      },
    } as never)

    render(
      <SkillEditor
        open={true}
        skill={{
          id: 'sk-1',
          name: 'Skill One',
          description: 'desc',
          instructions: 'initial workflow',
          is_active: true,
          is_system: false,
          tool_ids: ['tool-1'],
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }}
        mode="view"
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />, { wrapper }
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'skills.editor.previewWorkflow' })).toBeDefined()
    })

    fireEvent.click(screen.getByRole('button', { name: 'skills.editor.previewWorkflow' }))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/skills/workflow/preview', expect.any(Object))
      expect(screen.getByText('skills.editor.workflowPreviewTitle gpt-4o-mini')).toBeDefined()
      expect(screen.getByText('# Skill Workflow File')).toBeDefined()
    })
  })

  it('sends latest unsaved workflow state to preview endpoint', async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: {
        instruction_file: '# Skill Workflow File\nLatest draft workflow',
        model_id: 'gpt-4o-mini',
        selected_tools: [],
      },
    } as never)

    render(
      <SkillEditor
        open={true}
        skill={null}
        mode="create"
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />, { wrapper }
    )

    fireEvent.change(screen.getByRole('textbox', { name: 'app.description' }), {
      target: { value: 'latest description' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: 'skills.editor.workflow' }), {
      target: { value: 'Latest draft workflow' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'skills.editor.previewWorkflow' }))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/skills/workflow/preview', expect.objectContaining({
        workflow: 'Latest draft workflow',
        description: 'latest description',
      }))
      expect(screen.getByText('skills.editor.workflowPreviewTitle gpt-4o-mini')).toBeDefined()
      expect(screen.getAllByText(/Latest draft workflow/).length).toBeGreaterThan(0)
    })
  })

  it('shows missing-model error and does not overwrite manual workflow text', async () => {
    // Override skillDetail response so it returns 'manual workflow text' as instructions,
    // preventing the useEffect from overwriting the test's workflow field value.
    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url === '/agents/roles') return Promise.resolve({ data: [] })
      if (url === '/skills/sk-1') return Promise.resolve({ data: { ...SKILL_DETAIL, instructions: 'manual workflow text', instructions_with_tools: 'manual workflow text' } })
      return Promise.resolve({ data: [] })
    })

    vi.mocked(apiClient.post).mockRejectedValueOnce({
      response: {
        data: {
          detail: 'Workflow generation model is not configured. Configure it in system settings.',
        },
      },
    } as never)

    // Render with a skill that has pre-selected tools so "Generate with AI" calls the
    // API directly without opening the tool selector dialog first.
    render(
      <SkillEditor
        open={true}
        skill={{
          id: 'sk-1',
          name: 'Skill One',
          description: 'desc',
          instructions: 'manual workflow text',
          is_active: true,
          is_system: false,
          tool_ids: ['tool-1'],
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }}
        mode="edit"
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />
    )

    // Wait for the workflow to update
    await waitFor(() => {
      expect((screen.getByRole('textbox', { name: 'skills.editor.workflow' }) as HTMLInputElement).value).toBe('manual workflow text')
    })

    fireEvent.change(screen.getByRole('textbox', { name: 'app.description' }), {
      target: { value: 'desc' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: 'skills.editor.workflow' }), {
      target: { value: 'manual workflow text' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'skills.editor.generateWorkflow' }))

    await waitFor(() => {
      expect(screen.getByText(/not configured/i)).toBeDefined()
      expect((screen.getByRole('textbox', { name: 'skills.editor.workflow' }) as HTMLInputElement).value).toBe('manual workflow text')
    })
  })
})
