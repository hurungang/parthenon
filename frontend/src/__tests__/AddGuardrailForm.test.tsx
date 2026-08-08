import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'

const shared = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPut: vi.fn(),
  mockDelete: vi.fn(),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: (...args: unknown[]) => shared.mockGet(...args),
    post: (...args: unknown[]) => shared.mockPost(...args),
    put: (...args: unknown[]) => shared.mockPut(...args),
    delete: (...args: unknown[]) => shared.mockDelete(...args),
  },
}))

function renderForm(ui: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

const MODEL_NO_GUARDRAILS = {
  model_name: 'gpt-4.1',
  is_disabled: false,
  disabled_reason: null,
  guardrails: [],
}

const MODEL_WITH_HOUR = {
  model_name: 'gpt-4.1',
  is_disabled: false,
  disabled_reason: null,
  guardrails: [
    {
      id: 'gr-hour',
      model_config_id: 'cfg-1',
      model_id: 'cfg-1',
      model_name: 'gpt-4.1',
      period: 'hour' as const,
      limit_value: 100,
      unit: 'k' as const,
      enforcement_posture: 'terminate' as const,
      is_active: true,
      details: {},
      created_at: '2026-06-01T00:00:00Z',
      updated_at: '2026-06-01T00:00:00Z',
    },
  ],
}

const AVAILABLE = [
  {
    model_id: 'gpt-4.1',
    model_name: 'gpt-4.1',
    model_config_id: 'cfg-1',
    config_id: 'cfg-1',
    config_display_name: 'OpenAI',
    provider_type: 'openai',
  },
]

beforeEach(() => {
  vi.clearAllMocks()
  shared.mockGet.mockImplementation((url: string) => {
    if (url.startsWith('/agents/model-configs')) {
      return Promise.resolve({ data: [{ id: 'cfg-1', display_name: 'OpenAI', provider_type: 'openai', enabled_models: ['gpt-4.1'] }] })
    }
    return Promise.resolve({ data: [] })
  })
  shared.mockPost.mockResolvedValue({ data: {} })
})

describe('AddGuardrailForm - period filter', () => {
  it('offers all four periods when the model has no guardrails', async () => {
    const { AddGuardrailForm } = await import('../components/agents/AddGuardrailForm')
    renderForm(
      <AddGuardrailForm
        model={MODEL_NO_GUARDRAILS}
        vendorConfigId="cfg-1"
        vendorDisplayName="OpenAI"
        availableModels={AVAILABLE}
      />,
    )

    // Open the period combobox
    const periodSelect = screen.getByTestId('add-guardrail-period')
    const periodCombobox = periodSelect.parentElement?.querySelector('[role="combobox"]') as HTMLElement
    expect(periodCombobox).toBeDefined()
    fireEvent.mouseDown(periodCombobox)
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'hour' })).toBeDefined()
      expect(screen.getByRole('option', { name: 'day' })).toBeDefined()
      expect(screen.getByRole('option', { name: 'week' })).toBeDefined()
      expect(screen.getByRole('option', { name: 'month' })).toBeDefined()
    })
  })

  it('filters the period select to only periods not yet configured on the model', async () => {
    const { AddGuardrailForm } = await import('../components/agents/AddGuardrailForm')
    renderForm(
      <AddGuardrailForm
        model={MODEL_WITH_HOUR}
        vendorConfigId="cfg-1"
        vendorDisplayName="OpenAI"
        availableModels={AVAILABLE}
      />,
    )

    const periodSelect = screen.getByTestId('add-guardrail-period')
    const periodCombobox = periodSelect.parentElement?.querySelector('[role="combobox"]') as HTMLElement
    fireEvent.mouseDown(periodCombobox)
    await waitFor(() => {
      expect(screen.queryByRole('option', { name: 'hour' })).toBeNull()
      expect(screen.getByRole('option', { name: 'day' })).toBeDefined()
      expect(screen.getByRole('option', { name: 'week' })).toBeDefined()
      expect(screen.getByRole('option', { name: 'month' })).toBeDefined()
    })
  })
})

describe('AddGuardrailForm - submit behaviour', () => {
  it('submits a single per-period create call with terminate-default and k-default', async () => {
    const onSaved = vi.fn()
    const { AddGuardrailForm } = await import('../components/agents/AddGuardrailForm')
    renderForm(
      <AddGuardrailForm
        model={MODEL_NO_GUARDRAILS}
        vendorConfigId="cfg-1"
        vendorDisplayName="OpenAI"
        availableModels={AVAILABLE}
        onSaved={onSaved}
      />,
    )

    // Pick period=hour
    const periodSelect = screen.getByTestId('add-guardrail-period')
    const periodCombobox = periodSelect.parentElement?.querySelector('[role="combobox"]') as HTMLElement
    fireEvent.mouseDown(periodCombobox)
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'hour' })).toBeDefined()
    })
    fireEvent.click(screen.getByRole('option', { name: 'hour' }))

    // Enter a limit value
    const limitInput = screen.getByTestId('add-guardrail-limit')
    fireEvent.change(limitInput, { target: { value: '100' } })

    // Submit
    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))

    await waitFor(() => {
      expect(shared.mockPost).toHaveBeenCalledWith(
        '/agents/guardrails/model-usage-limits',
        expect.objectContaining({
          model_id: 'gpt-4.1',
          model_name: 'gpt-4.1',
          model_config_id: 'cfg-1',
          period: 'hour',
          limit_value: 100,
          unit: 'k',
          enforcement_posture: 'terminate',
          is_active: true,
        }),
      )
      expect(onSaved).toHaveBeenCalled()
    })
  })

  it('shows a validation error when no period is selected', async () => {
    const { AddGuardrailForm } = await import('../components/agents/AddGuardrailForm')
    renderForm(
      <AddGuardrailForm
        model={MODEL_NO_GUARDRAILS}
        vendorConfigId="cfg-1"
        vendorDisplayName="OpenAI"
        availableModels={AVAILABLE}
      />,
    )

    // Enter a limit value but skip period selection
    const limitInput = screen.getByTestId('add-guardrail-limit')
    fireEvent.change(limitInput, { target: { value: '100' } })

    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))

    await waitFor(() => {
      expect(shared.mockPost).not.toHaveBeenCalled()
    })
    expect(
      await screen.findByTestId('add-guardrail-period-error'),
    ).toBeDefined()
  })

  it('shows a validation error when no limit is entered', async () => {
    const { AddGuardrailForm } = await import('../components/agents/AddGuardrailForm')
    renderForm(
      <AddGuardrailForm
        model={MODEL_NO_GUARDRAILS}
        vendorConfigId="cfg-1"
        vendorDisplayName="OpenAI"
        availableModels={AVAILABLE}
      />,
    )

    // Pick a period but skip the limit value
    const periodSelect = screen.getByTestId('add-guardrail-period')
    const periodCombobox = periodSelect.parentElement?.querySelector('[role="combobox"]') as HTMLElement
    fireEvent.mouseDown(periodCombobox)
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'hour' })).toBeDefined()
    })
    fireEvent.click(screen.getByRole('option', { name: 'hour' }))

    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))

    await waitFor(() => {
      expect(shared.mockPost).not.toHaveBeenCalled()
    })
    // The FormHelperText gets role="alert" when there's a validation error
    const alerts = await screen.findAllByRole('alert')
    expect(alerts.length).toBeGreaterThanOrEqual(1)
    const limitError = alerts.find((el) => (el.textContent ?? '').includes('LimitRequired'))
    expect(limitError).toBeDefined()
  })
})

describe('AddGuardrailForm - error rendering', () => {
  it('surfaces a 403 permission-denied error via PermissionDeniedAlert', async () => {
    shared.mockPost.mockRejectedValue({
      response: {
        status: 403,
        data: {
          detail: {
            detail: 'Permission Denied',
            required_permission: {
              resource_type: 'model_guardrail_configuration',
              action: 'create',
            },
          },
        },
      },
    })
    const { AddGuardrailForm } = await import('../components/agents/AddGuardrailForm')
    renderForm(
      <AddGuardrailForm
        model={MODEL_NO_GUARDRAILS}
        vendorConfigId="cfg-1"
        vendorDisplayName="OpenAI"
        availableModels={AVAILABLE}
      />,
    )

    // Pick period=hour and a limit
    const periodSelect = screen.getByTestId('add-guardrail-period')
    const periodCombobox = periodSelect.parentElement?.querySelector('[role="combobox"]') as HTMLElement
    fireEvent.mouseDown(periodCombobox)
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'hour' })).toBeDefined()
    })
    fireEvent.click(screen.getByRole('option', { name: 'hour' }))

    const limitInput = screen.getByTestId('add-guardrail-limit')
    fireEvent.change(limitInput, { target: { value: '100' } })

    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))

    // Wait for the rejected mutation to render an alert
    await waitFor(
      () => {
        expect(shared.mockPost).toHaveBeenCalled()
      },
      { timeout: 5000 },
    )
    // The PermissionDeniedAlert renders an MUI Alert with severity=error; it
    // is part of the DOM after the catch handler sets dialogError.
    await waitFor(
      () => {
        const alerts = document.querySelectorAll('[role="alert"]')
        expect(alerts.length).toBeGreaterThanOrEqual(1)
      },
      { timeout: 5000 },
    )
  })
})
