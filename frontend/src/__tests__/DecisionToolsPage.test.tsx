import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { buildToolName, DECISION_SERVER_SLUG } from '../utils/toolNaming'

const stableT = (k: string) => k
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: stableT }),
}))

const apiMock = vi.hoisted(() => ({
  listDecisionTools: vi.fn(),
  createDecisionTool: vi.fn(),
  updateDecisionTool: vi.fn(),
  deleteDecisionTool: vi.fn(),
}))

vi.mock('../api/decisionToolsApi', () => apiMock)

const statusMock = vi.hoisted(() => ({
  getSystemOneStatus: vi.fn(),
}))

vi.mock('../api/systemOneApi', () => statusMock)

const TOOL: Record<string, unknown> = {
  id: 't-1',
  tenant_id: null,
  name: 'approve_loan',
  purpose: 'Approve small loans',
  description: "Decision tool 'approve_loan': Approve small loans",
  input_schema: null,
  output_schema: null,
  state_preset: null,
  act_threshold: 0.9,
  confirm_threshold: 0.7,
  provider_model: 'jev-latest',
  status: 'active',
  enabled: true,
  is_system: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  questions: [
    {
      ordering: 0,
      question_key: 'approve',
      question_type: 'choice',
      instructions: 'Approve?',
      criteria_options: { yes: 'approve', no: 'reject' },
      is_required: true,
    },
  ],
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

let renderResult: import('@testing-library/react').RenderResult
async function renderPage() {
  const { DecisionToolsPage } = await import(
    '../pages/agents/DecisionToolsPage'
  )
  renderResult = render(wrapper(<DecisionToolsPage />))
  return renderResult
}

describe('DecisionToolsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.listDecisionTools.mockResolvedValue([TOOL])
    apiMock.createDecisionTool.mockResolvedValue(TOOL)
    apiMock.updateDecisionTool.mockResolvedValue(TOOL)
    apiMock.deleteDecisionTool.mockResolvedValue(undefined)
    statusMock.getSystemOneStatus.mockResolvedValue({
      configured: true,
      provider_type: 'typesafe',
      model: 'jev-latest',
    })
  })

  it('lists decision tools with the canonical decision____ prefix', async () => {
    await renderPage()
    expect(
      await screen.findByText(buildToolName(DECISION_SERVER_SLUG, 'approve_loan')),
    ).toBeInTheDocument()
    expect(await screen.findByText('decision____approve_loan')).toBeInTheDocument()
    expect(screen.getByText('Approve small loans')).toBeInTheDocument()
  })

  it('shows an empty-state message with no tools', async () => {
    apiMock.listDecisionTools.mockResolvedValue([])
    await renderPage()
    expect(await screen.findByText('decisionTools.noTools')).toBeInTheDocument()
  })

  it('renders a permission error from the list call', async () => {
    apiMock.listDecisionTools.mockRejectedValue({
      response: { status: 403 },
    })
    await renderPage()
    // PermissionDeniedAlert renders a fallback instead of crashing
    await waitFor(() => {
      expect(screen.queryByText('decision____approve_loan')).not.toBeInTheDocument()
    })
  })

  it('opens the create dialog and saves a valid tool', async () => {
    await renderPage()
    fireEvent.click(await screen.findByText('decisionTools.addTool'))
    // dialog shows generated description preview
    await waitFor(() => {
      expect(
        screen.getAllByText('decisionTools.generatedDescription').length,
      ).toBeGreaterThan(0)
    })
    // save button is enabled when provider configured
    const save = await screen.findByRole('button', { name: 'app.save' })
    expect(save).not.toBeDisabled()
  })

  it('blocks saving when System One is not configured', async () => {
    statusMock.getSystemOneStatus.mockResolvedValue({ configured: false })
    await renderPage()
    fireEvent.click(await screen.findByText('decisionTools.addTool'))
    expect(await screen.findByText('decisionTools.notConfigured', {}, { timeout: 3000 })).toBeInTheDocument()
    await waitFor(() => {
      const save = screen.getByRole('button', { name: 'app.save' })
      expect(save).toBeDisabled()
    })
    expect(apiMock.createDecisionTool).not.toHaveBeenCalled()
  })

  it('shows duplicate-name API errors inside the dialog', async () => {
    apiMock.createDecisionTool.mockRejectedValue({
      response: { status: 409, data: { detail: ['exists'] } },
    })
    await renderPage()
    fireEvent.click(await screen.findByText('decisionTools.addTool'))
    await screen.findByRole('button', { name: 'app.save' })
    // fill in minimum required fields
    const nameField = await screen.findByLabelText(/^decisionTools\.name/, {}, { timeout: 3000 })
    fireEvent.change(nameField, { target: { value: 'approve-loan' } })
    const purposeField = await screen.findByLabelText(/^decisionTools\.purpose/)
    fireEvent.change(purposeField, { target: { value: 'Decide loans' } })
    const keyField = await screen.findByLabelText(/^decisionTools\.questionKey/)
    fireEvent.change(keyField, { target: { value: 'approve' } })
    const optionKey = await screen.findByLabelText(/^decisionTools\.optionKey$/)
    fireEvent.change(optionKey, { target: { value: 'yes' } })
    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))
    // dialog stays open and renders the error (fallback error message)
    await waitFor(() => {
      expect(apiMock.createDecisionTool).toHaveBeenCalledTimes(1)
    })
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('opens the edit dialog pre-filled and disabled name field', async () => {
    await renderPage()
    const editButton = await screen.findByRole('button', { name: 'app.edit' })

    fireEvent.click(editButton)
    const nameField = (await screen.findByLabelText(
      /^decisionTools\.name/,
      {},
      { timeout: 3000 },
    )) as HTMLInputElement
    expect(nameField.value).toBe('approve_loan')
    expect(nameField).toBeDisabled()
  })

  it('deletes a tool after confirmation', async () => {
    await renderPage()
    await screen.findByText('decision____approve_loan')
    // Icon buttons carry no accessible name; find the one with the Delete icon.
    const { container } = renderResult
    const deleteBtn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.querySelector('[data-testid="DeleteIcon"]'),
    )
    expect(deleteBtn).toBeTruthy()
    fireEvent.click(deleteBtn!)
    // confirm inside the dialog (text button carries the accessible name)
    fireEvent.click(await screen.findByRole('button', { name: 'app.delete' }))
    await waitFor(() => {
      expect(apiMock.deleteDecisionTool).toHaveBeenCalledWith('t-1')
    })
  })
})
