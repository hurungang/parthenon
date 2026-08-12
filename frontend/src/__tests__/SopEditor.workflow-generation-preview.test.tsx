import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { SopEditor } from '../pages/skills/SopEditor'
import apiClient from '../api/apiClient'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, vars?: Record<string, string>) => {
    if (k === 'sops.editor.workflowPreviewTitle') return `sops.editor.workflowPreviewTitle ${vars?.model ?? ''}`
    return k
  } }),
}))

vi.mock('../hooks/useSops', () => {
  const stableRoleIds: string[] = []
  return {
    useSopRoles: () => ({ data: stableRoleIds, isLoading: false }),
  }
})

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn((url: string) => {
      if (url === '/skills') return Promise.resolve({ data: [] })
      if (url === '/agents/types') return Promise.resolve({ data: [] })
      if (url === '/agents/roles') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    }),
    post: vi.fn(),
    put: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('SopEditor workflow generation and preview', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('generates workflow and updates workflow field', async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: { workflow: 'generated sop workflow', model_id: 'gpt-4o' } } as never)

    render(<SopEditor open={true} sop={null} mode="edit" onClose={vi.fn()} onSaved={vi.fn()} />, { wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'sops.editor.generateWorkflow' })).toBeDefined()
    })

    fireEvent.change(screen.getByRole('textbox', { name: 'app.description' }), { target: { value: 'desc' } })
    fireEvent.click(screen.getByRole('button', { name: 'sops.editor.generateWorkflow' }))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/sops/workflow/generate', expect.any(Object))
      expect((screen.getByRole('textbox', { name: 'sops.workflow' }) as HTMLInputElement).value).toContain('generated sop workflow')
    })
  })

  it('opens workflow preview with configured model in header', async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: {
        instruction_file: '# SOP Workflow File',
        model_id: 'gpt-4o-mini',
        steps: [],
      },
    } as never)

    render(<SopEditor open={true} sop={null} mode="view" onClose={vi.fn()} onSaved={vi.fn()} />, { wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'sops.editor.previewWorkflow' })).toBeDefined()
    })

    fireEvent.click(screen.getByRole('button', { name: 'sops.editor.previewWorkflow' }))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/sops/workflow/preview', expect.any(Object))
      expect(screen.getByText('sops.editor.workflowPreviewTitle gpt-4o-mini')).toBeDefined()
      expect(screen.getByText('# SOP Workflow File')).toBeDefined()
    })
  })

  it('sends latest unsaved step/workflow state to preview endpoint', async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: {
        instruction_file: '# SOP Workflow File\nLatest SOP workflow',
        model_id: 'gpt-4o-mini',
        steps: [],
      },
    } as never)

    render(<SopEditor open={true} sop={null} mode="create" onClose={vi.fn()} onSaved={vi.fn()} />, { wrapper })

    fireEvent.change(screen.getByRole('textbox', { name: 'app.description' }), {
      target: { value: 'sop desc latest' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: 'sops.workflow' }), {
      target: { value: 'Latest SOP workflow' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'sops.editor.previewWorkflow' }))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/sops/workflow/preview', expect.objectContaining({
        workflow: 'Latest SOP workflow',
        description: 'sop desc latest',
      }))
      expect(screen.getByText('sops.editor.workflowPreviewTitle gpt-4o-mini')).toBeDefined()
      expect(screen.getAllByText(/Latest SOP workflow/).length).toBeGreaterThan(0)
    })
  })

  it('shows missing-model error and keeps manual SOP workflow text', async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce({
      response: {
        data: {
          detail: 'Workflow generation model is not configured. Configure it in system settings.',
        },
      },
    } as never)

    render(<SopEditor open={true} sop={null} mode="create" onClose={vi.fn()} onSaved={vi.fn()} />, { wrapper })

    fireEvent.change(screen.getByRole('textbox', { name: 'app.description' }), {
      target: { value: 'desc' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: 'sops.workflow' }), {
      target: { value: 'manual sop workflow' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'sops.editor.generateWorkflow' }))

    await waitFor(() => {
      expect(screen.getByText(/not configured/i)).toBeDefined()
      expect((screen.getByRole('textbox', { name: 'sops.workflow' }) as HTMLInputElement).value).toBe('manual sop workflow')
    })
  })
})
