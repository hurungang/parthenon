import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { SystemConfigPage } from '../pages/system/SystemConfigPage'
import apiClient from '../api/apiClient'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn(),
    put: vi.fn(),
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

describe('SystemConfigPage assistant model config', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url === '/agents/model-configs/workflow-generation') {
        return Promise.resolve({
          data: {
            selected_model_id: 'gpt-4o-mini',
            options: [
              {
                model_id: 'gpt-4o-mini',
                config_id: 'cfg-1',
                config_display_name: 'OpenAI Prod',
                provider_type: 'openai',
              },
            ],
          },
        })
      }
      if (url === '/agents/model-configs/assistant-model') {
        return Promise.resolve({
          data: {
            selected_model_id: 'claude-3-5-sonnet',
            options: [
              {
                model_id: 'claude-3-5-sonnet',
                config_id: 'cfg-2',
                config_display_name: 'Anthropic Prod',
                provider_type: 'anthropic',
              },
              {
                model_id: 'gpt-4o',
                config_id: 'cfg-1',
                config_display_name: 'OpenAI Prod',
                provider_type: 'openai',
              },
            ],
          },
        })
      }
      return Promise.resolve({ data: {} })
    })
    vi.mocked(apiClient.put).mockResolvedValue({ data: {} } as never)
  })

  it('loads the assistant-model config from the tenant-scoped endpoint', async () => {
    render(<SystemConfigPage />, { wrapper })

    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledWith(
        '/agents/model-configs/assistant-model',
      )
    })
    expect(apiClient.get).toHaveBeenCalledWith(
      '/agents/model-configs/workflow-generation',
    )
  })

  it('renders both model sections and saves the assistant selection', async () => {
    render(<SystemConfigPage />, { wrapper })

    // Both sections render with their current selections.
    expect(await screen.findByText('systemConfig.workflowSection')).toBeDefined()
    expect(screen.getByText('systemConfig.assistantSection')).toBeDefined()
    // The assistant select shows the tenant's stored selection (MUI Select
    // renders the chosen option's label).
    expect(
      await screen.findByText('claude-3-5-sonnet (Anthropic Prod)'),
    ).toBeDefined()

    // Save the assistant selection.
    const saveButtons = screen.getAllByRole('button', { name: 'app.save' })
    expect(saveButtons.length).toBe(2)
    fireEvent.click(saveButtons[1])

    await waitFor(() => {
      expect(apiClient.put).toHaveBeenCalledWith(
        '/agents/model-configs/assistant-model',
        { model_id: 'claude-3-5-sonnet' },
      )
    })
  })
})
