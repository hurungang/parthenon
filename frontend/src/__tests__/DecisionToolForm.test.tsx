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
  listEnabledDecisionModels: vi.fn(),
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
  output_data_type_id: 'dt-1',
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
    statusMock.listEnabledDecisionModels.mockResolvedValue([])
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
    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))
    await vi.waitFor(() => {
      expect(apiMock.createDecisionTool).toHaveBeenCalledTimes(1)
    })
    const payload = apiMock.createDecisionTool.mock.calls[0][0]
    expect(payload.name).toBe('approve-loan')
    expect(payload.questions[0].question_type).toBe('choice')
    expect(payload.questions[0].criteria_options).toEqual({ yes: 'approve' })
    // No explicit mappings authored — state auto-matches (empty preset).
    expect(payload.state_preset).toBeNull()
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
    await ensureQuestionEditor()
    const select = screen.getByLabelText(/^decisionTools\.questionType$/)
    fireEvent.mouseDown(select, { button: 0 })
    fireEvent.click(await screen.findByRole('option', {
      name: `decisionTools.questionTypes.${value}`,
    }))
  }

  /** Create mode starts with ZERO questions (auto-derived from the output
      data type unless overridden) — tests needing an editor add one. */
  async function ensureQuestionEditor() {
    if (!screen.queryByLabelText(/^decisionTools\.questionKey/)) {
      fireEvent.click(
        screen.getByRole('button', { name: 'decisionTools.addQuestion' }),
      )
    }
  }

  /** The state-preset section is an ADVANCED accordion, collapsed by
      default — expand it before interacting with mapping controls. */
  async function expandStatePreset() {
    const heading = screen.getByText('decisionTools.statePreset')
    const summary = heading.closest('.MuiAccordionSummary-root')
    if (summary?.getAttribute('aria-expanded') !== 'true') {
      fireEvent.click(heading)
    }
  }

  async function fillMinimumValid() {
    fireEvent.change(label(/^decisionTools\.name/), { target: { value: 'approve-loan' } })
    fireEvent.change(label(/^decisionTools\.purpose/), { target: { value: 'Decide loans' } })
    await ensureQuestionEditor()
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

    await expandStatePreset()
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
    await ensureQuestionEditor()
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

  it('renders mapper rows for unmatched placeholders and saves only explicit mappings', async () => {
    await renderForm()
    await waitReady()
    await fillMinimumValid()
    // select the input type (fields: amount)
    const inputSelect = screen.getByLabelText(/^decisionTools\.inputDataType/)
    fireEvent.mouseDown(inputSelect, { button: 0 })
    fireEvent.click(await screen.findByRole('option', { name: /Loan Application/ }))

    // reference two placeholders in instructions: `amount` matches the
    // input property 1:1 (silent), `aaa` has no same-named property.
    await ensureQuestionEditor()
    fireEvent.change(screen.getByLabelText(/^decisionTools\.instructions/), {
      target: { value: 'Check `amount` and `aaa`' },
    })
    await expandStatePreset()
    // matched: silent chip, no mapper row for `amount`
    expect(await screen.findByText('amount → amount')).toBeInTheDocument()
    // unmatched: exactly one mapper row asking to map `aaa` (the mocked t()
    // returns the raw key, so both mapper rows share the same label text)
    expect(screen.getAllByText('decisionTools.mapPlaceholder')).toHaveLength(1)

    // map aaa → amount, then save: payload includes ONLY the explicit
    // mapping (the 1:1 `amount` key is not sent).
    const aaaSelect = screen.getAllByLabelText(/^decisionTools\.dataKey$/)[0]
    fireEvent.mouseDown(aaaSelect, { button: 0 })
    fireEvent.click(await screen.findByRole('option', { name: 'amount' }))
    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))
    await vi.waitFor(() => {
      expect(apiMock.createDecisionTool).toHaveBeenCalledTimes(1)
    })
    expect(apiMock.createDecisionTool.mock.calls[0][0].state_preset).toEqual({
      aaa: { source: 'input', key: 'amount' },
    })
  })

  it('shows the select-input-type hint and no mapper rows before an input type is chosen', async () => {
    await renderForm()
    await waitReady()
    await fillMinimumValid()
    await ensureQuestionEditor()
    fireEvent.change(screen.getByLabelText(/^decisionTools\.instructions/), {
      target: { value: 'Check `aaa`' },
    })
    await expandStatePreset()
    expect(
      await screen.findByText(
        'decisionTools.selectInputTypeFirst',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByLabelText(/^decisionTools\.dataKey$/)).toBeNull()
    expect(screen.queryByRole('button', { name: 'decisionTools.addStateMapping' })).toBeNull()
  })

  it('disables Save with an inline hint when enabled without both data types; disabled drafts save cleanly', async () => {
    await renderForm()
    await waitReady()
    await fillMinimumValid()
    const save = screen.getByRole('button', { name: 'app.save' })
    const toggleEnabled = () => {
      const input = document.querySelector('.MuiSwitch-input') as HTMLInputElement
      fireEvent.click(input)
    }
    // new tools start as disabled drafts → Save is available immediately
    expect(save).toBeEnabled()

    // enabling without both data types pre-validates: hint + Save disabled
    toggleEnabled()
    expect(await screen.findByText(
      'decisionTools.validation.readinessRequiresTypes',
    )).toBeInTheDocument()
    expect(save).toBeDisabled()
    expect(apiMock.createDecisionTool).not.toHaveBeenCalled()

    // disabling again clears the block — the draft saves cleanly
    toggleEnabled()
    await vi.waitFor(() => {
      expect(save).toBeEnabled()
    })
    fireEvent.click(save)
    await vi.waitFor(() => {
      expect(apiMock.createDecisionTool).toHaveBeenCalledTimes(1)
    })
    const payload = apiMock.createDecisionTool.mock.calls[0][0]
    expect(payload.enabled).toBe(false)
    expect(payload.input_data_type_id).toBeNull()
    expect(payload.output_data_type_id).toBeNull()
  })

  it('drops legacy agent_data state rows on load (dropped on next save)', async () => {
    const legacy = {
      ...BASE_TOOL,
      state_preset: {
        amount: { source: 'input', key: 'amount' },
        history: { source: 'agent_data', key: 'customer_history' },
      },
    }
    await renderForm({ editing: legacy })
    await waitReady()
    await expandStatePreset()
    // only the input row survives; the agent_data row is not rendered
    const stateKeys = screen.queryAllByLabelText(/^decisionTools\.stateKey$/)
    expect(stateKeys.map((k) => (k as HTMLInputElement).value)).toEqual(['amount'])
    await screen.findByText(/^Decision tool 'approve-loan'/)
  })

  it('auto-detects backtick state-path placeholders from question instructions', async () => {
    await renderForm()
    await waitReady()
    await fillMinimumValid()
    const inputSelect = screen.getByLabelText(/^decisionTools\.inputDataType/)
    fireEvent.mouseDown(inputSelect, { button: 0 })
    fireEvent.click(await screen.findByRole('option', { name: /Loan Application/ }))

    await ensureQuestionEditor()
    fireEvent.change(screen.getByLabelText(/^decisionTools\.instructions/), {
      target: { value: 'Check `input.tier` and `input.amount`, then `input.tier` again' },
    })
    // Deduped placeholders surface as mapper rows (neither matches the
    // input property 'amount' verbatim) — no manual auto-detect step.
    await expandStatePreset()
    const mapperRows = await screen.findAllByText('decisionTools.mapPlaceholder')
    expect(mapperRows).toHaveLength(2)
    expect(
      screen.queryByRole('button', { name: 'decisionTools.autoDetect' }),
    ).toBeNull()
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
    // Drafted state preset row mapped (visible once an input type is
    // chosen — mappings come from its properties).
    const inputSelect = screen.getByLabelText(/^decisionTools\.inputDataType/)
    fireEvent.mouseDown(inputSelect, { button: 0 })
    fireEvent.click(await screen.findByRole('option', { name: /Loan Application/ }))
    await expandStatePreset()
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

// ── Enabled-model selector (multi-provider model selection) ────────────────

const ENABLED_MODELS = [
  {
    availability_id: 'av-1',
    provider_id: 'p-1',
    provider_type: 'typesafe',
    provider_display_name: 'Primary Vendor',
    model_name: 'jev-latest',
  },
  {
    availability_id: 'av-2',
    provider_id: 'p-1',
    provider_type: 'typesafe',
    provider_display_name: 'Primary Vendor',
    model_name: 'jev-mini',
  },
]

const EDITING_WITH_MODEL = {
  ...BASE_TOOL,
  decision_model_availability_id: 'av-1',
  model_name: 'jev-latest',
  provider_display_name: 'Primary Vendor',
}

describe('DecisionToolForm enabled-model selector', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    statusMock.getSystemOneStatus.mockResolvedValue(CONFIGURED)
    statusMock.listEnabledDecisionModels.mockResolvedValue(ENABLED_MODELS)
    apiMock.createDecisionTool.mockResolvedValue(BASE_TOOL)
    apiMock.updateDecisionTool.mockResolvedValue(BASE_TOOL)
  })

  const openModelMenu = async () => {
    await screen.findAllByText(
      (_, el) => el?.textContent?.includes('decisionTools.configuredHint') ?? false,
      {},
      { timeout: 4000 },
    )
    fireEvent.mouseDown(screen.getByLabelText(/^decisionTools\.modelSelection/), {
      button: 0,
    })
  }

  it('lists ONLY enabled models across providers in the selector', async () => {
    await renderForm()
    await openModelMenu()
    expect(await screen.findByRole('option', { name: /jev-latest — Primary Vendor/ }))
    expect(screen.getByRole('option', { name: /jev-mini — Primary Vendor/ }))
    // no phantom options (placeholder + the two enabled models)
    expect(screen.getAllByRole('option')).toHaveLength(3)
  })

  it('submits the selected availability id as decision_model_availability_id', async () => {
    await renderForm()
    await openModelMenu()
    fireEvent.click(
      await screen.findByRole('option', { name: /jev-mini — Primary Vendor/ }),
    )
    fireEvent.change(label(/^decisionTools\.name/), { target: { value: 'selector-tool' } })
    fireEvent.change(label(/^decisionTools\.purpose/), { target: { value: 'p' } })
    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))
    await vi.waitFor(() => {
      expect(apiMock.createDecisionTool).toHaveBeenCalled()
    })
    expect(apiMock.createDecisionTool.mock.calls[0][0]).toMatchObject({
      decision_model_availability_id: 'av-2',
    })
  })

  it('pre-selects the saved model when editing a tool', async () => {
    await renderForm({ editing: EDITING_WITH_MODEL })
    await openModelMenu()
    const selected = await screen.findByRole('option', {
      name: /jev-latest — Primary Vendor/,
      selected: true,
    })
    expect(selected).toBeInTheDocument()
  })

  // ── FIX-20261014-004500: the model select must never be silently empty ────

  it('shows the stored selection as a disabled unavailable option when editing a tool whose model is no longer enabled', async () => {
    await renderForm({
      editing: {
        ...EDITING_WITH_MODEL,
        decision_model_availability_id: 'av-gone',
        model_name: 'jev-legacy',
      },
    })
    await openModelMenu()
    // The stored model renders as a DISABLED option (not silently missing),
    // labelled with the enriched tool identity.
    const unavailable = await screen.findByRole('option', {
      name: /jev-legacy — Primary Vendor/,
    })
    expect(unavailable).toHaveAttribute('aria-disabled', 'true')
    expect(
      screen.getAllByText((_, el) =>
        el?.textContent?.includes('decisionTools.modelUnavailableOption') ?? false,
      ).length,
    ).toBeGreaterThan(0)
  })

  it('shows a placeholder option instead of a blank select when no model is selected', async () => {
    await renderForm()
    await openModelMenu()
    const placeholder = await screen.findByRole('option', {
      name: 'decisionTools.modelNone',
    })
    expect(placeholder).toBeInTheDocument()
  })

  it('flags a stale selection (since-disabled model) as invalid on submit', async () => {
    // Editing a tool whose saved model is no longer in the enabled list.
    await renderForm({ editing: { ...EDITING_WITH_MODEL, decision_model_availability_id: 'av-gone' } })
    await screen.findAllByText(
      (_, el) => el?.textContent?.includes('decisionTools.configuredHint') ?? false,
      {},
      { timeout: 4000 },
    )
    fireEvent.change(label(/^decisionTools\.purpose/), { target: { value: 'trigger submit' } })
    fireEvent.click(screen.getByRole('button', { name: 'app.save' }))
    // the stale selection is NOT silently submitted
    await vi.waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })
    expect(apiMock.updateDecisionTool).not.toHaveBeenCalled()
  })
})
