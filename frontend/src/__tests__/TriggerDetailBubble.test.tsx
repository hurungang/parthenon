import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { TriggerDetailBubble } from '../components/agents/TriggerDetailBubble'
import type { TriggerExecution } from '../components/agents/TriggerDetailBubble'

const useQueryMock = vi.hoisted(() => vi.fn())
vi.mock('@tanstack/react-query', () => ({
  useQuery: useQueryMock,
}))

vi.mock('react-i18next', () => ({
  // Interpolate only the `count` param (execution-count heading); every
  // other call — including `t(key, defaultValueString)` — resolves to the
  // raw key.
  useTranslation: () => ({
    t: (k: string, params?: unknown) =>
      params !== null && typeof params === 'object' && 'count' in params
        ? `${k} (${String((params as Record<string, unknown>).count)})`
        : k,
  }),
}))

const EXECUTIONS: TriggerExecution[] = [
  { sessionId: 's-1', label: 'Alpha Agent', status: 'running' },
  { sessionId: 's-2', label: 'Beta Agent', status: 'completed' },
]

function renderBubble(overrides: Partial<React.ComponentProps<typeof TriggerDetailBubble>> = {}) {
  const props = {
    entityKey: 'person:Alice',
    kind: 'person' as const,
    name: 'Alice',
    creator: null,
    executions: EXECUTIONS,
    position: { left: 10, top: 20 },
    onSelectExecution: vi.fn(),
    onDismiss: vi.fn(),
    ...overrides,
  }
  return render(<TriggerDetailBubble {...props} />)
}

describe('TriggerDetailBubble', () => {
  beforeEach(() => {
    useQueryMock.mockReset()
    useQueryMock.mockReturnValue({ data: undefined, isLoading: false })
  })

  it('renders a person bubble with name, kind caption, execution count and rows', () => {
    renderBubble()

    const bubble = screen.getByTestId('trigger-detail-bubble')
    expect(bubble.getAttribute('data-trigger-entity')).toBe('person:Alice')

    // Header + kind caption.
    expect(within(bubble).getByText('Alice')).toBeDefined()
    expect(within(bubble).getByText('agents.sessions.runtimeMonitorTriggerPersonKind')).toBeDefined()

    // Count heading reflects the executions length.
    expect(
      within(bubble).getByText('agents.sessions.runtimeMonitorTriggerDetailExecutions (2)'),
    ).toBeDefined()

    // One row per execution: agent type label + status chip.
    const row1 = within(bubble).getByTestId('trigger-detail-execution-s-1')
    expect(within(row1).getByText('Alpha Agent')).toBeDefined()
    expect(within(row1).getByText('agents.sessions.statusRunning')).toBeDefined()
    const row2 = within(bubble).getByTestId('trigger-detail-execution-s-2')
    expect(within(row2).getByText('Beta Agent')).toBeDefined()
    expect(within(row2).getByText('agents.sessions.statusCompleted')).toBeDefined()
  })

  it('clicking an execution row calls onSelectExecution with the session id', () => {
    const onSelectExecution = vi.fn()
    renderBubble({ onSelectExecution })

    fireEvent.click(screen.getByTestId('trigger-detail-execution-s-1'))
    expect(onSelectExecution).toHaveBeenCalledTimes(1)
    expect(onSelectExecution).toHaveBeenCalledWith('s-1')

    // Keyboard activation selects too.
    fireEvent.keyDown(screen.getByTestId('trigger-detail-execution-s-2'), { key: 'Enter' })
    expect(onSelectExecution).toHaveBeenLastCalledWith('s-2')
  })

  it('dismisses via the close button', () => {
    const onDismiss = vi.fn()
    renderBubble({ onDismiss })

    fireEvent.click(screen.getByTestId('trigger-detail-bubble-close'))
    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it('renders no creator row for person bubbles', () => {
    renderBubble()
    expect(screen.queryByTestId('trigger-detail-creator')).toBeNull()
  })

  it('renders a schedule bubble with the schedule kind and the creator row when known', () => {
    renderBubble({
      entityKey: 'schedule:nightly',
      kind: 'schedule',
      name: 'nightly',
      creator: 'Tom',
      executions: [{ sessionId: 'sch-run-1', label: 'Nightly Agent', status: 'completed' }],
    })

    const bubble = screen.getByTestId('trigger-detail-bubble')
    expect(within(bubble).getByText('nightly')).toBeDefined()
    expect(within(bubble).getByText('agents.sessions.runtimeMonitorTriggerScheduleKind')).toBeDefined()
    expect(within(bubble).queryByText('agents.sessions.runtimeMonitorTriggerPersonKind')).toBeNull()

    // Creator row — the HUMAN who created the schedule.
    const creatorRow = within(bubble).getByTestId('trigger-detail-creator')
    expect(within(creatorRow).getByText('agents.sessions.runtimeMonitorTriggerDetailCreator')).toBeDefined()
    expect(within(creatorRow).getByText('Tom')).toBeDefined()

    // Executions list still renders.
    expect(
      within(bubble).getByText('agents.sessions.runtimeMonitorTriggerDetailExecutions (1)'),
    ).toBeDefined()
    expect(within(bubble).getByTestId('trigger-detail-execution-sch-run-1')).toBeDefined()
  })

  it('omits the creator row for a schedule with an unknown creator', () => {
    renderBubble({
      entityKey: 'schedule:nightly',
      kind: 'schedule',
      name: 'nightly',
      creator: null,
    })

    expect(screen.getByTestId('trigger-detail-bubble')).toBeDefined()
    expect(screen.queryByTestId('trigger-detail-creator')).toBeNull()
    expect(screen.queryByText('agents.sessions.runtimeMonitorTriggerDetailCreator')).toBeNull()
  })

  it('renders no execution section when the entity has no executions', () => {
    renderBubble({ executions: [] })

    expect(screen.getByTestId('trigger-detail-bubble')).toBeDefined()
    expect(screen.queryByTestId('trigger-detail-executions-heading')).toBeNull()
    expect(screen.queryByTestId('trigger-detail-execution-s-1')).toBeNull()
  })
})

describe('TriggerDetailBubble — trigger-own details', () => {
  it('renders the humanised cron row on a schedule bubble from the cron prop', () => {
    renderBubble({
      entityKey: 'schedule:nightly',
      kind: 'schedule',
      name: 'nightly',
      creator: 'Erin',
      userId: null,
      scheduleId: 'sched-1',
      cron: '0 3 * * *',
    })
    const cronRow = screen.getByTestId('trigger-detail-cron')
    expect(cronRow.textContent).toContain('0 3 * * *')
    // Creator row still present for schedules with a known creator.
    expect(screen.getByTestId('trigger-detail-creator').textContent).toContain(
      'agents.sessions.runtimeMonitorTriggerDetailCreator',
    )
  })

  it('renders person identity details when the identity fetch resolves', () => {
    useQueryMock.mockImplementation((opts: { queryKey: unknown[] }) =>
      opts.queryKey[1] === 'identity' && opts.queryKey[2] === 'ident-1'
        ? { data: { email: 'alice@corp.dev', identity_type: 'user' }, isLoading: false }
        : { data: undefined, isLoading: false },
    )
    renderBubble({ entityKey: 'person:Alice', kind: 'person', name: 'Alice', userId: 'ident-1' })
    expect(screen.getByTestId('trigger-detail-email').textContent).toBe('alice@corp.dev')
    expect(screen.getByTestId('trigger-detail-user-type').textContent).toBe('user')
  })

  it('shows no detail rows for a person without an identity id', () => {
    renderBubble({ userId: null })
    expect(screen.queryByTestId('trigger-detail-rows')).toBeNull()
  })
})
