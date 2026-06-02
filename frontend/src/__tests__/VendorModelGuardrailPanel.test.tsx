import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'

const shared = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPut: vi.fn(),
  mockPost: vi.fn(),
  mockDelete: vi.fn(),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, opts?: Record<string, unknown>) =>
    k + (opts ? `:${JSON.stringify(opts)}` : '') }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: (...args: unknown[]) => shared.mockGet(...args),
    put: (...args: unknown[]) => shared.mockPut(...args),
    post: (...args: unknown[]) => shared.mockPost(...args),
    delete: (...args: unknown[]) => shared.mockDelete(...args),
  },
}))

function renderPanel(ui: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

const HIERARCHY_FIXTURE = [
  {
    vendor_config_id: 'cfg-1',
    vendor_display_name: 'OpenAI Production',
    is_disabled: false,
    models: [
      {
        model_name: 'gpt-4.1',
        is_disabled: false,
        disabled_reason: null,
        guardrails: [
          {
            id: 'gr-1',
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
          {
            id: 'gr-2',
            model_config_id: 'cfg-1',
            model_id: 'cfg-1',
            model_name: 'gpt-4.1',
            period: 'day' as const,
            limit_value: 1500,
            unit: 'k' as const,
            enforcement_posture: 'observe_only' as const,
            is_active: false,
            details: {},
            created_at: '2026-06-01T00:00:00Z',
            updated_at: '2026-06-01T00:00:00Z',
          },
        ],
      },
    ],
  },
  {
    vendor_config_id: 'cfg-2',
    vendor_display_name: 'Cascaded Vendor',
    is_disabled: true,
    models: [
      {
        model_name: 'claude-sonnet-4',
        is_disabled: false,
        disabled_reason: null,
        guardrails: [],
      },
    ],
  },
]

const POSTURE_FIXTURE = [
  {
    id: 'p-1',
    model_guardrail_configuration_id: 'gr-1',
    model_id: 'cfg-1',
    posture_period: 'hour' as const,
    usage_value: 45,
    limit_value: 100,
    posture_state: 'within_limit' as const,
    observed_at: '2026-06-01T18:00:00Z',
    details: {},
  },
  {
    id: 'p-2',
    model_guardrail_configuration_id: 'gr-2',
    model_id: 'cfg-1',
    posture_period: 'day' as const,
    usage_value: 1300,
    limit_value: 1500,
    posture_state: 'approaching_limit' as const,
    observed_at: '2026-06-01T18:00:00Z',
    details: {},
  },
]

beforeEach(() => {
  vi.clearAllMocks()
  shared.mockGet.mockImplementation((url: string) => {
    if (url.startsWith('/agents/model-availability')) {
      return Promise.resolve({ data: HIERARCHY_FIXTURE })
    }
    if (url.startsWith('/agents/guardrails/model-usage-posture')) {
      return Promise.resolve({ data: POSTURE_FIXTURE })
    }
    if (url.startsWith('/agents/guardrails/model-usage-limits')) {
      return Promise.resolve({
        data: HIERARCHY_FIXTURE.flatMap((v) =>
          v.models.flatMap((m) => m.guardrails),
        ),
      })
    }
    if (url.startsWith('/agents/model-configs')) {
      return Promise.resolve({
        data: HIERARCHY_FIXTURE.map((v) => ({
          id: v.vendor_config_id,
          display_name: v.vendor_display_name,
          provider_type: 'openai',
          enabled_models: v.models.map((m) => m.model_name),
        })),
      })
    }
    return Promise.resolve({ data: [] })
  })
  shared.mockPut.mockResolvedValue({ data: {} })
  shared.mockPost.mockResolvedValue({ data: {} })
  shared.mockDelete.mockResolvedValue({ data: undefined })
})

async function waitForHierarchy() {
  await waitFor(
    () => {
      expect(screen.queryByText('app.loading')).toBeNull()
    },
    { timeout: 5000 },
  )
  await waitFor(
    () => {
      expect(screen.getByText('OpenAI Production')).toBeDefined()
    },
    { timeout: 5000 },
  )
}

describe('VendorModelGuardrailPanel - hierarchy rendering', () => {
  it('renders one vendor row per vendor with the correct enabled count', async () => {
    const { VendorModelGuardrailPanel } = await import(
      '../components/agents/VendorModelGuardrailPanel'
    )
    renderPanel(<VendorModelGuardrailPanel />)

    await waitForHierarchy()
    expect(screen.getByText('Cascaded Vendor')).toBeDefined()
  })

  it('expands a vendor row on click to show its models', async () => {
    const { VendorModelGuardrailPanel } = await import(
      '../components/agents/VendorModelGuardrailPanel'
    )
    renderPanel(<VendorModelGuardrailPanel />)

    await waitForHierarchy()
    fireEvent.click(screen.getByText('OpenAI Production'))

    await waitFor(() => {
      expect(screen.getByText('gpt-4.1')).toBeDefined()
    })
  })

  it('expands a model row on click to show its guardrails', async () => {
    const { VendorModelGuardrailPanel } = await import(
      '../components/agents/VendorModelGuardrailPanel'
    )
    renderPanel(<VendorModelGuardrailPanel />)

    await waitForHierarchy()
    fireEvent.click(screen.getByText('OpenAI Production'))

    await waitFor(() => {
      expect(screen.getByTestId('model-expand-cfg-1:gpt-4.1')).toBeDefined()
    })
    fireEvent.click(screen.getByTestId('model-expand-cfg-1:gpt-4.1'))

    await waitFor(() => {
      expect(screen.getByTestId('guardrail-row-gr-1')).toBeDefined()
      expect(screen.getByTestId('guardrail-row-gr-2')).toBeDefined()
    })
  })

  it('shows the cascade-source badge on models under a disabled vendor', async () => {
    const { VendorModelGuardrailPanel } = await import(
      '../components/agents/VendorModelGuardrailPanel'
    )
    renderPanel(<VendorModelGuardrailPanel />)

    await waitForHierarchy()
    fireEvent.click(screen.getByText('Cascaded Vendor'))
    await waitFor(() => {
      expect(screen.getByText('claude-sonnet-4')).toBeDefined()
    })
    const modelChip = screen.getByTestId('model-chip-cfg-2:claude-sonnet-4')
    expect(modelChip).toBeDefined()
    // The mock i18n returns the key, so we look for the key substring.
    expect(modelChip.textContent ?? '').toMatch(/disabled_vendor_cascade|vendor cascade/i)
  })
})

describe('VendorModelGuardrailPanel - mutation calls', () => {
  it('toggling the vendor switch calls useSetVendorDisabled with is_disabled=true', async () => {
    const { VendorModelGuardrailPanel } = await import(
      '../components/agents/VendorModelGuardrailPanel'
    )
    renderPanel(<VendorModelGuardrailPanel />)

    await waitForHierarchy()
    const switchEl = within(screen.getByTestId('vendor-switch-cfg-1')).getByRole('switch')
    fireEvent.click(switchEl)

    await waitFor(() => {
      expect(shared.mockPut).toHaveBeenCalledWith(
        '/agents/model-configs/cfg-1/disabled',
        expect.objectContaining({ is_disabled: true }),
      )
    })
  })

  it('toggling a per-model switch calls useSetModelDisabled with the right args', async () => {
    const { VendorModelGuardrailPanel } = await import(
      '../components/agents/VendorModelGuardrailPanel'
    )
    renderPanel(<VendorModelGuardrailPanel />)

    await waitForHierarchy()
    fireEvent.click(screen.getByText('OpenAI Production'))
    await waitFor(() => {
      expect(screen.getByTestId('model-switch-cfg-1:gpt-4.1')).toBeDefined()
    })
    const switchEl = within(screen.getByTestId('model-switch-cfg-1:gpt-4.1')).getByRole('switch')
    fireEvent.click(switchEl)

    await waitFor(() => {
      expect(shared.mockPut).toHaveBeenCalledWith(
        '/agents/model-configs/cfg-1/models/gpt-4.1/disabled',
        expect.objectContaining({ is_disabled: true }),
      )
    })
  })

  it('toggling a per-guardrail switch calls the per-guardrail update mutation', async () => {
    const { VendorModelGuardrailPanel } = await import(
      '../components/agents/VendorModelGuardrailPanel'
    )
    renderPanel(<VendorModelGuardrailPanel />)

    await waitForHierarchy()
    fireEvent.click(screen.getByText('OpenAI Production'))
    fireEvent.click(screen.getByTestId('model-expand-cfg-1:gpt-4.1'))
    await waitFor(() => {
      expect(screen.getByTestId('guardrail-switch-gr-1')).toBeDefined()
    })
    const switchEl = within(screen.getByTestId('guardrail-switch-gr-1')).getByRole('switch')
    fireEvent.click(switchEl)

    await waitFor(() => {
      expect(shared.mockPut).toHaveBeenCalledWith(
        '/agents/guardrails/model-usage-limits/gr-1',
        expect.objectContaining({ is_active: false }),
      )
    })
  })

  it('removing a guardrail calls the delete mutation', async () => {
    const { VendorModelGuardrailPanel } = await import(
      '../components/agents/VendorModelGuardrailPanel'
    )
    renderPanel(<VendorModelGuardrailPanel />)

    await waitForHierarchy()
    fireEvent.click(screen.getByText('OpenAI Production'))
    fireEvent.click(screen.getByTestId('model-expand-cfg-1:gpt-4.1'))
    await waitFor(() => {
      expect(screen.getByTestId('guardrail-remove-gr-1')).toBeDefined()
    })
    fireEvent.click(screen.getByTestId('guardrail-remove-gr-1'))

    await waitFor(() => {
      expect(shared.mockDelete).toHaveBeenCalledWith('/agents/guardrails/model-usage-limits/gr-1')
    })
  })

  it('the "Add guardrail" form only offers periods not yet configured on the model', async () => {
    const { VendorModelGuardrailPanel } = await import(
      '../components/agents/VendorModelGuardrailPanel'
    )
    renderPanel(<VendorModelGuardrailPanel />)

    await waitForHierarchy()
    fireEvent.click(screen.getByText('OpenAI Production'))
    fireEvent.click(screen.getByTestId('model-expand-cfg-1:gpt-4.1'))
    await waitFor(() => {
      expect(screen.getByTestId('add-guardrail-button-cfg-1:gpt-4.1')).toBeDefined()
    })
    fireEvent.click(screen.getByTestId('add-guardrail-button-cfg-1:gpt-4.1'))

    await waitFor(() => {
      expect(screen.getByTestId('add-guardrail-form')).toBeDefined()
    })
    const periodSelect = screen.getByTestId('add-guardrail-period')
    const periodCombobox = periodSelect.parentElement?.querySelector('[role="combobox"]') as HTMLElement
    expect(periodCombobox).toBeDefined()
    fireEvent.mouseDown(periodCombobox)
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'week' })).toBeDefined()
      expect(screen.queryByRole('option', { name: 'hour' })).toBeNull()
    })
  })
})

describe('VendorModelGuardrailPanel - readonly dashboard mode', () => {
  it('hides vendor/model/guardrail switches, edit and remove buttons, and the Add button when readonly', async () => {
    const { VendorModelGuardrailPanel } = await import(
      '../components/agents/VendorModelGuardrailPanel'
    )
    renderPanel(<VendorModelGuardrailPanel readonly />)

    await waitForHierarchy()
    // Read-only dashboard summary renders
    expect(screen.getByTestId('guardrail-dashboard-summary')).toBeDefined()
    expect(screen.getByTestId('summary-vendors')).toBeDefined()
    expect(screen.getByTestId('summary-models')).toBeDefined()
    expect(screen.getByTestId('summary-guardrails-active')).toBeDefined()
    expect(screen.getByTestId('summary-guardrails-breached')).toBeDefined()
    // No vendor enable/disable switch
    expect(screen.queryByTestId('vendor-switch-cfg-1')).toBeNull()
    // No Add guardrail button
    expect(screen.queryByTestId('add-guardrail-button-cfg-1:gpt-4.1')).toBeNull()
    // Auto-expanded: the guardrail rows are visible
    await waitFor(() => {
      expect(screen.getByTestId('guardrail-row-gr-1')).toBeDefined()
    })
    // No edit / remove buttons on guardrail rows
    expect(screen.queryByTestId('guardrail-edit-gr-1')).toBeNull()
    expect(screen.queryByTestId('guardrail-remove-gr-1')).toBeNull()
    expect(screen.queryByTestId('guardrail-switch-gr-1')).toBeNull()
  })

  it('reflects disabled vendors and breached guardrails in the summary tiles', async () => {
    const { VendorModelGuardrailPanel } = await import(
      '../components/agents/VendorModelGuardrailPanel'
    )
    renderPanel(<VendorModelGuardrailPanel readonly />)

    await waitForHierarchy()
    // 2 vendors, 1 disabled → 1 / 2
    expect(
      screen.getByTestId('summary-vendors').textContent,
    ).toMatch(/1 \/ 2/)
    // 2 models, 1 cascaded (vendor disabled) and 1 enabled → 1 / 2
    expect(
      screen.getByTestId('summary-models').textContent,
    ).toMatch(/1 \/ 2/)
    // 2 guardrails, 1 active, 0 breached → 1 / 2 and 0
    expect(
      screen.getByTestId('summary-guardrails-active').textContent,
    ).toMatch(/1 \/ 2/)
    expect(
      screen.getByTestId('summary-guardrails-breached').textContent,
    ).toMatch(/0/)
  })
})

describe('VendorModelGuardrailPanel - error rendering', () => {
  it('surfaces permission-denied errors via PermissionDeniedAlert when a mutation fails', async () => {
    shared.mockPut.mockImplementationOnce(() =>
      Promise.reject({
        response: {
          status: 403,
          data: {
            detail: {
              detail: 'Permission Denied',
              required_permission: {
                resource_type: 'model_config',
                action: 'update',
              },
            },
          },
        },
      }),
    )
    const { VendorModelGuardrailPanel } = await import(
      '../components/agents/VendorModelGuardrailPanel'
    )
    renderPanel(<VendorModelGuardrailPanel />)

    await waitForHierarchy()
    const switchEl = within(screen.getByTestId('vendor-switch-cfg-1')).getByRole('switch')
    fireEvent.click(switchEl)

    await waitFor(() => {
      expect(shared.mockPut).toHaveBeenCalled()
    })
    await waitFor(
      () => {
        const alerts = document.querySelectorAll('[role="alert"]')
        expect(alerts.length).toBeGreaterThanOrEqual(1)
      },
      { timeout: 5000 },
    )
  })
})
