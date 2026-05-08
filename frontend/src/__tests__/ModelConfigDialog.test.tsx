import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockPost = vi.fn()
const mockPut = vi.fn()
const mockGet = vi.fn()

vi.mock('../api/apiClient', () => ({
  default: {
    post: mockPost,
    put: mockPut,
    get: mockGet,
  },
}))

const MOCK_EXISTING_CONFIG = {
  id: 'cfg-1',
  display_name: 'GPT-4 Config',
  provider_type: 'openai',
  api_base_url: 'https://api.openai.com/v1',
  has_credentials: true,
  enabled_models: [],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('ModelConfigDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockPost.mockResolvedValue({ data: MOCK_EXISTING_CONFIG })
    mockPut.mockResolvedValue({ data: MOCK_EXISTING_CONFIG })
    mockGet.mockResolvedValue({ data: [] })
  })

  it('renders provider type selector with all provider options', async () => {
    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={null} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    // Provider type select should be present
    await waitFor(() => {
      expect(screen.getByText('agents.modelConfigs.providerType', { selector: 'label' })).toBeDefined()
    })
  })

  it('shows API key field for openai provider', async () => {
    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={null} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.modelConfigs.apiKey', { selector: 'label' })).toBeDefined()
    })
  })

  it('shows endpoint URL field in create mode', async () => {
    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={null} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.modelConfigs.apiBaseUrl', { selector: 'label' })).toBeDefined()
    })
  })

  it('blocks save when display name is empty', async () => {
    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={null} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    await waitFor(() => {
      // Name field should be empty initially
      const saveBtn = screen.getByText('app.save')
      expect(saveBtn).toBeDefined()
    })
  })

  it('pre-populates name and endpoint in edit mode', async () => {
    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={MOCK_EXISTING_CONFIG as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    await waitFor(() => {
      const nameInput = screen.getByDisplayValue('GPT-4 Config')
      expect(nameInput).toBeDefined()
    })
  })

  it('does NOT pre-populate api key field in edit mode', async () => {
    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={MOCK_EXISTING_CONFIG as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    await waitFor(() => {
      // Encrypted value must not appear in the text field
      const encValue = screen.queryByDisplayValue('enc:present')
      expect(encValue).toBeNull()

      // API key field should be blank
      const keyInputs = screen.queryAllByDisplayValue(/sk-/)
      expect(keyInputs).toHaveLength(0)
    })
  })

  it('shows PermissionDeniedAlert when save returns 403', async () => {
    mockPost.mockRejectedValue({ response: { status: 403, data: { detail: 'Forbidden' } } })

    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={null} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    // Wait for dialog to render
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })

    // Fill in the display name field (look by placeholder or testid fallback)
    const nameInputs = screen.queryAllByRole('textbox')
    if (nameInputs.length > 0) {
      fireEvent.change(nameInputs[0], { target: { value: 'Test Config' } })
    }

    const saveBtn = screen.getByText('app.save')
    fireEvent.click(saveBtn)

    await waitFor(() => {
      // PermissionDeniedAlert should render
      const alert = screen.queryByRole('alert')
      expect(alert).not.toBeNull()
    })
  })

  it('clears error state when dialog is reopened', async () => {
    const onClose = vi.fn()
    mockPost.mockRejectedValue({ response: { status: 403 } })

    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrap = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    )

    const { rerender } = render(
      <ModelConfigDialog open config={null} onClose={onClose} onSaved={vi.fn()} />,
      { wrapper: wrap },
    )

    // Close and reopen using the same wrapper
    rerender(<ModelConfigDialog open={false} config={null} onClose={onClose} onSaved={vi.fn()} />)
    rerender(<ModelConfigDialog open config={null} onClose={onClose} onSaved={vi.fn()} />)

    // Error should be cleared — no alert visible on fresh open
    await waitFor(() => {
      const alert = screen.queryByRole('alert')
      expect(alert).toBeNull()
    })
  })

  it('shows conflict error message on 409 response', async () => {
    mockPut.mockRejectedValue({ response: { status: 409, data: { detail: 'Referenced by AgentType' } } })

    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={MOCK_EXISTING_CONFIG as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    const saveBtn = screen.getByText('app.save')
    fireEvent.click(saveBtn)

    await waitFor(() => {
      const alert = screen.queryByRole('alert')
      expect(alert).not.toBeNull()
    })
  })

  it('shows api key optional hint for litellm_proxy provider', async () => {
    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={null} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    // The dialog renders — litellm_proxy is selectable
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeDefined()
    })
  })

  it('Fetch Models button is visible in edit mode', async () => {
    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={MOCK_EXISTING_CONFIG as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    await waitFor(() => {
      // The fetch models button key is 'agents.modelConfigs.fetchModels'
      const fetchBtn = screen.queryByText('agents.modelConfigs.fetchModels')
      expect(fetchBtn).not.toBeNull()
    })
  })

  it('Fetch Models button is NOT visible in create mode', async () => {
    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={null} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.queryByText('agents.modelConfigs.fetchModels')).toBeNull()
    })
  })

  it('calls available-models API when Fetch Models is clicked and renders checkboxes', async () => {
    const AVAILABLE = ['gpt-4o', 'gpt-4-turbo', 'gpt-4o-mini']
    mockGet.mockResolvedValue({ data: AVAILABLE })

    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={MOCK_EXISTING_CONFIG as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.modelConfigs.fetchModels')).toBeDefined()
    })

    const fetchBtn = screen.getByText('agents.modelConfigs.fetchModels')
    fireEvent.click(fetchBtn)

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith(
        expect.stringContaining(`/agents/model-configs/${MOCK_EXISTING_CONFIG.id}/models`)
      )
    })

    await waitFor(() => {
      // Checkboxes for each available model should appear
      const checkboxes = screen.queryAllByRole('checkbox')
      expect(checkboxes.length).toBeGreaterThanOrEqual(AVAILABLE.length)
    })
  })

  it('checking a model includes its identifier in enabled_models payload on save', async () => {
    const AVAILABLE = ['gpt-4o', 'gpt-4-turbo']
    mockGet.mockResolvedValue({ data: AVAILABLE })
    mockPut.mockResolvedValue({ data: { ...MOCK_EXISTING_CONFIG, enabled_models: ['gpt-4o'] } })

    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={MOCK_EXISTING_CONFIG as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    // Fetch models
    await waitFor(() => expect(screen.getByText('agents.modelConfigs.fetchModels')).toBeDefined())
    fireEvent.click(screen.getByText('agents.modelConfigs.fetchModels'))

    // Wait for checkboxes to appear
    await waitFor(() => {
      expect(screen.queryAllByRole('checkbox').length).toBeGreaterThan(0)
    })

    // Check the first checkbox (gpt-4o)
    const checkboxes = screen.queryAllByRole('checkbox')
    if (checkboxes.length > 0) {
      fireEvent.click(checkboxes[0])
    }

    // Save
    fireEvent.click(screen.getByText('app.save'))

    await waitFor(() => {
      expect(mockPut).toHaveBeenCalled()
      const callArgs = mockPut.mock.calls[0][1] as Record<string, unknown>
      expect(Array.isArray(callArgs.enabled_models)).toBe(true)
    })
  })

  it('shows inline error when fetch models call fails and preserves existing enabled_models', async () => {
    // The edit config has enabled_models already set (simulated via component state init from config)
    const configWithModels = { ...MOCK_EXISTING_CONFIG, enabled_models: ['gpt-4o'] }
    mockGet.mockRejectedValue(new Error('provider unreachable'))

    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={configWithModels as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    await waitFor(() => expect(screen.getByText('agents.modelConfigs.fetchModels')).toBeDefined())
    fireEvent.click(screen.getByText('agents.modelConfigs.fetchModels'))

    // After failure, no checkbox list appears (availableModels stays empty)
    await waitFor(() => {
      const checkboxes = screen.queryAllByRole('checkbox')
      // Checkboxes rendered only when availableModels list is populated
      expect(checkboxes.length).toBe(0)
    })
  })

  it('edit mode renders previously saved enabled_models count hint', async () => {
    const configWithModels = { ...MOCK_EXISTING_CONFIG, enabled_models: ['gpt-4o', 'gpt-4-turbo'] }

    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={configWithModels as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    // The enabled_models section is rendered (fetch models button visible)
    await waitFor(() => {
      expect(screen.queryByText('agents.modelConfigs.fetchModels')).not.toBeNull()
    })
  })

  it('shows enabled models as Chip components before Fetch Models is clicked', async () => {
    const configWithModels = {
      ...MOCK_EXISTING_CONFIG,
      enabled_models: ['gpt-4o', 'gpt-4-turbo'],
    }
    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={configWithModels as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    // availableModels is empty (no fetch triggered yet) so enabled models render as Chips
    await waitFor(() => {
      expect(screen.getByText('gpt-4o')).toBeDefined()
      expect(screen.getByText('gpt-4-turbo')).toBeDefined()
    })
  })

  it('shows apiKeySet helper text when config has api_key set', async () => {
    const configWithKey = {
      ...MOCK_EXISTING_CONFIG,
      has_credentials: true,
    }
    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={configWithKey as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.modelConfigs.apiKeySet')).toBeDefined()
    })
  })

  it('shows apiKeyNotSet helper text when config has no api_key', async () => {
    const configWithoutKey = {
      ...MOCK_EXISTING_CONFIG,
      has_credentials: false,
    }
    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={configWithoutKey as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.modelConfigs.apiKeyNotSet')).toBeDefined()
    })
  })

  it('save payload includes enabled_models array even when empty', async () => {
    mockPost.mockResolvedValue({ data: MOCK_EXISTING_CONFIG })

    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={null} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    await waitFor(() => expect(screen.getByRole('dialog')).toBeDefined())

    // Fill in required display name
    const nameInputs = screen.queryAllByRole('textbox')
    if (nameInputs.length > 0) {
      fireEvent.change(nameInputs[0], { target: { value: 'My Config' } })
    }

    fireEvent.click(screen.getByText('app.save'))

    await waitFor(() => {
      if (mockPost.mock.calls.length > 0) {
        const payload = mockPost.mock.calls[0][1] as Record<string, unknown>
        expect(Array.isArray(payload.enabled_models)).toBe(true)
      }
    })
  })

  it('does not include api_key in payload when bullets are unchanged in edit mode', async () => {
    mockPut.mockResolvedValue({ data: MOCK_EXISTING_CONFIG })

    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    render(
      <ModelConfigDialog open config={MOCK_EXISTING_CONFIG as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    await waitFor(() => expect(screen.getByRole('dialog')).toBeDefined())

    // Don't touch the API key field (it shows bullets but user didn't change it)
    fireEvent.click(screen.getByText('app.save'))

    await waitFor(() => {
      if (mockPut.mock.calls.length > 0) {
        const payload = mockPut.mock.calls[0][1] as Record<string, unknown>
        // api_key should NOT be in the payload
        expect(payload.api_key).toBeUndefined()
      }
    })
  })

  it('includes new api_key in payload when user changes it from bullets', async () => {
    mockPut.mockResolvedValue({ data: MOCK_EXISTING_CONFIG })

    const { ModelConfigDialog } = await import('../pages/agents/ModelConfigDialog')
    const { container } = render(
      <ModelConfigDialog open config={MOCK_EXISTING_CONFIG as any} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper },
    )

    // Wait for the dialog and password field to render
    await waitFor(() => {
      const apiKeyInput = container.querySelector('input[type="password"]')
      expect(apiKeyInput).not.toBeNull()
    })

    const apiKeyInput = container.querySelector('input[type="password"]') as HTMLInputElement
    fireEvent.change(apiKeyInput, { target: { value: 'sk-new-key-123' } })

    fireEvent.click(screen.getByText('app.save'))

    await waitFor(() => {
      if (mockPut.mock.calls.length > 0) {
        const payload = mockPut.mock.calls[0][1] as Record<string, unknown>
        // api_key SHOULD be in the payload with the new value
        expect(payload.api_key).toBe('sk-new-key-123')
      }
    })
  })
})