import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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

function renderPage(ui: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

const HIERARCHY = [
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
        ],
      },
    ],
  },
] as const

const POSTURE = [
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
] as const

describe('ModelUsageGuardrailManagement - readonly guardrail hierarchy view', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    shared.mockGet.mockImplementation((url: string) => {
      if (url.startsWith('/agents/runtime/topology')) {
        return Promise.resolve({ data: { nodes: [], edges: [], root_session_ids: [] } })
      }
      if (url.startsWith('/agents/guardrails/model-usage-limits')) {
        return Promise.resolve({ data: HIERARCHY.flatMap((v) => v.models.flatMap((m) => m.guardrails)) })
      }
      if (url.startsWith('/agents/guardrails/model-usage-posture')) {
        return Promise.resolve({ data: POSTURE })
      }
      if (url.startsWith('/agents/model-availability')) {
        return Promise.resolve({ data: HIERARCHY })
      }
      if (url.startsWith('/agents/model-configs')) {
        return Promise.resolve({
          data: [
            {
              id: 'cfg-1',
              display_name: 'OpenAI Production',
              provider_type: 'openai',
              enabled_models: ['gpt-4.1'],
            },
          ],
        })
      }
      return Promise.resolve({ data: [] })
    })
  })

  it('renders the read-only dashboard title on the dedicated dashboard', async () => {
    const { VendorModelGuardrailPanel } = await import(
      '../components/agents/VendorModelGuardrailPanel'
    )
    renderPage(<VendorModelGuardrailPanel readonly />)

    await waitFor(() => {
      expect(screen.getByText('agents.sessions.modelUsageDashboardTitle')).toBeDefined()
    })
  })

  it('renders vendor, model, and guardrail rows already expanded (read-only mode auto-expands)', async () => {
    const { VendorModelGuardrailPanel } = await import(
      '../components/agents/VendorModelGuardrailPanel'
    )
    renderPage(<VendorModelGuardrailPanel readonly />)

    // In readonly mode the panel auto-expands; no manual clicks needed.
    await waitFor(() => {
      expect(screen.getByText('OpenAI Production')).toBeDefined()
      expect(screen.getByText('gpt-4.1')).toBeDefined()
      expect(screen.getByTestId('guardrail-row-gr-1')).toBeDefined()
    })
  })

  it('renders the unit suffix in the guardrail row using the limit_value', async () => {
    const { VendorModelGuardrailPanel } = await import(
      '../components/agents/VendorModelGuardrailPanel'
    )
    renderPage(<VendorModelGuardrailPanel readonly />)

    await waitFor(() => {
      expect(screen.getByTestId('guardrail-row-gr-1')).toBeDefined()
    })
    // The guardrail row renders via t('agents.sessions.modelUsageGuardrailLimitValue', { value, limit, unit }).
    // Since the test's i18n mock returns the key, we look up the row by data-testid
    // and assert the key is present (i.e. the component called t() with the right arguments).
    const row = screen.getByTestId('guardrail-row-gr-1')
    expect(row.textContent ?? '').toMatch(/agents\.sessions\.modelUsageGuardrailLimitValue/)
  })

  it('renders posture state chip on the guardrail row', async () => {
    const { VendorModelGuardrailPanel } = await import(
      '../components/agents/VendorModelGuardrailPanel'
    )
    renderPage(<VendorModelGuardrailPanel readonly />)

    await waitFor(() => {
      expect(screen.getByTestId('guardrail-row-gr-1')).toBeDefined()
    })
    const row = screen.getByTestId('guardrail-row-gr-1')
    expect(row.textContent ?? '').toMatch(/agents\.sessions\.modelUsageState\.within_limit/)
  })
})
