import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { ModelConfigListPage } from '../pages/agents/ModelConfigListPage'
import apiClient from '../api/apiClient'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn(),
    put: vi.fn(),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

vi.mock('../pages/agents/ModelConfigDialog', () => ({
  ModelConfigDialog: () => null,
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('ModelConfigListPage workflow generation model config', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url === '/agents/model-configs') {
        return Promise.resolve({ data: [] })
      }
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
      return Promise.resolve({ data: [] })
    })
    vi.mocked(apiClient.put).mockResolvedValue({ data: {} } as never)
  })

  it('renders workflow generation model section and saves selection', async () => {
    render(<ModelConfigListPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('agents.modelConfigs.workflowGenerationTitle')).toBeDefined()
      expect(screen.getByText('gpt-4o-mini (OpenAI Prod)')).toBeDefined()
      expect(screen.getByRole('button', { name: 'app.save' })).toBeDefined()
      expect(apiClient.get).toHaveBeenCalledWith('/agents/model-configs/workflow-generation')
    })

    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))

    await waitFor(() => {
      expect(apiClient.put).toHaveBeenCalledWith('/agents/model-configs/workflow-generation', {
        model_id: 'gpt-4o-mini',
      })
    })
  })
})
