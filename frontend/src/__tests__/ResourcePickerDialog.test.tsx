import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ResourcePickerDialog, type ResourcePickerItem } from '../components/agents/panel/ResourcePickerDialog'
import { SLOT_PICKER_CONFIGS } from '../components/agents/panel/slotPickerConfigs'
import { useAgentDraftComposition, type UseAgentDraftCompositionResult } from '../hooks/useAgentDraftComposition'
import type { AgentDataType, AgentType } from '../types'

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../components/permissions/PermissionDeniedAlert', () => ({
  default: ({ error }: { error: unknown }) => (
    <div data-testid="permission-denied-alert">
      {error instanceof Error ? error.message : 'error'}
    </div>
  ),
}))

// ── Fixtures ──────────────────────────────────────────────────────────────────

const BASE_ITEMS: ResourcePickerItem[] = [
  { id: 'r1', label: 'alpha-resource', sublabel: 'first resource' },
  { id: 'r2', label: 'beta-resource', sublabel: null },
  { id: 'r3', label: 'gamma-resource', sublabel: 'gamma sublabel' },
]

/** 15 items — two pages at the default 10 rows per page. */
function manyItems(count: number): ResourcePickerItem[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `item-${i + 1}`,
    label: `resource-${String(i + 1).padStart(2, '0')}`,
    sublabel: null,
  }))
}

const INPUT_DATA_TYPE: AgentDataType = {
  id: 'dt-1',
  name: 'research-summary',
  slug: 'research-summary',
  description: null,
  fields: [
    { name: 'topic', type: 'string', required: true, enum_values: null },
  ],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

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

// ── Generic dialog harness ────────────────────────────────────────────────────

interface RenderPickerProps {
  items?: ResourcePickerItem[]
  selectionMode?: 'single' | 'multi'
  initialSelectedIds?: string[]
  /** Change-detection baseline (equipped ids); defaults to initialSelectedIds. */
  baselineIds?: string[]
  error?: unknown
  loading?: boolean
  onCreateNew?: () => void
  onConfirm?: (ids: string[]) => void
}

function renderPicker(props: RenderPickerProps = {}) {
  const onConfirm = props.onConfirm ?? vi.fn()
  const onCreateNew = props.onCreateNew
  const result = render(
    <ResourcePickerDialog
      open
      title="agents.panel.picker.title"
      items={props.items ?? BASE_ITEMS}
      loading={props.loading ?? false}
      error={props.error}
      selectionMode={props.selectionMode ?? 'single'}
      initialSelectedIds={props.initialSelectedIds ?? []}
      baselineIds={props.baselineIds}
      onClose={() => {}}
      onConfirm={onConfirm}
      onCreateNew={onCreateNew}
    />,
  )
  return { onConfirm, ...result }
}

// ── Draft harness for slot-picker config apply semantics ──────────────────────

let capturedApi: UseAgentDraftCompositionResult | null = null

function DraftHarness({ agent }: { agent: AgentType }) {
  const draftApi = useAgentDraftComposition(agent)
  capturedApi = draftApi
  return <pre data-testid="draft-dump">{JSON.stringify(draftApi.draft)}</pre>
}

function draftDump(): Record<string, unknown> {
  return JSON.parse(screen.getByTestId('draft-dump').textContent ?? '{}')
}

/** Renders the draft harness (fresh QueryClient per call) and returns the captured draft API. */
async function withDraftApi(agent?: AgentType): Promise<UseAgentDraftCompositionResult> {
  capturedApi = null
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<DraftHarness agent={agent ?? EMPTY_AGENT} />, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  })
  await waitFor(() => expect(capturedApi).not.toBeNull())
  const api: UseAgentDraftCompositionResult | null = capturedApi
  if (!api) throw new Error('draft API was not captured')
  return api
}

// ── Tests: generic dialog ──────────────────────────────────────────────────────

describe('ResourcePickerDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders rows with label and sublabel', () => {
    renderPicker()

    expect(screen.getByText('alpha-resource')).toBeDefined()
    expect(screen.getByText('first resource')).toBeDefined()
    expect(screen.getByText('beta-resource')).toBeDefined()
    expect(screen.getByText('gamma-resource')).toBeDefined()
  })

  it('search filters rows client-side (debounced commit)', async () => {
    renderPicker()

    fireEvent.change(screen.getByPlaceholderText('agents.panel.picker.searchPlaceholder'), {
      target: { value: 'beta' },
    })

    await waitFor(() => {
      expect(screen.queryByText('alpha-resource')).toBeNull()
    })
    expect(screen.getByText('beta-resource')).toBeDefined()
    // Search also matches the sublabel.
    fireEvent.change(screen.getByPlaceholderText('agents.panel.picker.searchPlaceholder'), {
      target: { value: 'gamma sub' },
    })
    await waitFor(() => {
      expect(screen.queryByText('beta-resource')).toBeNull()
      expect(screen.getByText('gamma-resource')).toBeDefined()
    })
  })

  it('shows an empty-state note when the search matches nothing', async () => {
    renderPicker()

    fireEvent.change(screen.getByPlaceholderText('agents.panel.picker.searchPlaceholder'), {
      target: { value: 'no-such-resource' },
    })

    await waitFor(() => {
      expect(screen.getByText('agents.panel.picker.noMatch')).toBeDefined()
    })
  })

  it('paginates the filtered list and navigates pages', () => {
    renderPicker({ items: manyItems(15) })

    // Default page size 10 → first ten rows only.
    expect(screen.getByText('resource-01')).toBeDefined()
    expect(screen.getByText('resource-10')).toBeDefined()
    expect(screen.queryByText('resource-11')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Go to next page' }))

    expect(screen.getByText('resource-11')).toBeDefined()
    expect(screen.getByText('resource-15')).toBeDefined()
    expect(screen.queryByText('resource-01')).toBeNull()
  })

  it('single mode: replaces the selection, Assign disabled until the value changes', () => {
    const onConfirm = vi.fn()
    renderPicker({ selectionMode: 'single', initialSelectedIds: ['r1'], onConfirm })

    // Pre-selected row, no change yet → Assign disabled.
    expect(screen.getByRole('button', { name: 'agents.panel.picker.assign' })).toHaveAttribute(
      'disabled',
    )
    // Clicking the already-selected row keeps Assign disabled (radio semantics).
    fireEvent.click(screen.getByText('alpha-resource'))
    expect(screen.getByRole('button', { name: 'agents.panel.picker.assign' })).toHaveAttribute(
      'disabled',
    )

    // Picking another row replaces (not adds) and enables Assign.
    fireEvent.click(screen.getByText('beta-resource'))
    const assign = screen.getByRole('button', { name: 'agents.panel.picker.assign' })
    expect(assign).not.toHaveAttribute('disabled')
    fireEvent.click(assign)
    expect(onConfirm).toHaveBeenCalledWith(['r2'])
  })

  it('multi mode: checkboxes pre-check equipped items and confirm the reconciled set', () => {
    const onConfirm = vi.fn()
    renderPicker({ selectionMode: 'multi', initialSelectedIds: ['r1'], onConfirm })

    const first = screen.getByRole('checkbox', { name: 'alpha-resource' }) as HTMLInputElement
    expect(first.checked).toBe(true)

    // Unchanged set → Assign disabled.
    expect(screen.getByRole('button', { name: 'agents.panel.picker.assign' })).toHaveAttribute(
      'disabled',
    )

    // Add r2, remove r1 → reconciled set confirmed on Assign.
    fireEvent.click(screen.getByText('beta-resource'))
    fireEvent.click(screen.getByText('alpha-resource'))
    const assign = screen.getByRole('button', { name: 'agents.panel.picker.assign' })
    expect(assign).not.toHaveAttribute('disabled')
    fireEvent.click(assign)
    expect(onConfirm).toHaveBeenCalledWith(['r2'])
  })

  it('create-new button invokes the slot create flow; the refreshed list pre-selects the created row', () => {
    const onCreateNew = vi.fn()
    const onConfirm = vi.fn()
    const created: ResourcePickerItem = { id: 'created-1', label: 'freshly-created', sublabel: null }

    const { rerender } = renderPicker({
      initialSelectedIds: ['r1'],
      baselineIds: ['r1'],
      onCreateNew,
      onConfirm,
    })

    fireEvent.click(screen.getByRole('button', { name: 'agents.panel.createNew' }))
    expect(onCreateNew).toHaveBeenCalledOnce()

    // Simulate the page contract: the shared dialog created the resource,
    // invalidated the list cache (rows refetch) and preset the created id —
    // while the change baseline stays the equipped value.
    rerender(
      <ResourcePickerDialog
        open
        title="agents.panel.picker.title"
        items={[...BASE_ITEMS, created]}
        loading={false}
        error={null}
        selectionMode="single"
        initialSelectedIds={['created-1']}
        baselineIds={['r1']}
        onClose={() => {}}
        onConfirm={onConfirm}
        onCreateNew={onCreateNew}
      />,
    )

    // The refreshed list contains the created row, pre-selected and assignable.
    expect(screen.getByText('freshly-created')).toBeDefined()
    const assign = screen.getByRole('button', { name: 'agents.panel.picker.assign' })
    expect(assign).not.toHaveAttribute('disabled')
    fireEvent.click(assign)
    expect(onConfirm).toHaveBeenCalledWith(['created-1'])
  })

  it('renders the list error through PermissionDeniedAlert first and disables Assign (403 degradation)', () => {
    renderPicker({ error: new Error('403 Forbidden') })

    const alert = screen.getByTestId('permission-denied-alert')
    expect(alert).toBeDefined()
    expect(alert.textContent).toContain('403 Forbidden')
    expect(screen.queryByText('alpha-resource')).toBeNull()
    expect(screen.getByRole('button', { name: 'agents.panel.picker.assign' })).toHaveAttribute(
      'disabled',
    )
  })

  it('truncates long names with ellipsis and reveals the full text through a tooltip', async () => {
    const LONG_NAME = 'an-extremely-long-resource-name-designed-to-overflow-the-picker-dialog'
    renderPicker({
      items: [{ id: 'long-1', label: LONG_NAME, sublabel: null }],
    })

    const label = screen.getByText(LONG_NAME)
    expect(label).toHaveStyle({
      overflow: 'hidden',
      'text-overflow': 'ellipsis',
      'white-space': 'nowrap',
    })

    fireEvent.mouseOver(label)
    expect(await screen.findByRole('tooltip')).toHaveTextContent(LONG_NAME)
  })
})

// ── Tests: per-slot picker configs (apply / pre-selection semantics) ──────────

describe('SLOT_PICKER_CONFIGS', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    capturedApi = null
  })

  it('role apply replaces the draft role (single-slot replace semantics)', async () => {
    const api = await withDraftApi({ ...EMPTY_AGENT, role_id: 'role-1' })

    SLOT_PICKER_CONFIGS.role.apply(api, ['role-2'], [])

    await waitFor(() => {
      expect(draftDump().roleId).toBe('role-2')
      // Read isDirty from the freshly rendered hook result (the hook returns a
      // new object per render — the initially captured one is stale).
      expect(capturedApi?.isDirty).toBe(true)
    })
  })

  it('skills apply reconciles add/remove while keeping existing order', async () => {
    const equipped: AgentType = {
      ...EMPTY_AGENT,
      skill_bindings: [
        { id: 'sb-1', skill_id: 'skill-1', skill_name: 'skill-one', order: 1, created_at: '2026-01-01T00:00:00Z' },
        { id: 'sb-2', skill_id: 'skill-2', skill_name: 'skill-two', order: 2, created_at: '2026-01-01T00:00:00Z' },
      ],
    }
    const api = await withDraftApi(equipped)

    // Remove skill-1, keep skill-2, add skill-3.
    SLOT_PICKER_CONFIGS.skills.apply(api, ['skill-2', 'skill-3'], [])

    await waitFor(() => {
      const bindings = draftDump().skillBindings as { skill_id: string; order: number }[]
      expect(bindings.map((b) => b.skill_id)).toEqual(['skill-2', 'skill-3'])
      expect(bindings.map((b) => b.order)).toEqual([1, 2])
    })
  })

  it('input_data_type apply composes the typed input schema from the picked registry entry', async () => {
    const api = await withDraftApi()
    const items: ResourcePickerItem[] = [
      { id: 'dt-1', label: 'research-summary', sublabel: null, dataType: INPUT_DATA_TYPE },
    ]

    SLOT_PICKER_CONFIGS.input_data_type.apply(api, ['dt-1'], items)

    await waitFor(() => {
      const draft = draftDump()
      expect(draft.inputType).toBe('typed')
      expect(draft.inputSchema).toEqual({
        type: 'object',
        properties: { topic: { type: 'string' } },
        required: ['topic'],
      })
    })
  })

  it('input_data_type pre-selection resolves the applied schema back to the registry entry', async () => {
    const applied: AgentType = {
      ...EMPTY_AGENT,
      input_type: 'typed',
      input_schema: {
        type: 'object',
        properties: { topic: { type: 'string' } },
        required: ['topic'],
      },
    }
    const api = await withDraftApi(applied)
    const items: ResourcePickerItem[] = [
      { id: 'dt-1', label: 'research-summary', sublabel: null, dataType: INPUT_DATA_TYPE },
      { id: 'dt-2', label: 'other', sublabel: null, dataType: { ...INPUT_DATA_TYPE, id: 'dt-2' } },
    ]

    expect(SLOT_PICKER_CONFIGS.input_data_type.getSelectedIds(api.draft, items)).toEqual(['dt-1'])

    // Untyped draft → nothing pre-selected.
    const empty = await withDraftApi()
    expect(SLOT_PICKER_CONFIGS.input_data_type.getSelectedIds(empty.draft, items)).toEqual([])
  })

  it('output_data_type apply switches output to typed with the picked id', async () => {
    const api = await withDraftApi({ ...EMPTY_AGENT, output_data_type_id: 'dt-1' })

    SLOT_PICKER_CONFIGS.output_data_type.apply(api, ['dt-2'], [])

    await waitFor(() => {
      const draft = draftDump()
      expect(draft.outputType).toBe('typed')
      expect(draft.outputDataTypeId).toBe('dt-2')
    })
  })

  it('model createdSelectionIds maps a created config to its first enabled model', () => {
    expect(
      SLOT_PICKER_CONFIGS.model.createdSelectionIds({
        id: 'mc-new',
        label: 'New Config',
        enabledModelIds: ['gpt-4o', 'gpt-4o-mini'],
      }),
    ).toEqual(['gpt-4o'])

    // No enabled models → no pre-selection.
    expect(
      SLOT_PICKER_CONFIGS.model.createdSelectionIds({ id: 'mc-new', label: 'New Config' }),
    ).toEqual([])
  })
})
