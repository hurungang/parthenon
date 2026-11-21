import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { WorkingStepsPanel } from '../components/executions/WorkingStepsPanel'
import type { ExecutionLogEntry, WorkingStep, WorkingStepSpan } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn(),
  },
}))

vi.mock('../hooks/useSessionExecutionLogStream', () => ({
  useSessionExecutionLogStream: () => ({ entries: [] }),
}))

let idCounter = 0
beforeEach(() => {
  idCounter = 0
})

function makeStep(overrides: Partial<WorkingStep> = {}): WorkingStep {
  idCounter++
  return {
    id: `step-${idCounter}`,
    iconType: 'info',
    message: `Step message ${idCounter}`,
    timestamp: '2026-01-01T00:01:00Z',
    detail: null,
    ...overrides,
  }
}

function makeSpan(overrides: Partial<WorkingStepSpan> = {}): WorkingStepSpan {
  idCounter++
  return {
    id: `span-${idCounter}`,
    title: `Span ${idCounter}`,
    iconType: 'info',
    children: [],
    collapsed: false,
    ...overrides,
  }
}

/** Helper: build a Preparation span (expanded by default, info steps). */
function makePrepSpan(steps: WorkingStep[] = []): WorkingStepSpan {
  return makeSpan({
    id: 'span-preparation',
    title: 'Preparation',
    iconType: 'info',
    children: steps,
    collapsed: false,
  })
}

/** Helper: build an Agent Actions span (collapsed by default, contains iteration sub-spans). */
function makeAgentActionsSpan(iterationSpans: WorkingStepSpan[] = []): WorkingStepSpan {
  return makeSpan({
    id: 'span-agent-actions',
    title: 'Agent Actions',
    iconType: 'llm',
    children: iterationSpans,
    collapsed: true,
  })
}

/** Helper: build an iteration sub-span. */
function makeIterationSpan(num: number, steps: WorkingStep[] = []): WorkingStepSpan {
  return makeSpan({
    id: `iteration-${num}`,
    title: `Iteration ${num}`,
    iconType: 'llm',
    children: steps,
    collapsed: false,
  })
}

function makeLogEntry(overrides: Partial<ExecutionLogEntry> = {}): ExecutionLogEntry {
  return {
    id: `log-${Math.random().toString(36).slice(2)}`,
    timestamp: '2026-01-01T00:01:00Z',
    event_type: 'observe',
    log_level: 'INFO',
    message: 'log entry',
    data: {},
    ...overrides,
  }
}

/** Helper: build a delegation card step whose payload names the child session. */
function makeDelegationStep(childSessionId: string): WorkingStep {
  return makeStep({
    iconType: 'delegating',
    message: "Delegating to agent 'research-helper'",
    detail: {
      label: 'delegation_started',
      eventType: 'delegation_started',
      content: JSON.stringify({
        delegation_target: 'research-helper',
        receiver_session_id: childSessionId,
        delegation_depth: 1,
      }),
    },
  })
}

describe('WorkingStepsPanel', () => {
  it('renders the section title', () => {
    render(<WorkingStepsPanel spans={[]} />)
    expect(screen.getByText('agents.sessions.logViewer.workingSteps.title')).toBeDefined()
  })

  it('shows empty message when no spans provided', () => {
    render(<WorkingStepsPanel spans={[]} />)
    expect(screen.getByText('agents.sessions.logViewer.workingSteps.empty')).toBeDefined()
  })

  it('does not show empty message when spans with children are provided', () => {
    const spans = [makePrepSpan([makeStep({ iconType: 'info' })])]
    render(<WorkingStepsPanel spans={spans} />)
    expect(
      screen.queryByText('agents.sessions.logViewer.workingSteps.empty')
    ).toBeNull()
  })

  it('renders span titles as headings', () => {
    const spans = [makePrepSpan([makeStep()])]
    render(<WorkingStepsPanel spans={spans} />)
    expect(screen.getByText('Preparation')).toBeDefined()
  })

  it('expanded span (collapsed=false) shows its child steps', () => {
    const step = makeStep({ message: 'Visible step message' })
    const spans = [makePrepSpan([step])]
    render(<WorkingStepsPanel spans={spans} />)
    expect(screen.getByText('Visible step message')).toBeDefined()
  })

  it('Agent Actions span starts collapsed (aria-expanded="false")', () => {
    const llmStep = makeStep({ iconType: 'llm', message: 'LLM call' })
    const iterSpan = makeIterationSpan(1, [llmStep])
    const actionsSpan = makeAgentActionsSpan([iterSpan])
    render(<WorkingStepsPanel spans={[actionsSpan]} />)

    // The span header button should have aria-expanded="false"
    const toggleBtn = screen.getByText('Agent Actions').closest('[role="button"]')
    expect(toggleBtn?.getAttribute('aria-expanded')).toBe('false')
  })

  it('clicking collapsed span toggles it to expanded', () => {
    const actionsSpan = makeAgentActionsSpan([makeIterationSpan(1, [makeStep()])])
    render(<WorkingStepsPanel spans={[actionsSpan]} />)

    const toggleBtn = screen.getByText('Agent Actions').closest('[role="button"]')!
    fireEvent.click(toggleBtn)
    expect(toggleBtn.getAttribute('aria-expanded')).toBe('true')
  })

  it('clicking expanded span toggles it back to collapsed', () => {
    const prepSpan = makePrepSpan([makeStep()])
    render(<WorkingStepsPanel spans={[prepSpan]} />)

    const toggleBtn = screen.getByText('Preparation').closest('[role="button"]')!
    fireEvent.click(toggleBtn) // collapse
    expect(toggleBtn.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(toggleBtn) // expand again
    expect(toggleBtn.getAttribute('aria-expanded')).toBe('true')
  })

  it('renders nested iteration sub-spans inside Agent Actions', () => {
    const iter1 = makeIterationSpan(1, [makeStep({ message: 'iter1 step' })])
    const iter2 = makeIterationSpan(2, [makeStep({ message: 'iter2 step' })])
    const actionsSpan = makeAgentActionsSpan([iter1, iter2])
    render(<WorkingStepsPanel spans={[actionsSpan]} />)

    // Iteration titles are in the DOM even when parent is collapsed
    expect(screen.getByText('Iteration 1')).toBeDefined()
    expect(screen.getByText('Iteration 2')).toBeDefined()
  })

  it('step without detail has no expand detail button', () => {
    const step = makeStep({ detail: null })
    render(<WorkingStepsPanel spans={[makePrepSpan([step])]} />)

    // There should be no step-level detail toggle for steps without detail.
    expect(screen.queryByRole('button', { name: /expand detail|collapse detail/i })).toBeNull()
  })

  it('step with detail shows an expand detail button', () => {
    const step = makeStep({
      iconType: 'success',
      message: 'Step with detail',
      detail: { label: 'myTool', content: '{"input": 1}' },
    })
    render(<WorkingStepsPanel spans={[makePrepSpan([step])]} />)

    // The section starts collapsed — expand it first
    const sectionToggle = screen.getByRole('button', { name: /agents.sessions.logViewer.workingSteps.title/i })
    fireEvent.click(sectionToggle)

    const detailBtn = screen.getByRole('button', { name: /expand detail|collapse detail/i })
    expect(detailBtn).toBeDefined()
    expect(detailBtn.getAttribute('aria-expanded')).toBe('false')
  })

  it('clicking step expand button reveals detail content', () => {
    const step = makeStep({
      detail: { label: 'myTool', content: '{"input": 1}' },
    })
    render(<WorkingStepsPanel spans={[makePrepSpan([step])]} />)

    // The section starts collapsed — expand it first
    const sectionToggle = screen.getByRole('button', { name: /agents.sessions.logViewer.workingSteps.title/i })
    fireEvent.click(sectionToggle)

    const detailBtn = screen.getByRole('button', { name: /expand detail|collapse detail/i })
    fireEvent.click(detailBtn)

    expect(detailBtn.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByText('myTool')).toBeDefined()
  })

  it('clicking expanded step detail button collapses it', () => {
    const step = makeStep({
      detail: { label: 'myTool', content: '{}' },
    })
    render(<WorkingStepsPanel spans={[makePrepSpan([step])]} />)

    // The section starts collapsed — expand it first
    const sectionToggle = screen.getByRole('button', { name: /agents.sessions.logViewer.workingSteps.title/i })
    fireEvent.click(sectionToggle)

    const detailBtn = screen.getByRole('button', { name: /expand detail|collapse detail/i })
    fireEvent.click(detailBtn)
    fireEvent.click(detailBtn)

    expect(detailBtn.getAttribute('aria-expanded')).toBe('false')
  })

  it('handles keyboard Enter to toggle span', () => {
    const actionsSpan = makeAgentActionsSpan([makeIterationSpan(1)])
    render(<WorkingStepsPanel spans={[actionsSpan]} />)

    const toggleBtn = screen.getByText('Agent Actions').closest('[role="button"]')!
    fireEvent.keyDown(toggleBtn, { key: 'Enter' })

    expect(toggleBtn.getAttribute('aria-expanded')).toBe('true')
  })

  it('handles keyboard Space to toggle span', () => {
    const actionsSpan = makeAgentActionsSpan([makeIterationSpan(1)])
    render(<WorkingStepsPanel spans={[actionsSpan]} />)

    const toggleBtn = screen.getByText('Agent Actions').closest('[role="button"]')!
    fireEvent.keyDown(toggleBtn, { key: ' ' })

    expect(toggleBtn.getAttribute('aria-expanded')).toBe('true')
  })
})

// ── Delegation card: direct-child progress peek scoping ─────────────────────

describe('WorkingStepsPanel delegation card peek', () => {
  const CHILD_SESSION_ID = 'child-session-123'

  async function renderDelegationCard(onViewSubAgentExecution = vi.fn()) {
    const apiClient = (await import('../api/apiClient')).default
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === `/agents/sessions/${CHILD_SESSION_ID}`) {
        return Promise.resolve({ data: { status: 'completed' } })
      }
      if (url === `/agents/sessions/${CHILD_SESSION_ID}/logs`) {
        return Promise.resolve({
          data: [
            makeLogEntry({
              id: 'child-init',
              event_type: 'agent_initialized',
              message: 'Child initialised',
            }),
            makeLogEntry({
              id: 'child-delegation-tool-call',
              event_type: 'tool_call',
              message: 'Tool call: agent____grandchild-agent',
              data: { tool: 'agent____grandchild-agent' },
            }),
            makeLogEntry({
              id: 'child-legacy-delegation',
              event_type: 'tool_call',
              message: 'Tool call: agent__legacy-grandchild',
              data: { tool: 'agent__legacy-grandchild' },
            }),
            makeLogEntry({
              id: 'child-delegation-response',
              event_type: 'tool_response',
              message: 'Delegation response to parent LLM',
              data: { delegation_target: 'grandchild-agent' },
            }),
            makeLogEntry({
              id: 'child-delegation-lifecycle',
              event_type: 'delegation_started',
              message: 'Grandchild delegation started',
              data: { delegation_target: 'grandchild-agent' },
            }),
            makeLogEntry({
              id: 'child-model-request',
              event_type: 'llm_request',
              message: 'Child model request',
            }),
            makeLogEntry({
              id: 'child-mcp-tool',
              event_type: 'tool_call',
              message: 'Tool call: server____search',
              data: { tool: 'server____search' },
            }),
            makeLogEntry({
              id: 'child-completed',
              event_type: 'session_completed',
              message: 'Child completed',
            }),
          ],
        })
      }
      return Promise.resolve({ data: [] })
    })

    render(
      <WorkingStepsPanel
        spans={[makePrepSpan([makeDelegationStep(CHILD_SESSION_ID)])]}
        onViewSubAgentExecution={onViewSubAgentExecution}
      />,
    )
    await waitFor(() => expect(screen.getByText('Child initialised')).toBeDefined())
    return { apiClient, onViewSubAgentExecution }
  }

  it('shows the child’s own activity in the peek', async () => {
    await renderDelegationCard()

    expect(screen.getByText('Child initialised')).toBeDefined()
    expect(screen.getByText('Child model request')).toBeDefined()
    expect(screen.getByText('Tool call: server____search')).toBeDefined()
    expect(screen.getByText('Child completed')).toBeDefined()
  })

  it('excludes the child’s onward delegation from the peek', async () => {
    await renderDelegationCard()

    expect(screen.queryByText('Tool call: agent____grandchild-agent')).toBeNull()
    expect(screen.queryByText('Tool call: agent__legacy-grandchild')).toBeNull()
    expect(screen.queryByText('Delegation response to parent LLM')).toBeNull()
    expect(screen.queryByText('Grandchild delegation started')).toBeNull()
  })

  it('fetches the child log unfiltered for drill-in and keeps the action wired', async () => {
    const { apiClient, onViewSubAgentExecution } = await renderDelegationCard()

    // The component still reads the child's RAW log (the helper only filters the peek projection).
    expect(
      (apiClient.get as ReturnType<typeof vi.fn>).mock.calls.some(
        (call) => call[0] === `/agents/sessions/${CHILD_SESSION_ID}/logs`,
      ),
    ).toBe(true)

    const drillIn = await screen.findByRole('button', { name: /View Execution Logs/ })
    fireEvent.click(drillIn)
    expect(onViewSubAgentExecution).toHaveBeenCalledWith(CHILD_SESSION_ID)
  })
})
