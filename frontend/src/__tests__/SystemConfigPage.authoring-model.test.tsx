import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import type { WorkflowGenerationModelConfig } from '../types'

/**
 * System Config — plan & workflow authoring model.
 *
 * Covers the operator guidance contract: the three uses of the single
 * tenant-scoped authoring model, the advisory "choose a larger model"
 * recommendation, the unset / no-longer-available reminder, tenant-scoped
 * options + selection, and the save path (including the 422 error standard).
 */

// Only placeholder-carrying strings are resolved; everything else falls back to
// the key so assertions can use the raw i18n key.
const STRINGS: Record<string, string> = {
  'systemConfig.workflowReminderUnavailable':
    'The saved authoring model “{{modelId}}” is no longer available in this workspace. Re-select an enabled model.',
  'systemConfig.workflowUnavailableOption': '{{modelId}} — no longer available',
  'systemConfig.workflowNoOptions':
    'No model configurations available in this workspace. Add a model configuration first.',
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, params?: Record<string, unknown>) => {
      let out = STRINGS[k] ?? k
      if (params) {
        for (const [key, value] of Object.entries(params)) {
          out = out.replace(`{{${key}}}`, String(value))
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

interface Option {
  model_id: string
  config_id: string
  config_display_name: string
  provider_type: string
}

const WORKSPACE_OPTIONS: Option[] = [
  {
    model_id: 'gpt-4o',
    config_id: 'cfg-1',
    config_display_name: 'OpenAI Prod',
    provider_type: 'openai',
  },
  {
    model_id: 'gpt-4o-mini',
    config_id: 'cfg-1',
    config_display_name: 'OpenAI Mini',
    provider_type: 'openai',
  },
]

/** Mutable "stored" selection so a save + refetch can be asserted. */
let storedWorkflowModelId: string | null = null

function mockWorkflowConfig(overrides: Partial<WorkflowGenerationModelConfig> = {}) {
  getMock.mockImplementation((url: string) => {
    if (url === '/agents/model-configs/workflow-generation') {
      return Promise.resolve({
        data: {
          selected_model_id: storedWorkflowModelId,
          options: WORKSPACE_OPTIONS,
          ...overrides,
        },
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

/** Opens the authoring-model Select and picks an option by its label. */
async function pickWorkflowModel(label: string) {
  const selects = await screen.findAllByRole('combobox')
  fireEvent.mouseDown(selects[0])
  const option = await screen.findByRole('option', { name: label })
  fireEvent.click(option)
}

describe('SystemConfigPage — plan & workflow authoring model', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    storedWorkflowModelId = null
    putMock.mockResolvedValue({ data: {} } as never)
    mockWorkflowConfig()
  })

  it('loads the authoring-model setting from the tenant-scoped endpoint', async () => {
    render(<SystemConfigPage />, { wrapper })

    await waitFor(() => {
      expect(getMock).toHaveBeenCalledWith('/agents/model-configs/workflow-generation')
    })
    // The assistant model keeps its own tenant-scoped endpoint — the authoring
    // model has exactly one setting and one save path.
    expect(getMock).toHaveBeenCalledWith('/agents/model-configs/assistant-model')
  })

  it('explains the three uses and the workspace scope of the choice', async () => {
    render(<SystemConfigPage />, { wrapper })

    const section = await screen.findByTestId('authoring-model-section')
    expect(section.textContent).toContain('systemConfig.workflowSection')
    expect(section.textContent).toContain('systemConfig.workflowUsesTitle')
    // Use 1 — Skill/SOP workflow generation
    expect(within(section).getByText('systemConfig.workflowUseSkills')).toBeDefined()
    // Use 2 — implementation-plan generation
    expect(
      within(section).getByText('systemConfig.workflowUseImplementationPlans'),
    ).toBeDefined()
    // Use 3 — optimization-plan generation
    expect(
      within(section).getByText('systemConfig.workflowUseOptimizationPlans'),
    ).toBeDefined()
    // The choice applies to the current workspace only.
    const scopeNote = within(section).getByTestId('authoring-model-workspace-note')
    expect(scopeNote.textContent).toBe('systemConfig.workflowOptionsScopeNote')
  })

  it('recommends a larger model as advisory and clarifies runtime models are separate', async () => {
    render(<SystemConfigPage />, { wrapper })

    const recommendation = await screen.findByTestId('authoring-model-recommendation')
    expect(recommendation.textContent).toBe('systemConfig.workflowRecommendation')
    // The recommendation is advice, not a gate: a smaller enabled model is
    // still saveable (asserted below).
    await screen.findAllByRole('combobox')
    expect(screen.getByRole('button', { name: 'app.save' })).toBeDefined()
  })

  it('shows a visible reminder while no authoring model is configured', async () => {
    storedWorkflowModelId = null
    render(<SystemConfigPage />, { wrapper })

    const reminder = await screen.findByTestId('authoring-model-reminder')
    expect(reminder.textContent).toBe('systemConfig.workflowReminderUnset')
  })

  it('clears the reminder once a valid model is saved', async () => {
    storedWorkflowModelId = null
    render(<SystemConfigPage />, { wrapper })

    expect(await screen.findByTestId('authoring-model-reminder')).toBeDefined()

    await pickWorkflowModel('gpt-4o (OpenAI Prod)')

    // Saving the (stored) valid selection goes through the single save path.
    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))

    await waitFor(() => {
      expect(putMock).toHaveBeenCalledWith('/agents/model-configs/workflow-generation', {
        model_id: 'gpt-4o',
      })
    })
    expect(putMock).toHaveBeenCalledTimes(1)

    storedWorkflowModelId = 'gpt-4o'
    await waitFor(() => {
      expect(screen.queryByTestId('authoring-model-reminder')).toBeNull()
    })
  })

  it('keeps any enabled model saveable — the larger-model recommendation is advisory', async () => {
    storedWorkflowModelId = 'gpt-4o'
    render(<SystemConfigPage />, { wrapper })

    // A smaller enabled model is offered and selectable.
    await screen.findByTestId('authoring-model-recommendation')
    await screen.findAllByRole('combobox')
    await pickWorkflowModel('gpt-4o-mini (OpenAI Mini)')

    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))

    await waitFor(() => {
      expect(putMock).toHaveBeenCalledWith('/agents/model-configs/workflow-generation', {
        model_id: 'gpt-4o-mini',
      })
    })
    // Nothing blocked the save and no reminder was raised for a valid model.
    expect(screen.queryByTestId('authoring-model-reminder')).toBeNull()
  })

  it('flags a saved model that is no longer in the workspace catalogue and asks to re-select', async () => {
    storedWorkflowModelId = 'retired-model'
    render(<SystemConfigPage />, { wrapper })

    const reminder = await screen.findByTestId('authoring-model-reminder')
    // The stale value is echoed so the operator knows what to replace.
    expect(reminder.textContent).toContain('retired-model')
    expect(reminder.textContent).toContain('no longer available')

    // A stale selection cannot be re-submitted as-is (checked before opening
    // the menu: an open MUI Menu hides the rest of the page from role queries).
    expect(
      (screen.getByRole('button', { name: 'app.save' }) as HTMLButtonElement).disabled,
    ).toBe(true)

    // The stale value stays visible as a disabled entry in the selector.
    const selects = screen.getAllByRole('combobox')
    fireEvent.mouseDown(selects[0])
    const staleOption = await screen.findByRole('option', {
      name: 'retired-model — no longer available',
    })
    expect(staleOption.getAttribute('aria-disabled')).toBe('true')
  })

  it('offers only the session tenant catalogue — no other workspace models', async () => {
    storedWorkflowModelId = null
    render(<SystemConfigPage />, { wrapper })

    const selects = await waitFor(() => screen.getAllByRole('combobox'))
    fireEvent.mouseDown(selects[0])

    expect(await screen.findByRole('option', { name: 'gpt-4o (OpenAI Prod)' })).toBeDefined()
    expect(screen.getByRole('option', { name: 'gpt-4o-mini (OpenAI Mini)' })).toBeDefined()
    // Options come exclusively from the tenant-scoped response.
    expect(getMock).toHaveBeenCalledWith('/agents/model-configs/workflow-generation')
    expect(screen.queryByText(/other-workspace/i)).toBeNull()
  })

  it('surfaces a rejected save (422 not-enabled model) via the dialog error standard', async () => {
    storedWorkflowModelId = 'gpt-4o'
    putMock.mockRejectedValue({
      response: {
        status: 422,
        data: { detail: 'Model is not enabled in this workspace' },
      },
    })

    render(<SystemConfigPage />, { wrapper })

    await screen.findByTestId('authoring-model-recommendation')
    await screen.findAllByRole('combobox')
    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))

    await waitFor(() => {
      expect(screen.getByText('Model is not enabled in this workspace')).toBeDefined()
    })
    // The previous selection is unchanged and no success toast was shown.
    expect(screen.queryByText('systemConfig.saveSuccess')).toBeNull()
  })
})
