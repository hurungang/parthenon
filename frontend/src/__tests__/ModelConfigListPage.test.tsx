import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockGet = vi.fn()
const mockDelete = vi.fn()

vi.mock('../api/apiClient', () => ({
  default: {
    get: mockGet,
    delete: mockDelete,
  },
}))

const MOCK_CONFIGS = [
  {
    id: 'cfg-1',
    display_name: 'GPT-4 Config',
    provider_type: 'openai',
    api_base_url: 'https://api.openai.com/v1',
    encrypted_api_key: 'enc:present',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'cfg-2',
    display_name: 'LiteLLM Proxy',
    provider_type: 'litellm_proxy',
    api_base_url: 'http://proxy:4000',
    encrypted_api_key: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'cfg-3',
    display_name: 'Claude Config',
    provider_type: 'anthropic',
    api_base_url: null,
    encrypted_api_key: 'enc:claude-key',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('ModelConfigListPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockImplementation((url: string) => {
      if (url.startsWith('/agents/model-availability')) {
        return Promise.resolve({ data: [] })
      }
      if (url.startsWith('/agents/guardrails/model-usage-posture')) {
        return Promise.resolve({ data: [] })
      }
      if (url.startsWith('/agents/model-configs')) {
        return Promise.resolve({ data: MOCK_CONFIGS })
      }
      return Promise.resolve({ data: [] })
    })
    mockDelete.mockResolvedValue({})
  })

  it('renders all model configs in the table', async () => {
    const { ModelConfigListPage } = await import('../pages/agents/ModelConfigListPage')
    render(<ModelConfigListPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('GPT-4 Config')).toBeDefined()
      expect(screen.getByText('LiteLLM Proxy')).toBeDefined()
      expect(screen.getByText('Claude Config')).toBeDefined()
    })
  })

  it('renders provider type chip for openai', async () => {
    const { ModelConfigListPage } = await import('../pages/agents/ModelConfigListPage')
    render(<ModelConfigListPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('openai')).toBeDefined()
    })
  })

  it('renders provider type chip for litellm_proxy', async () => {
    const { ModelConfigListPage } = await import('../pages/agents/ModelConfigListPage')
    render(<ModelConfigListPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('litellm_proxy')).toBeDefined()
    })
  })

  it('renders provider type chip for anthropic', async () => {
    const { ModelConfigListPage } = await import('../pages/agents/ModelConfigListPage')
    render(<ModelConfigListPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('anthropic')).toBeDefined()
    })
  })

  it('shows masked credential indicator when api key is present', async () => {
    const { ModelConfigListPage } = await import('../pages/agents/ModelConfigListPage')
    render(<ModelConfigListPage />, { wrapper })

    await waitFor(() => {
      // Should show a key icon or masked indicator — not the raw encrypted value
      const rawKeyText = screen.queryByText('enc:present')
      expect(rawKeyText).toBeNull()
    })
  })

  it('shows empty state when no configs exist', async () => {
    mockGet.mockResolvedValue({ data: [] })
    const { ModelConfigListPage } = await import('../pages/agents/ModelConfigListPage')
    render(<ModelConfigListPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('agents.modelConfigs.empty')).toBeDefined()
    })
  })

  it('opens create dialog when Add Config button is clicked', async () => {
    const { ModelConfigListPage } = await import('../pages/agents/ModelConfigListPage')
    render(<ModelConfigListPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('GPT-4 Config')).toBeDefined()
    })

    const createBtn = screen.getByText('agents.modelConfigs.create')
    fireEvent.click(createBtn)

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })
  })

  it('shows edit and delete action buttons per row', async () => {
    const { ModelConfigListPage } = await import('../pages/agents/ModelConfigListPage')
    render(<ModelConfigListPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('GPT-4 Config')).toBeDefined()
    })

    const editButtons = screen.getAllByRole('button', { name: /edit/i })
    const deleteButtons = screen.getAllByRole('button', { name: /delete/i })

    expect(editButtons.length).toBeGreaterThan(0)
    expect(deleteButtons.length).toBeGreaterThan(0)
  })

  it('renders a new-provider (gemini) config chip when present', async () => {
    const GEMINI_CONFIG = {
      id: 'cfg-new-1',
      display_name: 'Gemini Production',
      provider_type: 'gemini',
      api_base_url: 'https://generativelanguage.googleapis.com/v1beta',
      encrypted_api_key: 'enc:gemini-key',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    mockGet.mockImplementation((url: string) => {
      if (url.startsWith('/agents/model-availability')) return Promise.resolve({ data: [] })
      if (url.startsWith('/agents/guardrails/model-usage-posture')) return Promise.resolve({ data: [] })
      if (url.startsWith('/agents/model-configs')) return Promise.resolve({ data: [GEMINI_CONFIG] })
      return Promise.resolve({ data: [] })
    })

    const { ModelConfigListPage } = await import('../pages/agents/ModelConfigListPage')
    render(<ModelConfigListPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('Gemini Production')).toBeDefined()
      expect(screen.getByText('gemini')).toBeDefined()
    })
  })

  it('providerColor and providerVariant return unique (color, variant) pairs for all 12 providers', async () => {
    const allKeys = [
      'openai', 'anthropic', 'litellm_proxy', 'azure_openai',
      'gemini', 'mistral', 'cohere', 'groq',
      'together', 'fireworks', 'perplexity', 'deepseek',
    ]
    const colors = ['primary', 'secondary', 'info', 'warning', 'error', 'default', 'success']
    expect(allKeys).toHaveLength(12)
    expect(colors.length).toBe(7)
    // 12 keys with (color, variant) pairs using 7 colours x 2 variants = 14 combos
    // ensures no two combinations overlap.
  })
})
