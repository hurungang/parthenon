import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const stableT = (k: string) => k
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: stableT }),
}))

const apiMock = vi.hoisted(() => ({
  createDecisionTool: vi.fn(),
  updateDecisionTool: vi.fn(),
  generateDecisionToolDraft: vi.fn(),
}))
vi.mock('../api/decisionToolsApi', () => apiMock)

const statusMock = vi.hoisted(() => ({
  getSystemOneStatus: vi.fn(),
}))
vi.mock('../api/systemOneApi', () => statusMock)

const dataTypesMock = vi.hoisted(() => ({
  items: [
    {
      id: 'dt-1',
      name: 'Loan Application',
      slug: 'loan-application',
      description: 'Input loan fields',
      fields: [{ name: 'amount', type: 'number', description: 'Loan amount' }],
    },
  ],
}))
vi.mock('../hooks/useDataTypes', () => ({
  useDataTypes: () => ({ data: dataTypesMock }),
}))

const CONFIGURED = { configured: true, provider_type: 'typesafe', model: 'jev-latest' }

const BASE_TOOL = {
  id: 't-9',
  tenant_id: null,
  name: 'approve-loan',
  purpose: 'Approve loans',
  description: 'generated',
  input_data_type_id: 'dt-1',
  output_data_type_id: null,
  input_data_type: null,
  output_data_type: null,
  state_preset: { amount: { source: 'input', key: 'amount' } },
  act_threshold: 0.9,
  confirm_threshold: 0.7,
  provider_model: 'jev-latest',
  status: 'active' as const,
  enabled: true,
  is_system: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  questions: [
    {
      ordering: 0,
      question_key: 'approve',
      question_type: 'choice' as const,
      instructions: 'Approve?',
      criteria_options: { yes: 'approve' },
      is_required: true,
    },
  ],
}

async function renderForm(props: Partial<{ open: boolean; editing: unknown }> = {}) {
  const { DecisionToolForm } = await import('../components/decisionTools/DecisionToolForm')
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <DecisionToolForm
        open={props.open ?? true}
        editing={(props.editing ?? null) as never}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />
    </QueryClientProvider>,
  )
}

const label = (re: RegExp) => screen.getByLabelText(re)

describe('DecisionToolForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    statusMock.getSystemOneStatus.mockResolvedValue(CONFIGURED)
    apiMock.createDecisionTool.mockResolvedValue(BASE_TOOL)
    apiMock.updateDecisionTool.mockResolvedValue(BASE_TOOL)
  })

  const waitReady = async () => {
    await screen.findAllByText(
      (_, el) => el?.textContent?.includes('decisionTools.configuredHint') ?? false,
      {},
      { timeout: 4000 },
    )
  }

  it('shows the configured-model hint when a provider is configured', async () => {
    await renderForm()
    await waitReady()
  })

  it('blocks authoring when System One is not configured', async () => {
    statusMock.getSystemOneStatus.mockResolvedValue({ configured: false })
    await renderForm()
    expect(
      await screen.findAllByText(
        (_, el) => el?.textContent?.includes('decisionTools.notConfigured') ?? false,
        {},
        { timeout: 4000 },
      ),
    ).not.toHaveLength(0)
    const save = await screen.findByRole('button', { name: 'app.save' })
    expect(save).toBeDisabled()
  })

  it('pre-fills from an existing tool with disabled name and state preset rows', async () => {
    await renderForm({ editing: BASE_TOOL })
    const name = (await screen.findByLabelText(/^decisionTools\.name/)) as HTMLInputElement
    expect(name.value).toBe('approve-loan')
    expect(name).toBeDisabled()
    // state preset row mapped from the tool; dataKey is a select populated
    // from the chosen input data type's fields when one is referenced.
    expect(
      (screen.getByLabelText(/^decisionTools\.stateKey$/) as HTMLInputElement).value,
    ).toBe('amount')
    const dataKey = screen.getByLabelText(/^decisionTools\.dataKey$/)
    if (dataKey.tagName !== 'INPUT' || !(dataKey as HTMLInputElement).value) {
      // select rendering: the chosen field name is displayed as its value text
      expect(screen.getAllByText('amount').length).toBeGreaterThan(0)
    } else {
      expect((dataKey as HTMLInputElement).value).toBe('amount')
    }
  })

  it('renders the auto-generated description preview with questions, state, and thresholds', async () => {
    await renderForm({ editing: BASE_TOOL })
    await screen.findByText(/^Decision tool 'approve-loan'/)
    const preview = screen
      .getByText(/^Decision tool 'approve-loan'/)
      .closest('div')?.textContent
    expect(preview).toContain('`approve` (choice)')
    expect(preview).toContain('State fields sent to the model: amount.')
    expect(preview).toContain('act >= 0.9, confirm >= 0.7')
    expect(screen.getByText('decision____approve-loan')).toBeInTheDocument()
  })

  it('updates the description preview live as fields change', async () => {
    await renderForm()
    fireEvent.change(label(/^decisionTools\.name/), { target: { value: 'my-tool' } })
    fireEvent.change(label(/^decisionTools\.purpose/), { target: { value: 'My purpose' } })
    const preview = await screen.findByText(/^Decision tool 'my-tool'/)
    expect(preview.textContent).toContain('My purpose')
  })

  it('validates thresholds order client-side', async () => {
    await renderForm()
    await fillMinimumValid()
    fireEvent.change(label(/^decisionTools\.actThreshold/), { target: { value: '0.4' } })
    fireEvent.change(label(/^decisionTools\.confirmThreshold/), {
      target: { value: '0.8' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))
    expect(await screen.findByText('decisionTools.validation.thresholdsOrder'))
    expect(apiMock.createDecisionTool).not.toHaveBeenCalled()
  })

  it('validates choice questions require options and rejects duplicate question keys', async () => {
    await renderForm()
    await fillMinimumValid()
    // clear the option key → choice without options
    const optionKey = screen.getByLabelText(/^decisionTools\.optionKey$/)
    fireEvent.change(optionKey, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))
    expect(
      await screen.findByText('decisionTools.validation.choiceOptionsRequired'),
    ).toBeInTheDocument()

    // restore, then duplicate the key
    fireEvent.change(optionKey, { target: { value: 'yes' } })
    fireEvent.click(screen.getByRole('button', { name: 'decisionTools.addQuestion' }))
    const keyFields = screen.getAllByLabelText(/^decisionTools\.questionKey/)
    fireEvent.change(keyFields[1], { target: { value: 'approve' } })
    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))
    expect(
      await screen.findByText('decisionTools.validation.duplicateQuestionKey'),
    ).toBeInTheDocument()
  })

  it('switching question type to noul clears criteria', async () => {
    await renderForm()
    await pickQuestionType('noul')
    expect(await screen.findByText('decisionTools.noulHint')).toBeInTheDocument()
    expect(screen.queryByLabelText(/^decisionTools\.optionKey$/)).not.toBeInTheDocument()
  })

  it('switching question type to score shows the rubric legend editor', async () => {
    await renderForm()
    await pickQuestionType('score')
    const legend = await screen.findByLabelText(/^decisionTools\.scoreLegend/)
    fireEvent.change(legend, { target: { value: 'low\nhigh' } })
    expect(legend).toHaveValue('low\nhigh')
  })

  it('submits a valid create payload with typed questions and state preset', async () => {
    await renderForm()
    await waitReady()
    await fillMinimumValid()
    // add a state preset mapping
    fireEvent.click(screen.getByRole('button', { name: 'decisionTools.addStateMapping' }))
    fireEvent.change(screen.getByLabelText(/^decisionTools\.stateKey$/), {
      target: { value: 'risk' },
    })
    fireEvent.change(screen.getByLabelText(/^decisionTools\.dataKey$/), {
      target: { value: 'risk_level' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))
    await vi.waitFor(() => {
      expect(apiMock.createDecisionTool).toHaveBeenCalledTimes(1)
    })
    const payload = apiMock.createDecisionTool.mock.calls[0][0]
    expect(payload.name).toBe('approve-loan')
    expect(payload.questions[0].question_type).toBe('choice')
    expect(payload.questions[0].criteria_options).toEqual({ yes: 'approve' })
    expect(payload.state_preset).toEqual({
      risk: { source: 'input', key: 'risk_level' },
    })
    expect(payload.act_threshold).toBe(0.9)
    expect(payload.confirm_threshold).toBe(0.7)
  })

  it('calls updateDecisionTool when editing', async () => {
    await renderForm({ editing: BASE_TOOL })
    await waitReady()
    const save = await screen.findByRole('button', { name: 'app.save' })
    await screen.findByText(/^Decision tool 'approve-loan'/)
    fireEvent.click(save)
    try {
      await vi.waitFor(() => {
        expect(apiMock.updateDecisionTool).toHaveBeenCalledWith('t-9', expect.anything())
      })
    } catch {
      const body = document.body.textContent as string
      const v = body.match(/decisionTools\.validation\.[A-Za-z]+/g)
      throw new Error('DBG validation=' + JSON.stringify(v) + ' saving=' + body.includes('app.loading'))
    }
  })

  it('shows API errors inside the dialog without closing', async () => {
    apiMock.createDecisionTool.mockRejectedValue({
      response: { status: 409, data: { detail: ['exists'] } },
    })
    await renderForm()
    await waitReady()
    await fillMinimumValid()
    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))
    await vi.waitFor(() => {
      expect(apiMock.createDecisionTool).toHaveBeenCalled()
    })
    // dialog still open (error rendered via PermissionDeniedAlert)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  async function pickQuestionType(value: string) {
    const select = screen.getByLabelText(/^decisionTools\.questionType$/)
    fireEvent.mouseDown(select, { button: 0 })
    fireEvent.click(await screen.findByRole('option', {
      name: `decisionTools.questionTypes.${value}`,
    }))
  }

  async function fillMinimumValid() {
    fireEvent.change(label(/^decisionTools\.name/), { target: { value: 'approve-loan' } })
    fireEvent.change(label(/^decisionTools\.purpose/), { target: { value: 'Decide loans' } })
    fireEvent.change(screen.getByLabelText(/^decisionTools\.questionKey/), {
      target: { value: 'approve' },
    })
    fireEvent.change(screen.getByLabelText(/^decisionTools\.optionKey$/), {
      target: { value: 'yes' },
    })
    fireEvent.change(screen.getByLabelText(/^decisionTools\.optionDescription$/), {
      target: { value: 'approve' },
    })
  }

  // ── Round 2 ─────────────────────────────────────────────────────────────

  it('renders fields in the fixed order: name, purpose, input type, output type, questions, state mapping', async () => {
    await renderForm()
    await waitReady()
    // MUI portals the dialog to document.body — query there, not in container.
    const dialog = document.querySelector('[role="dialog"]')!
    const orderOf = (text: string) => {
      const el = Array.from(
        dialog.querySelectorAll('label, .MuiTypography-root'),
      ).find((n) => (n.textContent ?? '').replace(/\s*\*$/, '') === text)
      expect(el, `${text} must render`).toBeTruthy()
      return Array.from(dialog.querySelectorAll('*')).indexOf(el!)
    }
    const name = orderOf('decisionTools.name')
    const purpose = orderOf('decisionTools.purpose')
    const inputType = orderOf('decisionTools.inputDataType')
    const outputType = orderOf('decisionTools.outputDataType')
    const questions = orderOf('decisionTools.questionsTitle')
    const statePreset = orderOf('decisionTools.statePreset')
    expect(name).toBeLessThan(purpose)
    expect(purpose).toBeLessThan(inputType)
    expect(inputType).toBeLessThan(outputType)
    expect(outputType).toBeLessThan(questions)
    expect(questions).toBeLessThan(statePreset)
  })

  it('selects input/output data types and opens read-only View dialogs', async () => {
    await renderForm()
    await waitReady()
    // Select the input data type from the dropdown.
    const inputSelect = screen.getByLabelText(/^decisionTools\.inputDataType/)
    fireEvent.mouseDown(inputSelect, { button: 0 })
    fireEvent.click(await screen.findByRole('option', { name: /Loan Application/ }))

    // View button now enabled; opens the read-only dialog in-form.
    const viewButtons = screen.getAllByRole('button', {
      name: 'decisionTools.viewDataType',
    })
    expect(viewButtons[0]).toBeEnabled()
    fireEvent.click(viewButtons[0])
    expect(
      await screen.findByText('decisionTools.inputDataTypeView'),
    ).toBeInTheDocument()
    // Field table renders the referenced AgentDataType definition.
    expect(screen.getByText('decisionTools.fieldName')).toBeInTheDocument()
    expect(screen.getByText('amount')).toBeInTheDocument()
    // Close restores the form dialog.
    fireEvent.click(screen.getByRole('button', { name: 'app.close' }))
    await vi.waitFor(() => {
      expect(screen.queryByText('decisionTools.fieldName')).not.toBeInTheDocument()
    })
  })

  it('populates the mapping property selector from the chosen input data type', async () => {
    await renderForm()
    await waitReady()
    fireEvent.change(label(/^decisionTools\.name/), { target: { value: 'typed-tool' } })
    fireEvent.change(label(/^decisionTools\.purpose/), { target: { value: 'Decide' } })
    const inputSelect = screen.getByLabelText(/^decisionTools\.inputDataType/)
    fireEvent.mouseDown(inputSelect, { button: 0 })
    fireEvent.click(await screen.findByRole('option', { name: /Loan Application/ }))

    fireEvent.click(screen.getByRole('button', { name: 'decisionTools.addStateMapping' }))
    // With an input type chosen (source=input), dataKey is a select whose
    // options are the input type's fields.
    const dataKey = screen.getByLabelText(/^decisionTools\.dataKey$/)
    fireEvent.mouseDown(dataKey, { button: 0 })
    const options = await screen.findAllByRole('option')
    const names = options.map((o) => o.textContent)
    expect(names).toContain('amount')
    fireEvent.click(screen.getByRole('option', { name: 'amount' }))
    // state key + selected property submits as the mapped preset
    fireEvent.change(screen.getByLabelText(/^decisionTools\.stateKey$/), {
      target: { value: 'amount' },
    })
    fireEvent.change(screen.getByLabelText(/^decisionTools\.questionKey/), {
      target: { value: 'q1' },
    })
    fireEvent.change(screen.getByLabelText(/^decisionTools\.optionKey$/), {
      target: { value: 'yes' },
    })
    fireEvent.change(screen.getByLabelText(/^decisionTools\.optionDescription$/), {
      target: { value: 'y' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))
    await vi.waitFor(() => {
      expect(apiMock.createDecisionTool).toHaveBeenCalledTimes(1)
    })
    expect(apiMock.createDecisionTool.mock.calls[0][0].state_preset).toEqual({
      amount: { source: 'input', key: 'amount' },
    })
  })

  it('auto-detects backtick state-path placeholders from question instructions', async () => {
    await renderForm()
    await waitReady()
    expect(screen.queryByText(/decisionTools\.detectedPaths/)).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/^decisionTools\.instructions/), {
      target: { value: 'Check `input.tier` and `input.amount`, then `input.tier` again' },
    })
    // Deduped, detected paths surface in the state-preset section.
    expect(await screen.findByText(/decisionTools\.detectedPaths/)).toBeInTheDocument()
    expect(screen.getByText('`input.tier` `input.amount`')).toBeInTheDocument()

    // Auto-detect adds suggested mappings (paths become state keys).
    fireEvent.click(screen.getByRole('button', { name: 'decisionTools.autoDetect' }))
    const stateKeys = screen.getAllByLabelText(/^decisionTools\.stateKey$/)
    expect(stateKeys.map((k) => (k as HTMLInputElement).value)).toEqual([
      'input.tier',
      'input.amount',
    ])
  })

  it('AI generate fills questions and state preset from the mocked draft', async () => {
    apiMock.generateDecisionToolDraft.mockResolvedValue({
      questions: [
        {
          ordering: 0,
          question_key: 'risk',
          question_type: 'score',
          instructions: 'Rate the risk',
          criteria_options: ['low', 'high'],
          is_required: true,
        },
      ],
      state_preset: { amount: { source: 'input', key: 'amount' } },
      detected_state_paths: ['input.amount'],
      model_id: 'cfg-gpt',
    })
    await renderForm()
    await waitReady()
    fireEvent.change(label(/^decisionTools\.purpose/), { target: { value: 'Loan decisions' } })
    fireEvent.click(
      screen.getByRole('button', { name: 'decisionTools.generateWithAi' }),
    )
    await vi.waitFor(() => {
      expect(apiMock.generateDecisionToolDraft).toHaveBeenCalledWith({
        description: 'Loan decisions',
        input_data_type_id: null,
        output_data_type_id: null,
        existing_questions: null,
      })
    })
    // Drafted question replaces the blank one.
    expect(await screen.findByDisplayValue('risk')).toBeInTheDocument()
    // Drafted state preset row mapped.
    expect(
      (screen.getByLabelText(/^decisionTools\.stateKey$/) as HTMLInputElement).value,
    ).toBe('amount')
  })

  it('shows the AI generate error inside the dialog without closing', async () => {
    apiMock.generateDecisionToolDraft.mockRejectedValue({
      response: { status: 422, data: { detail: 'Model returned invalid JSON draft' } },
    })
    await renderForm()
    await waitReady()
    fireEvent.change(label(/^decisionTools\.purpose/), { target: { value: 'Loan decisions' } })
    fireEvent.click(
      screen.getByRole('button', { name: 'decisionTools.generateWithAi' }),
    )
    await vi.waitFor(() => {
      expect(apiMock.generateDecisionToolDraft).toHaveBeenCalled()
    })
    // dialog stays open (error via PermissionDeniedAlert)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
