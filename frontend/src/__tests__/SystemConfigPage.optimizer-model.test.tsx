import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import type { OptimizerModelConfig } from '../types'

/**
 * System Config — Optimizer Model (workspace-scoped).
 *
 * Covers the operator contract for the model that powers the optimization-mode
 * conversation: workspace scope, inherit-from-authoring default, catalogue-only
 * options (no substitution), unset / stale reminders, save + clear-to-inherit,
 * stale-save blocking and the 422 dialog-error standard.
 */

// Only placeholder-carrying strings are resolved; everything else falls back to
// the key so assertions can use the raw i18n key.
const STRINGS: Record<string, string> = {
  'systemConfig.optimizerReminderUnavailable':
    'The saved optimizer model “{{modelId}}” is no longer available in this workspace. Re-select an enabled model to save.',
  'systemConfig.optimizerUnavailableOption': '{{modelId}} — no longer available',
  'systemConfig.optimizerStateInherited': 'Inheriting “{{modelId}}” from the plan authoring model.',
  'systemConfig.optimizerStateSelected': 'Optimization runs on “{{modelId}}”.',
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, params?: Record<string, unknown>) => {
      let out = STRINGS[k] ?? k
      if (params) {
        for (const [key, value] of Object.entries(params)) {
          out = out.split(`{{${key}}}`).join(String(value))
        }
      }
      return out
    },
  }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn(),
    put: vi.fn(),
  },
}))

import apiClient from '../api/apiClient'
import { SystemConfigPage } from '../pages/system/SystemConfigPage'

const getMock = vi.mocked(apiClient.get)
const putMock = vi.mocked(apiClient.put)

const OPTIONS: OptimizerModelConfig['options'] = [
  {
    model_id: 'gpt-4o',
    config_id: 'cfg-1',
    config_display_name: 'OpenAI Prod',
    provider_type: 'openai',
  },
  {
    model_id: 'claude-sonnet',
    config_id: 'cfg-2',
    config_display_name: 'Anthropic',
    provider_type: 'anthropic',
  },
]

/** Mutable "stored" optimizer config so save + refetch can be asserted. */
let storedOptimizer: OptimizerModelConfig = {
  selected_model_id: null,
  effective_model_id: 'gpt-4o',
  source: 'authoring',
  configured: true,
  enabled: true,
  reason_code: null,
  options: OPTIONS,
}

function mockConfigs(overrides: Partial<OptimizerModelConfig> = {}) {
  getMock.mockImplementation((url: string) => {
    if (url === '/agents/model-configs/optimizer-model') {
      return Promise.resolve({ data: { ...storedOptimizer, ...overrides } })
    }
    if (url === '/agents/model-configs/workflow-generation') {
      return Promise.resolve({
        data: { selected_model_id: 'gpt-4o', options: OPTIONS },
      })
    }
    if (url === '/agents/model-configs/assistant-model') {
      return Promise.resolve({ data: { selected_model_id: null, options: [] } })
    }
    return Promise.resolve({ data: {} })
  })
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

/** Opens the optimizer-model Select and picks an option by its label. */
async function pickOptimizerModel(label: string) {
  // The optimizer section is rendered first, so its combobox is index 0.
  const selects = await screen.findAllByRole('combobox')
  fireEvent.mouseDown(selects[0])
  const option = await screen.findByRole('option', { name: label })
  fireEvent.click(option)
}

describe('SystemConfigPage — optimizer model', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    storedOptimizer = {
      selected_model_id: null,
      effective_model_id: 'gpt-4o',
      source: 'authoring',
      configured: true,
      enabled: true,
      reason_code: null,
      options: OPTIONS,
    }
    putMock.mockResolvedValue({ data: storedOptimizer } as never)
    mockConfigs()
  })

  it('loads the workspace optimizer-model setting from its tenant-scoped endpoint', async () => {
    render(<SystemConfigPage />, { wrapper })

    await waitFor(() => {
      expect(getMock).toHaveBeenCalledWith('/agents/model-configs/optimizer-model')
    })
  })

  it('explains what the model powers and that it is workspace-scoped (not a runtime model)', async () => {
    render(<SystemConfigPage />, { wrapper })

    const section = await screen.findByTestId('optimizer-model-section')
    expect(section.textContent).toContain('systemConfig.optimizerSection')
    // Workspace scope chip.
    expect(within(section).getByTestId('optimizer-model-scope').textContent).toBe(
      'systemConfig.optimizerScope',
    )
    // It powers the optimization conversation — separate from runtime models.
    expect(section.textContent).toContain('systemConfig.optimizerHint')
    expect(section.textContent).toContain('systemConfig.optimizerUsesTitle')
    expect(section.textContent).toContain('systemConfig.optimizerUseConversation')
    // Unset inherits the plan authoring model — one editor, no second setting.
    expect(section.textContent).toContain('systemConfig.optimizerUseInherit')
    // Changing it affects this workspace only.
    expect(section.textContent).toContain('systemConfig.optimizerUseScope')
    // Safety behaviour is explicitly unchanged by this choice.
    expect(within(section).getByTestId('optimizer-model-unchanged').textContent).toBe(
      'systemConfig.optimizerUnchanged',
    )
  })

  it('offers catalogue-only options plus an explicit inherit option', async () => {
    render(<SystemConfigPage />, { wrapper })

    await screen.findAllByRole('combobox')
    fireEvent.mouseDown(screen.getAllByRole('combobox')[0])

    expect(
      await screen.findByRole('option', { name: 'systemConfig.optimizerInheritOption' }),
    ).toBeDefined()
    expect(screen.getByRole('option', { name: 'gpt-4o (OpenAI Prod)' })).toBeDefined()
    expect(screen.getByRole('option', { name: 'claude-sonnet (Anthropic)' })).toBeDefined()
    // Nothing from another workspace's catalogue leaks in.
    expect(screen.queryByText(/other-workspace/i)).toBeNull()
  })

  it('states that no model is ever substituted when the choice is unusable', async () => {
    render(<SystemConfigPage />, { wrapper })

    const note = await screen.findByTestId('optimizer-model-no-substitution')
    expect(note.textContent).toBe('systemConfig.optimizerNoSubstitution')
  })

  it('shows the inherited model state and no reminder when it resolves via authoring', async () => {
    render(<SystemConfigPage />, { wrapper })

    const state = await screen.findByTestId('optimizer-model-state')
    await waitFor(() => {
      expect(state.textContent).toBe(
        'Inheriting “gpt-4o” from the plan authoring model.',
      )
    })
    expect(screen.queryByTestId('optimizer-model-reminder')).toBeNull()
  })

  it('shows a reminder while no usable optimizer model exists', async () => {
    storedOptimizer = {
      selected_model_id: null,
      effective_model_id: null,
      source: null,
      configured: false,
      enabled: false,
      reason_code: 'optimizer_model_not_configured',
      options: OPTIONS,
    }
    mockConfigs()

    render(<SystemConfigPage />, { wrapper })

    const reminder = await screen.findByTestId('optimizer-model-reminder')
    expect(reminder.textContent).toBe('systemConfig.optimizerReminderUnset')
    expect(screen.getByTestId('optimizer-model-state').textContent).toBe(
      'systemConfig.optimizerStateBlocked',
    )
  })

  it('flags a stale saved value, keeps it visible, and blocks Save until re-selected', async () => {
    storedOptimizer = {
      selected_model_id: 'retired-model',
      effective_model_id: null,
      source: 'optimizer',
      configured: false,
      enabled: false,
      reason_code: 'optimizer_model_not_enabled',
      options: OPTIONS,
    }
    mockConfigs()

    render(<SystemConfigPage />, { wrapper })

    const reminder = await screen.findByTestId('optimizer-model-reminder')
    expect(reminder.textContent).toContain('retired-model')
    expect(reminder.textContent).toContain('no longer available')

    // A stale value can never be re-submitted as-is.
    expect(
      (screen.getByTestId('optimizer-model-save') as HTMLButtonElement).disabled,
    ).toBe(true)

    // The stale id stays visible as a disabled option (never auto-cleared).
    const selects = screen.getAllByRole('combobox')
    fireEvent.mouseDown(selects[0])
    const staleOption = await screen.findByRole('option', {
      name: 'retired-model — no longer available',
    })
    expect(staleOption.getAttribute('aria-disabled')).toBe('true')
  })

  it('saves an enabled catalogue model and reflects the new derived state', async () => {
    render(<SystemConfigPage />, { wrapper })

    await screen.findAllByRole('combobox')
    await pickOptimizerModel('claude-sonnet (Anthropic)')

    // Saving the (still stored) inherit value would clear; picking an explicit
    // model saves that id.
    storedOptimizer = {
      ...storedOptimizer,
      selected_model_id: 'claude-sonnet',
      effective_model_id: 'claude-sonnet',
      source: 'optimizer',
    }
    fireEvent.click(screen.getByTestId('optimizer-model-save'))

    await waitFor(() => {
      expect(putMock).toHaveBeenCalledWith('/agents/model-configs/optimizer-model', {
        model_id: 'claude-sonnet',
      })
    })
    expect(putMock).toHaveBeenCalledTimes(1)

    await waitFor(() => {
      expect(screen.getByTestId('optimizer-model-state').textContent).toBe(
        'Optimization runs on “claude-sonnet”.',
      )
    })
  })

  it('clears back to inherit with null when the inherit option is chosen', async () => {
    storedOptimizer = {
      ...storedOptimizer,
      selected_model_id: 'gpt-4o',
      effective_model_id: 'gpt-4o',
      source: 'optimizer',
    }
    mockConfigs()

    render(<SystemConfigPage />, { wrapper })

    await screen.findAllByRole('combobox')
    await pickOptimizerModel('systemConfig.optimizerInheritOption')

    fireEvent.click(screen.getByTestId('optimizer-model-save'))

    await waitFor(() => {
      expect(putMock).toHaveBeenCalledWith('/agents/model-configs/optimizer-model', {
        model_id: null,
      })
    })
  })

  it('surfaces a rejected save (422 not-enabled model) via the dialog error standard', async () => {
    putMock.mockRejectedValue({
      response: {
        status: 422,
        data: { detail: 'Model is not enabled in this workspace' },
      },
    })

    render(<SystemConfigPage />, { wrapper })

    await screen.findAllByRole('combobox')
    fireEvent.click(screen.getByTestId('optimizer-model-save'))

    expect(await screen.findByText('Model is not enabled in this workspace')).toBeDefined()
    // Nothing was "saved": no success path, and the selection surface is intact.
    expect(screen.getByTestId('optimizer-model-select')).toBeDefined()
  })

  it('explains when the workspace catalogue has no models at all', async () => {
    storedOptimizer = {
      selected_model_id: null,
      effective_model_id: null,
      source: null,
      configured: false,
      enabled: false,
      reason_code: 'optimizer_model_not_configured',
      options: [],
    }
    mockConfigs()

    render(<SystemConfigPage />, { wrapper })

    expect(await screen.findByText('systemConfig.optimizerNoOptions')).toBeDefined()
    expect(screen.queryByTestId('optimizer-model-save')).toBeNull()
  })
})
