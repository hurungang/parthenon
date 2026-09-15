import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useAgentDraftComposition } from '../hooks/useAgentDraftComposition'
import { EquipmentSlots } from '../components/agents/panel/EquipmentSlots'
import type { AgentType, PanelDialogRequest } from '../types'

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const { mockApiGet, mockApiPut, mockApiPost, fixtures } = vi.hoisted(() => ({
  mockApiGet: vi.fn(),
  mockApiPut: vi.fn(),
  mockApiPost: vi.fn(),
  // Mutable fixtures so individual tests can swap in long names (reset in beforeEach).
  fixtures: {
    dataTypes: [
      {
        id: 'dt-1',
        name: 'research-summary',
        description: null,
        fields: [
          { name: 'topic', type: 'string', required: true, description: null, enum_values: null },
        ],
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
      {
        id: 'dt-2',
        name: 'final-report',
        description: null,
        fields: [],
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ],
    models: [
      {
        model_id: 'gpt-4o',
        model_name: 'gpt-4o',
        model_config_id: 'mc-1',
        config_id: 'mc-1',
        config_display_name: 'OpenAI Prod',
        provider_type: 'openai',
      },
    ],
  },
}))

vi.mock('../api/apiClient', () => ({
  default: { get: mockApiGet, put: mockApiPut, post: mockApiPost },
}))

vi.mock('../hooks/useDataTypes', () => ({
  useDataTypes: () => ({
    data: { items: fixtures.dataTypes },
    error: null,
  }),
}))

vi.mock('../hooks/useAvailableModels', () => ({
  useAvailableModels: () => ({
    data: fixtures.models,
    error: null,
  }),
}))

vi.mock('../components/permissions/PermissionDeniedAlert', () => ({
  default: () => <div data-testid="permission-denied-alert" />,
}))

// ── Fixtures ──────────────────────────────────────────────────────────────────

const EMPTY_AGENT: AgentType = {
  id: 'at-1',
  name: 'research-agent',
  description: null,
  identity_id: null,
  role_id: null,
  model_id: null,
  system_instruction: null,
  input_type: 'none',
  input_schema: null,
  output_type: 'auto',
  output_schema: null,
  output_data_type_id: null,
  output_data_type_name: null,
  sop_bindings: [],
  skill_bindings: [],
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  plan: null,
}

/** Agent equipped in every slot — ids resolve against the fixture lists. */
const EQUIPPED_AGENT: AgentType = {
  ...EMPTY_AGENT,
  role_id: 'role-1',
  identity_id: 'identity-1',
  skill_bindings: [
    { id: 'sb-1', skill_id: 'skill-1', skill_name: 'web-search', order: 1, created_at: '2026-01-01T00:00:00Z' },
  ],
  sop_bindings: [
    { id: 'so-1', sop_id: 'sop-1', sop_name: 'research-sop', order: 1, created_at: '2026-01-01T00:00:00Z' },
  ],
  input_type: 'typed',
  // Serializes identically to dataTypeToInputSchema(dt-1) so the applied
  // input-type chip resolves to the registry entry.
  input_schema: { type: 'object', properties: { topic: { type: 'string' } }, required: ['topic'] },
  output_data_type_id: 'dt-1',
  model_id: 'gpt-4o',
}

// ── Harness: real draft hook + EquipmentSlots, draft dump for assertions ──────

function TestHost({
  agent = EMPTY_AGENT,
  onOpenDialog = () => {},
}: {
  agent?: AgentType
  onOpenDialog?: (request: PanelDialogRequest) => void
}) {
  const draftApi = useAgentDraftComposition(agent)
  return (
    <>
      <EquipmentSlots draftApi={draftApi} onOpenDialog={onOpenDialog} />
      <pre data-testid="draft-dump">{JSON.stringify(draftApi.draft)}</pre>
      <pre data-testid="dirty-dump">{String(draftApi.isDirty)}</pre>
    </>
  )
}

/** Opens a MUI Select in jsdom (requires mouseDown) and clicks an option. */
async function pickFromSelect(labelText: string, optionText: string) {
  const select = screen.getByLabelText(labelText)
  fireEvent.mouseDown(select)
  const option = await screen.findByRole('option', { name: optionText })
  fireEvent.click(option)
}

function renderSlots(props: Parameters<typeof TestHost>[0] = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<TestHost {...props} />, {
    wrapper: ({ children }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>,
  })
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('EquipmentSlots', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Restore default fixture names (tests may swap in long names).
    fixtures.dataTypes[0].name = 'research-summary'
    fixtures.dataTypes[1].name = 'final-report'
    fixtures.models[0].config_display_name = 'OpenAI Prod'
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/agents/roles') {
        return { data: [{ id: 'role-1', name: 'Researcher', description: null, created_at: '', updated_at: '' }] }
      }
      if (url === '/agents/identities') {
        return { data: [{ id: 'identity-1', name: 'svc-agent', created_at: '', updated_at: '' }] }
      }
      if (url === '/skills') {
        return { data: [{ id: 'skill-1', name: 'web-search', description: null, created_at: '', updated_at: '' }] }
      }
      if (url === '/sops') {
        return { data: [{ id: 'sop-1', name: 'research-sop', description: null, created_at: '', updated_at: '' }] }
      }
      return { data: [] }
    })
  })

  it('renders all seven equipment slots', () => {
    renderSlots()

    expect(screen.getByText('agents.panel.slots.role.label')).toBeDefined()
    expect(screen.getByText('agents.panel.slots.identity.label')).toBeDefined()
    expect(screen.getByText('agents.panel.slots.skills.label')).toBeDefined()
    expect(screen.getByText('agents.panel.slots.sops.label')).toBeDefined()
    expect(screen.getByText('agents.panel.slots.input_data_type.label')).toBeDefined()
    expect(screen.getByText('agents.panel.slots.output_data_type.label')).toBeDefined()
    expect(screen.getByText('agents.panel.slots.model.label')).toBeDefined()
  })

  it('shows empty-slot placeholders for an unequipped agent', () => {
    renderSlots()

    // The input slot always renders its input-type select instead of a
    // placeholder, so the remaining six slots show the dashed placeholder.
    const placeholders = screen.getAllByText('agents.panel.emptySlot')
    expect(placeholders.length).toBe(6)
    expect(screen.getByLabelText('agents.types.inputType')).toBeDefined()
  })

  it('assign-existing picks a role into the draft without API writes', async () => {
    renderSlots()

    // Open the role slot's assign picker (first slot) and pick the role.
    const assignButtons = screen.getAllByRole('button', { name: 'agents.panel.assignExisting' })
    fireEvent.click(assignButtons[0])

    await pickFromSelect('agents.panel.slots.role.label', 'Researcher')

    await waitFor(() => {
      expect(JSON.parse(screen.getByTestId('draft-dump').textContent ?? '{}').roleId).toBe('role-1')
    })
    expect(screen.getByTestId('dirty-dump').textContent).toBe('true')
    expect(mockApiPut).not.toHaveBeenCalled()
    expect(mockApiPost).not.toHaveBeenCalled()
  })

  it('create-new requests the matching dialog per slot', () => {
    const onOpenDialog = vi.fn()
    renderSlots({ onOpenDialog })

    const createButtons = screen.getAllByRole('button', { name: 'agents.panel.createNew' })
    expect(createButtons).toHaveLength(7)
    // Slots render in definition order: role, identity, skills, sops, input, output, model.
    fireEvent.click(createButtons[0])
    expect(onOpenDialog).toHaveBeenLastCalledWith({ kind: 'role' })
    fireEvent.click(createButtons[1])
    expect(onOpenDialog).toHaveBeenLastCalledWith({ kind: 'identity' })
    fireEvent.click(createButtons[2])
    expect(onOpenDialog).toHaveBeenLastCalledWith({ kind: 'skill' })
    fireEvent.click(createButtons[3])
    expect(onOpenDialog).toHaveBeenLastCalledWith({ kind: 'sop' })
    fireEvent.click(createButtons[4])
    expect(onOpenDialog).toHaveBeenLastCalledWith({ kind: 'input_data_type' })
    fireEvent.click(createButtons[5])
    expect(onOpenDialog).toHaveBeenLastCalledWith({ kind: 'output_data_type' })
    fireEvent.click(createButtons[6])
    expect(onOpenDialog).toHaveBeenLastCalledWith({ kind: 'model_config' })
  })

  it('locks the output data type slot for conversational agents', () => {
    renderSlots({ agent: { ...EMPTY_AGENT, input_type: 'conversation' } })

    expect(screen.getByText('agents.panel.lockedOutputNote')).toBeDefined()
    // The locked slot exposes no assign/create actions; the other six do.
    expect(screen.getAllByRole('button', { name: 'agents.panel.createNew' })).toHaveLength(6)
  })

  it('assign-existing on the output slot applies the data type and switches output to typed', async () => {
    renderSlots()

    // Output data type slot is the 6th "Assign existing" button (role, identity, skills, sops, input, output).
    const assignButtons = screen.getAllByRole('button', { name: 'agents.panel.assignExisting' })
    fireEvent.click(assignButtons[5])

    await pickFromSelect('agents.panel.slots.output_data_type.label', 'final-report')

    await waitFor(() => {
      const draft = JSON.parse(screen.getByTestId('draft-dump').textContent ?? '{}')
      expect(draft.outputDataTypeId).toBe('dt-2')
      expect(draft.outputType).toBe('typed')
    })
  })

  it('assign-existing on the input slot composes the typed input schema from the registry', async () => {
    renderSlots()

    const assignButtons = screen.getAllByRole('button', { name: 'agents.panel.assignExisting' })
    fireEvent.click(assignButtons[4])

    await pickFromSelect('agents.panel.slots.input_data_type.label', 'research-summary')

    await waitFor(() => {
      const draft = JSON.parse(screen.getByTestId('draft-dump').textContent ?? '{}')
      expect(draft.inputType).toBe('typed')
      expect(draft.inputSchema).toEqual({
        type: 'object',
        properties: { topic: { type: 'string' } },
        required: ['topic'],
      })
    })
  })

  it('disables slot actions with an explanation when the backing list query is denied (403)', async () => {
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/agents/roles') {
        throw Object.assign(new Error('Request failed with status code 403'), {
          response: { status: 403 },
        })
      }
      if (url === '/agents/identities') return { data: [] }
      if (url === '/skills') return { data: [] }
      if (url === '/sops') return { data: [] }
      return { data: [] }
    })

    renderSlots()

    // The denied slot shows the explanatory permission note instead of an error.
    await waitFor(() => {
      expect(screen.getByText('agents.panel.permissionNote')).toBeDefined()
    })
    // Only six create actions remain (the denied role slot's actions are gone).
    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: 'agents.panel.createNew' })).toHaveLength(6)
    })
  })

  it('truncates long equipped names with ellipsis + tooltip and keeps buttons outside the truncating box', async () => {
    const LONG_NAME =
      'an-extremely-long-resource-name-designed-to-overflow-the-property-bar-column'
    mockApiGet.mockImplementation(async (url: string) => {
      if (url === '/agents/roles') {
        return { data: [{ id: 'role-1', name: LONG_NAME, description: null, created_at: '', updated_at: '' }] }
      }
      if (url === '/agents/identities') {
        return { data: [{ id: 'identity-1', name: LONG_NAME, created_at: '', updated_at: '' }] }
      }
      if (url === '/skills') {
        return { data: [{ id: 'skill-1', name: LONG_NAME, description: null, created_at: '', updated_at: '' }] }
      }
      if (url === '/sops') {
        return { data: [{ id: 'sop-1', name: LONG_NAME, description: null, created_at: '', updated_at: '' }] }
      }
      return { data: [] }
    })
    fixtures.dataTypes[0].name = LONG_NAME
    fixtures.models[0].config_display_name = LONG_NAME

    renderSlots({ agent: EQUIPPED_AGENT })

    // Role, identity, skill, SOP, input data type, and output data type all
    // render the long name — each label must carry the truncation styles.
    // The role/identity/skill/sop lists resolve async (react-query), so wait.
    let truncatingLabels: HTMLElement[] = []
    await waitFor(() => {
      truncatingLabels = screen.getAllByText(LONG_NAME)
      expect(truncatingLabels).toHaveLength(6)
    })
    for (const label of truncatingLabels) {
      expect(label).toHaveStyle({
        overflow: 'hidden',
        'text-overflow': 'ellipsis',
        'white-space': 'nowrap',
      })
    }

    // The model value label (composed id + config display name) truncates too.
    const modelLabel = screen.getByText(`gpt-4o (${LONG_NAME})`)
    expect(modelLabel).toHaveStyle({
      overflow: 'hidden',
      'text-overflow': 'ellipsis',
      'white-space': 'nowrap',
    })

    // Hovering a truncating label reveals the full name in a tooltip.
    fireEvent.mouseOver(truncatingLabels[2]) // the skill chip label
    expect(await screen.findByRole('tooltip')).toHaveTextContent(LONG_NAME)

    // Skill row: order/remove buttons are siblings of the chip — OUTSIDE the
    // truncating box — so they stay visible and clickable.
    const skillChip = truncatingLabels[2].closest('.MuiChip-root') as HTMLElement
    expect(skillChip).not.toBeNull()
    const skillRow = skillChip.parentElement as HTMLElement
    expect(within(skillChip).queryByLabelText('agents.panel.remove')).toBeNull()
    expect(within(skillRow).getAllByLabelText('agents.panel.remove')).toHaveLength(1)
    expect(within(skillRow).getAllByLabelText('agents.panel.bindingOrderUp')).toHaveLength(1)
    expect(within(skillRow).getAllByLabelText('agents.panel.bindingOrderDown')).toHaveLength(1)

    // Deletable chips (role): the remove icon sits inside the chip root but
    // outside the truncating label span.
    const roleChip = truncatingLabels[0].closest('.MuiChip-root') as HTMLElement
    const roleDelete = within(roleChip).getByLabelText('agents.panel.remove')
    expect(truncatingLabels[0].contains(roleDelete)).toBe(false)
  })
})
