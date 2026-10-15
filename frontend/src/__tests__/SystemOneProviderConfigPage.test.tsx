import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('react-router-dom', async () => {
  const actual =
    await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn() }
})

const MOCK_PROVIDERS = [
  {
    id: 'p-1',
    provider_type: 'typesafe',
    display_name: 'TypeSafe Jev',
    base_url: 'https://api.typesafe.example/v1',
    default_model: 'jev-latest',
    enabled: true,
    enabled_models: ['jev-latest'],
    has_api_key: true,
  },
  {
    id: 'p-2',
    provider_type: 'typesafe',
    display_name: 'No Key Yet',
    base_url: 'https://other.example/v1',
    default_model: 'jev-latest',
    enabled: false,
    enabled_models: null,
    has_api_key: false,
  },
]

const apiMock = vi.hoisted(() => ({
  listSystemOneProviders: vi.fn(),
  createSystemOneProvider: vi.fn(),
  updateSystemOneProvider: vi.fn(),
  deleteSystemOneProvider: vi.fn(),
  testSystemOneProviderConnection: vi.fn(),
  listDecisionModelHierarchy: vi.fn(),
  setProviderAvailability: vi.fn(),
  setDecisionModelAvailability: vi.fn(),
  listEnabledDecisionModels: vi.fn(),
  getSystemOneStatus: vi.fn(),
  listSystemOneProviderTypes: vi.fn(),
  listVendorModels: vi.fn(),
  importVendorModels: vi.fn(),
  SYSTEM_ONE_PRESET_BASE_URL: 'https://api.typesafe.ai/v1/systemone',
}))

vi.mock('../api/systemOneApi', () => apiMock)

function wrapper(children: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

async function renderPage() {
  const { SystemOneProviderConfigPage } = await import(
    '../pages/system/SystemOneProviderConfigPage'
  )
  return render(wrapper(<SystemOneProviderConfigPage />))
}

describe('SystemOneProviderConfigPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.listSystemOneProviders.mockResolvedValue(MOCK_PROVIDERS)
    apiMock.listDecisionModelHierarchy.mockResolvedValue([])
    apiMock.listEnabledDecisionModels.mockResolvedValue([])
    apiMock.setProviderAvailability.mockResolvedValue({})
    apiMock.setDecisionModelAvailability.mockResolvedValue(undefined)
    apiMock.createSystemOneProvider.mockResolvedValue(MOCK_PROVIDERS[0])
    apiMock.updateSystemOneProvider.mockResolvedValue(MOCK_PROVIDERS[0])
    apiMock.deleteSystemOneProvider.mockResolvedValue(undefined)
    apiMock.createSystemOneProvider.mockResolvedValue(MOCK_PROVIDERS[0])
    apiMock.updateSystemOneProvider.mockResolvedValue(MOCK_PROVIDERS[0])
    apiMock.listSystemOneProviderTypes.mockResolvedValue([
      { value: 'typesafe', label: 'typesafe' },
    ])
    apiMock.listVendorModels.mockResolvedValue({ models: [] })
    apiMock.importVendorModels.mockResolvedValue(MOCK_PROVIDERS[0])
  })

  it('renders providers with key-status chips and no key material', async () => {
    await renderPage()
    expect(await screen.findByText('TypeSafe Jev')).toBeInTheDocument()
    // has_api_key renders a "stored" chip; never the key itself.
    expect(screen.getByText('systemOne.apiKeyStored')).toBeInTheDocument()
    expect(screen.getByText('systemOne.apiKeyMissing')).toBeInTheDocument()
    expect(screen.getByText('systemOne.status.configured')).toBeInTheDocument()
  })

  it('creates a provider with the API key sent once (write-only)', async () => {
    await renderPage()
    fireEvent.click(await screen.findByText('systemOne.addProvider'))
    fireEvent.change(screen.getByLabelText(/systemOne\.displayName/), {
      target: { value: 'New Provider' },
    })
    fireEvent.change(screen.getByLabelText(/systemOne\.baseUrl/), {
      target: { value: 'https://new.example/v1' },
    })
    fireEvent.change(screen.getByLabelText(/systemOne\.apiKey/), {
      target: { value: 'sk-new-secret' },
    })
    fireEvent.click(screen.getByText('app.save'))
    await waitFor(() =>
      expect(apiMock.createSystemOneProvider).toHaveBeenCalledTimes(1),
    )
    const body = apiMock.createSystemOneProvider.mock.calls[0][0]
    expect(body.api_key).toBe('sk-new-secret')
    expect(body.display_name).toBe('New Provider')
    expect(body.default_model).toBe('jev-latest')
  })

  it('validates required fields on create', async () => {
    await renderPage()
    fireEvent.click(await screen.findByText('systemOne.addProvider'))
    fireEvent.click(screen.getByText('app.save'))
    expect(
      await screen.findByText('systemOne.validation.displayNameRequired'),
    ).toBeInTheDocument()
    expect(apiMock.createSystemOneProvider).not.toHaveBeenCalled()
  })

  it('edit dialog never prefills the API key and omits it when unchanged', async () => {
    await renderPage()
    const rows = await screen.findByText('TypeSafe Jev')
    expect(rows).toBeInTheDocument()
    // Open the edit dialog for the first provider (edit icon button).
    const editButtons = screen.getAllByRole('button', { name: 'app.edit' })
    fireEvent.click(editButtons[0])
    // Write-only: key field is empty even though has_api_key is true.
    const keyField = screen.getByLabelText(/systemOne\.apiKey/) as HTMLInputElement
    expect(keyField.value).toBe('')
    fireEvent.change(screen.getByLabelText(/systemOne\.displayName/), {
      target: { value: 'Renamed Provider' },
    })
    fireEvent.click(screen.getByText('app.save'))
    await waitFor(() =>
      expect(apiMock.updateSystemOneProvider).toHaveBeenCalledTimes(1),
    )
    const [id, body] = apiMock.updateSystemOneProvider.mock.calls[0]
    expect(id).toBe('p-1')
    expect(body.display_name).toBe('Renamed Provider')
    expect(body).not.toHaveProperty('api_key')
  })

  it('sends a new api_key on update only when typed', async () => {
    await renderPage()
    await screen.findByText('TypeSafe Jev')
    fireEvent.click(screen.getAllByRole('button', { name: 'app.edit' })[0])
    fireEvent.change(screen.getByLabelText(/systemOne\.apiKey/), {
      target: { value: 'sk-rotated' },
    })
    fireEvent.click(screen.getByText('app.save'))
    await waitFor(() =>
      expect(apiMock.updateSystemOneProvider).toHaveBeenCalledTimes(1),
    )
    const [, body] = apiMock.updateSystemOneProvider.mock.calls[0]
    expect(body.api_key).toBe('sk-rotated')
  })

  it('shows a dialog error when create fails (dialog error handling)', async () => {
    apiMock.createSystemOneProvider.mockRejectedValue({
      response: { status: 403 },
    })
    await renderPage()
    fireEvent.click(await screen.findByText('systemOne.addProvider'))
    fireEvent.change(screen.getByLabelText(/systemOne\.displayName/), {
      target: { value: 'X' },
    })
    fireEvent.change(screen.getByLabelText(/systemOne\.baseUrl/), {
      target: { value: 'https://x.example/v1' },
    })
    fireEvent.change(screen.getByLabelText(/systemOne\.apiKey/), {
      target: { value: 'sk-x' },
    })
    fireEvent.click(screen.getByText('app.save'))
    // PermissionDeniedAlert renders both at page level and inside the dialog.
    await waitFor(() => {
      expect(screen.getAllByText('app.error').length).toBeGreaterThan(0)
    })
    // Dialog stays open (its title button row still shows the add-provider text twice:
    // page button + dialog title).
    expect(screen.getAllByText('systemOne.addProvider').length).toBeGreaterThan(1)
  })

  it('deletes a provider', async () => {
    await renderPage()
    await screen.findByText('TypeSafe Jev')
    // Delete icon buttons have no aria-label; click via the icon.
    fireEvent.click(screen.getAllByTestId('DeleteIcon')[0].closest('button')!)
    // Confirm-on-delete dialog: the API call happens after confirmation.
    const confirmButton = await screen.findByRole('button', { name: 'app.delete' })
    fireEvent.click(confirmButton)
    await waitFor(() =>
      expect(apiMock.deleteSystemOneProvider).toHaveBeenCalledWith('p-1'),
    )
  })

  it('shows empty state when no providers exist', async () => {
    apiMock.listSystemOneProviders.mockResolvedValue([])
    await renderPage()
    expect(await screen.findByText('systemOne.noProviders')).toBeInTheDocument()
    expect(screen.getByText('systemOne.status.notConfigured')).toBeInTheDocument()
  })

  // ── Round 2: preset base URL + Test connection ──────────────────────────

  it('presets the base URL as an editable default in the create dialog', async () => {
    await renderPage()
    fireEvent.click(await screen.findByText('systemOne.addProvider'))
    const baseUrl = screen.getByLabelText(
      /systemOne\.baseUrl/,
    ) as HTMLInputElement
    expect(baseUrl.value).toBe('https://api.typesafe.ai/v1/systemone')
    // Editable per tenant — NOT disabled.
    expect(baseUrl).not.toBeDisabled()
    expect(
      screen.getByText('systemOne.baseUrlHint'),
    ).toBeInTheDocument()
  })

  it('sends the typed base_url on create', async () => {
    await renderPage()
    fireEvent.click(await screen.findByText('systemOne.addProvider'))
    const baseUrl = screen.getByLabelText(/systemOne\.baseUrl/) as HTMLInputElement
    expect(baseUrl.value).toBe('https://api.typesafe.ai/v1/systemone')
    fireEvent.change(baseUrl, { target: { value: 'https://tenant.example/v1/systemone' } })
    fireEvent.change(screen.getByLabelText(/systemOne\.displayName/), {
      target: { value: 'Preset Provider' },
    })
    fireEvent.change(screen.getByLabelText(/systemOne\.apiKey/), {
      target: { value: 'sk-preset' },
    })
    fireEvent.click(screen.getByText('app.save'))
    await waitFor(() =>
      expect(apiMock.createSystemOneProvider).toHaveBeenCalledTimes(1),
    )
    const createBody = apiMock.createSystemOneProvider.mock.calls[0][0]
    expect(createBody.base_url).toBe('https://tenant.example/v1/systemone')
  })

  it('sends base_url on update (editable per tenant)', async () => {
    await renderPage()
    await screen.findByText('TypeSafe Jev')
    fireEvent.click(screen.getAllByRole('button', { name: 'app.edit' })[0])
    fireEvent.change(screen.getByLabelText(/systemOne\.baseUrl/), {
      target: { value: 'https://updated.example/v1' },
    })
    fireEvent.change(screen.getByLabelText(/systemOne\.displayName/), {
      target: { value: 'Renamed Again' },
    })
    fireEvent.click(screen.getByText('app.save'))
    await waitFor(() =>
      expect(apiMock.updateSystemOneProvider).toHaveBeenCalledTimes(1),
    )
    const [, updateBody] = apiMock.updateSystemOneProvider.mock.calls[0]
    expect(updateBody.base_url).toBe('https://updated.example/v1')
  })

  it('validates that base_url is required', async () => {
    await renderPage()
    fireEvent.click(await screen.findByText('systemOne.addProvider'))
    fireEvent.change(screen.getByLabelText(/systemOne\.displayName/), {
      target: { value: 'No URL Provider' },
    })
    fireEvent.change(screen.getByLabelText(/systemOne\.baseUrl/), {
      target: { value: '' },
    })
    fireEvent.change(screen.getByLabelText(/systemOne\.apiKey/), {
      target: { value: 'sk-x' },
    })
    fireEvent.click(screen.getByText('app.save'))
    expect(
      await screen.findByText('systemOne.validation.baseUrlRequired'),
    ).toBeInTheDocument()
    expect(apiMock.createSystemOneProvider).not.toHaveBeenCalled()
  })

  it('shows the saved-key placeholder on edit when has_api_key, not on create', async () => {
    await renderPage()
    await screen.findByText('TypeSafe Jev')
    // Edit dialog for the provider with has_api_key=true.
    fireEvent.click(screen.getAllByRole('button', { name: 'app.edit' })[0])
    const keyField = screen.getByLabelText(/systemOne\.apiKey/) as HTMLInputElement
    expect(keyField.getAttribute('placeholder')).toBe(
      'systemOne.apiKeySavedPlaceholder',
    )
    expect(screen.getByText('systemOne.apiKeyConfigured')).toBeInTheDocument()
    // Close and open create — no saved placeholder / configured indicator.
    fireEvent.click(screen.getByText('app.cancel'))
    fireEvent.click(await screen.findByText('systemOne.addProvider'))
    const createKeyField = screen.getByLabelText(
      /systemOne\.apiKey/,
    ) as HTMLInputElement
    expect(createKeyField.getAttribute('placeholder')).not.toBe(
      'systemOne.apiKeySavedPlaceholder',
    )
    expect(screen.queryByText('systemOne.apiKeyConfigured')).not.toBeInTheDocument()
  })

  it('Test connection button shows success state (status-only)', async () => {
    apiMock.testSystemOneProviderConnection.mockResolvedValue({
      ok: true,
      message: 'Connection succeeded',
      latency_ms: 12.5,
    })
    await renderPage()
    fireEvent.click(
      (
        await screen.findAllByRole('button', {
          name: 'systemOne.testConnection',
        })
      )[0],
    )
    await waitFor(() => {
      expect(apiMock.testSystemOneProviderConnection).toHaveBeenCalledWith('p-1')
    })
    expect(await screen.findByText('systemOne.testSuccess')).toBeInTheDocument()
    // status-only: no key material anywhere
    expect(screen.queryByText(/sk-/)).not.toBeInTheDocument()
  })

  it('Test connection button shows the failure reason on failure', async () => {
    apiMock.testSystemOneProviderConnection.mockResolvedValue({
      ok: false,
      message: 'provider endpoint unreachable',
      latency_ms: null,
    })
    await renderPage()
    fireEvent.click(
      (
        await screen.findAllByRole('button', {
          name: 'systemOne.testConnection',
        })
      )[0],
    )
    expect(await screen.findByText('systemOne.testFailure')).toBeInTheDocument()
  })

  it('disables the tested provider button while a test is in flight', async () => {
    let resolveTest: (v: unknown) => void = () => {}
    apiMock.testSystemOneProviderConnection.mockReturnValue(
      new Promise((resolve) => {
        resolveTest = resolve
      }),
    )
    await renderPage()
    await screen.findByText('TypeSafe Jev')
    const buttons = screen.getAllByRole('button', {
      name: 'systemOne.testConnection',
    })
    fireEvent.click(buttons[0])
    // while testing: the in-flight button is disabled and stops exposing its
    // accessible name (spinner replaces the label) — one enabled button left.
    await waitFor(() => {
      expect(
        screen.getAllByRole('button', { name: 'systemOne.testConnection' }),
      ).toHaveLength(1)
    })
    resolveTest({ ok: true, message: 'ok', latency_ms: 1 })
    await waitFor(() => {
      expect(
        screen.getAllByRole('button', { name: 'systemOne.testConnection' }),
      ).toHaveLength(2)
    })
  })
})
