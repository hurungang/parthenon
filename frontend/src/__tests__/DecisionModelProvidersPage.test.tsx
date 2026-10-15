/**
 * Decision Model Providers settings page — multi-provider CRUD UX,
 * per-model availability toggles + vendor cascade, dialog error handling,
 * and the terminology rename sweep (test-plan §3).
 *
 * Complements SystemOneProviderConfigPage.test.tsx (key semantics,
 * base-URL preset, test-connection) — this file focuses on the
 * decision-model-providers change surface.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import enJson from '../i18n/locales/en.json'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

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
  listDecisionGuardrails: vi.fn(),
  createDecisionGuardrail: vi.fn(),
  updateDecisionGuardrail: vi.fn(),
  deleteDecisionGuardrail: vi.fn(),
  getDecisionGuardrailPosture: vi.fn(),
  SYSTEM_ONE_PRESET_BASE_URL: 'https://api.typesafe.ai/v1/systemone',
}))
vi.mock('../api/systemOneApi', () => apiMock)

const PROVIDERS = [
  {
    id: 'p-1',
    provider_type: 'typesafe',
    display_name: 'Primary Vendor',
    base_url: 'https://api.typesafe.example/v1',
    default_model: 'jev-latest',
    enabled: true,
    enabled_models: ['jev-latest', 'jev-mini'],
    has_api_key: true,
  },
]

const HIERARCHY = [
  {
    provider_id: 'p-1',
    display_name: 'Primary Vendor',
    provider_type: 'typesafe',
    default_model: 'jev-latest',
    is_disabled: false,
    models: [
      {
        availability_id: 'av-1',
        model_name: 'jev-latest',
        effective_is_disabled: false,
        disabled_reason: 'manual',
      },
      {
        availability_id: 'av-2',
        model_name: 'jev-mini',
        effective_is_disabled: true,
        disabled_reason: 'vendor_cascaded',
      },
    ],
  },
]

const GUARDRAIL = {
  id: 'g-1',
  decision_provider_id: 'p-1',
  model_id: null,
  model_name: 'jev-latest',
  period: 'day',
  limit_value: 100,
  unit: 'k',
  enforcement_posture: 'terminate',
  is_active: true,
  details: {},
  created_at: '2026-10-14T00:00:00Z',
  updated_at: '2026-10-14T00:00:00Z',
}

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

describe('DecisionModelProvidersPage (settings page)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.listSystemOneProviders.mockResolvedValue(PROVIDERS)
    apiMock.listDecisionModelHierarchy.mockResolvedValue(HIERARCHY)
    apiMock.listEnabledDecisionModels.mockResolvedValue([])
    apiMock.setProviderAvailability.mockResolvedValue({})
    apiMock.setDecisionModelAvailability.mockResolvedValue(undefined)
    apiMock.createSystemOneProvider.mockResolvedValue(PROVIDERS[0])
    apiMock.updateSystemOneProvider.mockResolvedValue(PROVIDERS[0])
    apiMock.deleteSystemOneProvider.mockResolvedValue(undefined)
    apiMock.listSystemOneProviderTypes.mockResolvedValue([
      { value: 'typesafe', label: 'typesafe' },
    ])
    apiMock.listVendorModels.mockResolvedValue({ models: [] })
    apiMock.importVendorModels.mockResolvedValue(PROVIDERS[0])
    apiMock.listDecisionGuardrails.mockResolvedValue([GUARDRAIL])
    apiMock.getDecisionGuardrailPosture.mockResolvedValue([])
    apiMock.createDecisionGuardrail.mockResolvedValue(GUARDRAIL)
    apiMock.updateDecisionGuardrail.mockResolvedValue(GUARDRAIL)
    apiMock.deleteDecisionGuardrail.mockResolvedValue(undefined)
  })

  // ── Terminology rename sweep ───────────────────────────────────────────

  it('renders the page header through the i18n title key (Decision Model Providers)', async () => {
    await renderPage()
    expect(await screen.findByText('systemOne.title')).toBeInTheDocument()
    // the add-provider entry point is present (nav/CTA surface)
    expect(screen.getByText('systemOne.addProvider')).toBeInTheDocument()
  })

  it('terminology sweep: en.json contains no user-visible "System One Provider(s)" string', () => {
    const offenders: string[] = []
    const walk = (node: unknown, path: string) => {
      if (typeof node === 'string') {
        if (/system\s*one\s+providers?/i.test(node)) offenders.push(`${path}: ${node}`)
      } else if (node && typeof node === 'object') {
        for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
          walk(v, `${path}.${k}`)
        }
      }
    }
    walk(enJson, 'en')
    expect(offenders).toEqual([])
  })

  it('terminology sweep: empty state and delete-confirm copy use the new term keys', async () => {
    apiMock.listSystemOneProviders.mockResolvedValue([])
    await renderPage()
    expect(await screen.findByText('systemOne.noProviders')).toBeInTheDocument()
    // both copy keys route through systemOne.* (no hardcoded strings)
    expect(screen.getByText('systemOne.status.notConfigured')).toBeInTheDocument()
  })

  // ── Model catalogue lives ONLY in the editor dialog (drawer removed) ───

  it('renders a lean table: NO inline expandable model catalogue per row', async () => {
    await renderPage()
    await screen.findByText('Primary Vendor')
    // the only expand icon on the page belongs to the collapsed guardrail
    // section toggle — provider rows have no inline model catalogue
    expect(screen.getAllByTestId('ExpandMoreIcon')).toHaveLength(1)
    // the vendor-cascade switch (drawer-only) is gone from the page
    expect(screen.queryByText('systemOne.vendorEnabledCascade')).not.toBeInTheDocument()
    // the hierarchy endpoint is no longer queried for the row catalogue;
    // per-model availability switches are not rendered inline
    expect(
      screen.queryByText('systemOne.cascadedFromVendor'),
    ).not.toBeInTheDocument()
  })

  // ── Embedded guardrail management (FIX-20261014-003000) ────────────────

  it('points users at the embedded guardrail section, not Model Configurations', async () => {
    await renderPage()
    expect(
      await screen.findByText('systemOne.guardrailsTitle'),
    ).toBeInTheDocument()
    // the old "jump to Model Configurations" alert is gone
    expect(screen.queryByText('systemOne.guardrailInfo')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: 'systemOne.guardrailInfoLink' }),
    ).not.toBeInTheDocument()
  })

  it('embedded guardrail section renders the reused panel with decision-scoped data', async () => {
    await renderPage()
    fireEvent.click(await screen.findByText('systemOne.guardrailsTitle'))
    const section = await screen.findByTestId('guardrails-section')
    expect(section).toBeInTheDocument()
    // the reused guardrail panel renders inside the section
    const panel = await screen.findByTestId('vendor-model-guardrail-panel')
    expect(panel).toBeInTheDocument()
    // decision-scoped provider hierarchy is shown (provider + models)
    expect((await screen.findAllByText('Primary Vendor')).length).toBeGreaterThan(0)
    // decision guardrails fetched via the decision-scoped endpoint
    await waitFor(() => {
      expect(apiMock.listDecisionGuardrails).toHaveBeenCalledWith('p-1')
    })
    expect(apiMock.getDecisionGuardrailPosture).toHaveBeenCalledWith('p-1', true)
  })

  it('guardrail CRUD via the embedded panel hits the decision endpoints only', async () => {
    await renderPage()
    fireEvent.click(await screen.findByText('systemOne.guardrailsTitle'))
    // expand the model row and toggle the guardrail's active switch
    const expand = await screen.findByTestId('model-expand-p-1:jev-latest')
    fireEvent.click(expand)
    const switchRow = await screen.findByTestId('guardrail-switch-g-1')
    const switchInput = switchRow.querySelector('input[type="checkbox"]')
    expect(switchInput).not.toBeNull()
    fireEvent.click(switchInput as Element)
    await waitFor(() => {
      expect(apiMock.updateDecisionGuardrail).toHaveBeenCalledWith('g-1', {
        is_active: false,
      })
    })
  })

  // ── Delete flow (confirm + error standard) ─────────────────────────────

  it('delete confirmation dialog cancel does NOT call the API', async () => {
    await renderPage()
    await screen.findByText('Primary Vendor')
    fireEvent.click(screen.getAllByTestId('DeleteIcon')[0].closest('button')!)
    fireEvent.click(await screen.findByRole('button', { name: 'app.cancel' }))
    expect(apiMock.deleteSystemOneProvider).not.toHaveBeenCalled()
  })

  it('delete-blocking error (provider referenced by tools) shows INSIDE the dialog', async () => {
    apiMock.deleteSystemOneProvider.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: 'Provider cannot be deleted while decision tools reference its models' },
      },
    })
    await renderPage()
    await screen.findByText('Primary Vendor')
    fireEvent.click(screen.getAllByTestId('DeleteIcon')[0].closest('button')!)
    fireEvent.click(await screen.findByRole('button', { name: 'app.delete' }))
    await waitFor(() => {
      expect(apiMock.deleteSystemOneProvider).toHaveBeenCalledWith('p-1')
    })
    // the blocking-reference error is rendered INSIDE the still-open dialog
    await waitFor(() => {
      expect(
        screen.getByText(/decision tools reference its models/),
      ).toBeInTheDocument()
    })
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  // ── Create + auto-refresh ──────────────────────────────────────────────

  it('create succeeds → dialog closes, success notification shown, providers refetched', async () => {
    await renderPage()
    fireEvent.click(await screen.findByText('systemOne.addProvider'))
    fireEvent.change(screen.getByLabelText(/systemOne\.displayName/), {
      target: { value: 'Second Vendor' },
    })
    fireEvent.change(screen.getByLabelText(/systemOne\.apiKey/), {
      target: { value: 'sk-second' },
    })
    fireEvent.click(screen.getByText('app.save'))
    await waitFor(() => {
      expect(apiMock.createSystemOneProvider).toHaveBeenCalledTimes(1)
    })
    // dialog closed (only the page-level add button remains)
    await waitFor(() => {
      expect(screen.getAllByText('systemOne.addProvider')).toHaveLength(1)
    })
    expect(screen.getByText('systemOne.saveSuccess')).toBeInTheDocument()
    // parent table refetched automatically (no page reload)
    await waitFor(() => {
      expect(apiMock.listSystemOneProviders.mock.calls.length).toBeGreaterThan(1)
    })
  })

  it('duplicate-provider API error shows inside the create dialog', async () => {
    apiMock.createSystemOneProvider.mockRejectedValue({
      response: { status: 409, data: { detail: 'already exists' } },
    })
    await renderPage()
    fireEvent.click(await screen.findByText('systemOne.addProvider'))
    fireEvent.change(screen.getByLabelText(/systemOne\.displayName/), {
      target: { value: 'Duplicate Vendor' },
    })
    fireEvent.change(screen.getByLabelText(/systemOne\.apiKey/), {
      target: { value: 'sk-dup' },
    })
    fireEvent.click(screen.getByText('app.save'))
    await waitFor(() => {
      expect(apiMock.createSystemOneProvider).toHaveBeenCalled()
    })
    // dialog stays open with a visible error (the API detail message)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect((await screen.findAllByText('already exists')).length).toBeGreaterThan(0)
  })

  it('sends the selected enabled-model chips in the payload (multi-select)', async () => {
    await renderPage()
    fireEvent.click(await screen.findByText('systemOne.addProvider'))
    fireEvent.change(screen.getByLabelText(/systemOne\.displayName/), {
      target: { value: 'Catalogued' },
    })
    fireEvent.change(screen.getByLabelText(/systemOne\.apiKey/), {
      target: { value: 'sk-cat' },
    })
    // type + Enter adds chips via the freeSolo multi-select
    const modelsInput = screen.getByLabelText(/systemOne\.enabledModels/)
    fireEvent.change(modelsInput, { target: { value: 'm-one' } })
    fireEvent.keyDown(modelsInput, { key: 'Enter' })
    fireEvent.change(modelsInput, { target: { value: 'm-two' } })
    fireEvent.keyDown(modelsInput, { key: 'Enter' })
    // default_model is now gated on the chips — pick one
    fireEvent.change(screen.getByLabelText(/systemOne\.defaultModel/), {
      target: { value: 'm-one' },
    })
    fireEvent.click(screen.getByText('app.save'))
    await waitFor(() => {
      expect(apiMock.createSystemOneProvider).toHaveBeenCalled()
    })
    expect(apiMock.createSystemOneProvider.mock.calls[0][0]).toMatchObject({
      enabled_models: ['m-one', 'm-two'],
    })
  })

  // ── FIX-20261014-002300: enabled models as a selection control ─────────

  it('default-model select is disabled until an enabled model is selected; then shows only the chips', async () => {
    await renderPage()
    fireEvent.click(await screen.findByText('systemOne.addProvider'))
    // nothing selected yet → default_model must not be selectable
    const modelField = screen.getByLabelText(/systemOne\.defaultModel/)
    expect(modelField).toBeDisabled()
    expect(screen.getByText('systemOne.defaultModelSyncFirst')).toBeInTheDocument()
    // select an enabled model → default becomes selectable and offers it
    const modelsInput = screen.getByLabelText(/systemOne\.enabledModels/)
    fireEvent.change(modelsInput, { target: { value: 'm-one' } })
    fireEvent.keyDown(modelsInput, { key: 'Enter' })
    const enabledField = screen.getByLabelText(/systemOne\.defaultModel/)
    expect(enabledField).not.toBeDisabled()
    expect(screen.getByRole('option', { name: 'm-one' })).toBeInTheDocument()
  })

  it('removing the default model from the enabled chips clears the default', async () => {
    await renderPage()
    await screen.findByText('Primary Vendor')
    fireEvent.click(screen.getAllByRole('button', { name: 'app.edit' })[0])
    // provider: enabled [jev-latest, jev-mini], default jev-latest
    expect(screen.getByLabelText(/systemOne\.defaultModel/)).toHaveValue('jev-latest')
    // delete the jev-latest chip (first chip in selection order)
    fireEvent.click(screen.getAllByTestId('CancelIcon')[0])
    // the default is cleared — never left stale on a removed model
    expect(screen.getByLabelText(/systemOne\.defaultModel/)).toHaveValue('')
  })

  // ── Vendor type selection (Issue 1) ────────────────────────────────────

  it('create dialog offers vendor types from the backend and sends the selection', async () => {
    apiMock.listSystemOneProviderTypes.mockResolvedValue([
      { value: 'typesafe', label: 'typesafe' },
    ])
    await renderPage()
    fireEvent.click(await screen.findByText('systemOne.addProvider'))
    // The select is rendered with the vendor-type label and is NOT disabled.
    const typeField = screen.getByLabelText(/systemOne\.vendorType/)
    expect(typeField).not.toBeDisabled()
    fireEvent.change(screen.getByLabelText(/systemOne\.displayName/), {
      target: { value: 'Typed Vendor' },
    })
    fireEvent.change(screen.getByLabelText(/systemOne\.apiKey/), {
      target: { value: 'sk-typed' },
    })
    fireEvent.click(screen.getByText('app.save'))
    await waitFor(() => {
      expect(apiMock.createSystemOneProvider).toHaveBeenCalledTimes(1)
    })
    expect(apiMock.createSystemOneProvider.mock.calls[0][0]).toMatchObject({
      provider_type: 'typesafe',
    })
  })

  it('locks the vendor type on edit with the locked helper text', async () => {
    await renderPage()
    await screen.findByText('Primary Vendor')
    fireEvent.click(screen.getAllByRole('button', { name: 'app.edit' })[0])
    const typeField = screen.getByLabelText(/systemOne\.vendorType/)
    expect(typeField).toBeDisabled()
    expect(
      screen.getByText('systemOne.providerTypeLockedHint'),
    ).toBeInTheDocument()
  })

  // ── Vendor model sync (Issue 2) + default-model select (Issue 3) ───────

  it('edit dialog default-model is a select over the provider catalogue', async () => {
    await renderPage()
    await screen.findByText('Primary Vendor')
    fireEvent.click(screen.getAllByRole('button', { name: 'app.edit' })[0])
    const modelField = screen.getByLabelText(/systemOne\.defaultModel/)
    expect(modelField).toHaveValue('jev-latest')
    // catalogue models offered as select options
    expect(screen.getAllByRole('option', { name: 'jev-mini' }).length).toBeGreaterThan(0)
  })

  it('sync button discovers vendor models and imports them; default select refreshes', async () => {
    apiMock.listVendorModels.mockResolvedValue({
      models: ['jev-latest', 'jev-pro', 'jev-mini'],
    })
    await renderPage()
    await screen.findByText('Primary Vendor')
    fireEvent.click(screen.getAllByRole('button', { name: 'app.edit' })[0])
    fireEvent.click(
      await screen.findByRole('button', { name: 'systemOne.syncModels' }),
    )
    await waitFor(() => {
      expect(apiMock.listVendorModels).toHaveBeenCalledWith('p-1')
    })
    await waitFor(() => {
      expect(apiMock.importVendorModels).toHaveBeenCalledWith('p-1', [
        'jev-latest',
        'jev-pro',
        'jev-mini',
      ])
    })
    // imported model becomes selectable in the default-model select
    expect(
      await screen.findAllByRole('option', { name: 'jev-pro' }).then((r) => r.length),
    ).toBeGreaterThan(0)
  })

  it('vendor sync failure shows an actionable error inside the dialog', async () => {
    apiMock.listVendorModels.mockRejectedValue({
      response: { status: 502, data: { detail: 'the API key was rejected' } },
    })
    await renderPage()
    await screen.findByText('Primary Vendor')
    fireEvent.click(screen.getAllByRole('button', { name: 'app.edit' })[0])
    fireEvent.click(
      await screen.findByRole('button', { name: 'systemOne.syncModels' }),
    )
    expect(
      await screen.findAllByText('the API key was rejected').then((r) => r.length),
    ).toBeGreaterThan(0)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  // ── FIX-20261014-001900: default_model gated on enabled models ─────────
  // EXPECTED TO FAIL against current code (reproduction tests).

  it('default-model select is disabled when NO models are enabled', async () => {
    apiMock.listSystemOneProviders.mockResolvedValue([
      { ...PROVIDERS[0], enabled_models: [], default_model: 'jev-latest' },
    ])
    await renderPage()
    await screen.findByText('Primary Vendor')
    fireEvent.click(screen.getAllByRole('button', { name: 'app.edit' })[0])
    const modelField = screen.getByLabelText(/systemOne\.defaultModel/)
    // no enabled models → default_model must not be selectable at all
    expect(modelField).toBeDisabled()
  })

  it('default-model options are restricted to the enabled models only', async () => {
    // hierarchy still knows jev-mini (cascaded), but only jev-latest is
    // enabled → the select must offer ONLY enabled models
    apiMock.listSystemOneProviders.mockResolvedValue([
      { ...PROVIDERS[0], enabled_models: ['jev-latest'] },
    ])
    await renderPage()
    await screen.findByText('Primary Vendor')
    fireEvent.click(screen.getAllByRole('button', { name: 'app.edit' })[0])
    const options = screen.getAllByRole('option').map((o) => o.textContent)
    expect(options).toContain('jev-latest')
    expect(options).not.toContain('jev-mini')
  })
})
