import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { useQuery } from '@tanstack/react-query'
import { AgentDetailBubble } from '../components/agents/AgentDetailBubble'
import type { RuntimeTopologyNode } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// The bubble reads the backing job's guardrail usage via react-query;
// stub useQuery so tests control what usage data the bubble sees.
vi.mock('@tanstack/react-query', () => ({
  useQuery: vi.fn(),
}))

vi.mock('../hooks/useAgentTypes', () => ({
  useAgentType: () => ({
    data: {
      id: 'at-1',
      name: 'Support Agent',
      guardrail_max_iterations: 10,
      guardrail_max_delegation_depth: 3,
      guardrail_max_delegated_steps: 20,
      guardrail_token_budget: 5000,
    },
  }),
}))

vi.mock('../hooks/useConversationSessions', () => ({
  useConversationSessions: vi.fn(() => ({ data: undefined })),
  useEndConversationSession: () => ({
    mutateAsync: vi.fn().mockResolvedValue({ id: 'conv-1', status: 'closed' }),
    isPending: false,
  }),
}))

// Isolate the (heavy) execution-log dialog behind a stub.
vi.mock('../components/agents/AgentExecutionDetailsDialog', () => ({
  AgentExecutionDetailsDialog: ({ sessionId }: { sessionId: string }) => (
    <div data-testid="execution-log-dialog">execution-log-{sessionId}</div>
  ),
}))

import { useConversationSessions } from '../hooks/useConversationSessions'

const useQueryMock = vi.mocked(useQuery)
const useConversationSessionsMock = vi.mocked(useConversationSessions)

function makeNode(overrides: Partial<RuntimeTopologyNode> = {}): RuntimeTopologyNode {
  return {
    session_id: 'sess-001',
    agent_type_id: 'at-1',
    agent_type_name: 'Support Agent',
    status: 'running',
    depth_from_root: 1,
    parent_session_id: 'parent-001',
    started_at: null,
    created_at: '2026-06-01T00:00:00Z',
    termination_category: null,
    kind: 'agent',
    ...overrides,
  }
}

/** Stub the session fetch with an output_data.guardrail_usage payload. */
function mockAgentJobUsage(usage: Record<string, unknown> | null) {
  useQueryMock.mockReturnValue({
    data:
      usage === null
        ? null
        : { output_data: usage === undefined ? null : { guardrail_usage: usage } },
  } as never)
}

/** The guardrail summary is folded by default — expand it via the toggle. */
function expandGuardrails() {
  fireEvent.click(screen.getByTestId('agent-detail-guardrails-toggle'))
}

describe('AgentDetailBubble', () => {
  beforeEach(() => {
    useQueryMock.mockReset()
    // Default: no session data fetched (undefined → "—" fallbacks).
    useQueryMock.mockReturnValue({ data: undefined } as never)
    useConversationSessionsMock.mockReset()
    useConversationSessionsMock.mockReturnValue({ data: undefined } as never)
  })

  it('renders agent detail, terminate action, and guardrail summary', () => {
    render(
      <AgentDetailBubble
        node={makeNode()}
        position={{ left: 0, top: 0 }}
        onDismiss={vi.fn()}
        onTerminate={vi.fn()}
      />,
    )

    expect(screen.getByTestId('agent-detail-bubble')).toBeDefined()
    expect(screen.getByText('Support Agent')).toBeDefined()
    expect(screen.getByText('sess-001')).toBeDefined()
    // Guardrail summary section — folded by default, expand to see rows.
    expect(screen.getByText('agents.sessions.runtimeMonitorGuardrailSummary')).toBeDefined()
    expandGuardrails()
    expect(screen.getByText('agents.sessions.logViewer.summary.currentSessionTokens')).toBeDefined()
    expect(screen.getByTestId('guardrail-usage-tokens').textContent).toBe('— / 5k')
    expect(screen.getByTestId('guardrail-usage-iterations').textContent).toBe('— / 10')
    expect(screen.getByTestId('guardrail-usage-delegated-steps').textContent).toBe('— / 20')
    expect(screen.getByTestId('guardrail-usage-delegation-depth').textContent).toBe('— / 3')
    // Terminate action (non-sleep node)
    expect(screen.getByTestId('terminate-node-button')).toBeDefined()
  })

  it('renders guardrail usage rows from the session output_data', () => {
    mockAgentJobUsage({
      token_usage_current_session: 1234,
      token_budget: 5000,
      cumulative_iterations: 2,
      max_iterations: 10,
      delegated_steps: 1,
      max_delegated_steps: 20,
      delegation_depth: 1,
      max_delegation_depth: 3,
    })
    render(
      <AgentDetailBubble
        node={makeNode()}
        position={{ left: 0, top: 0 }}
        onDismiss={vi.fn()}
        onTerminate={vi.fn()}
      />,
    )

    expandGuardrails()
    expect(screen.getByTestId('guardrail-usage-tokens').textContent).toBe('1.2k / 5k')
    expect(screen.getByTestId('guardrail-usage-iterations').textContent).toBe('2 / 10')
    expect(screen.getByTestId('guardrail-usage-delegated-steps').textContent).toBe('1 / 20')
    expect(screen.getByTestId('guardrail-usage-delegation-depth').textContent).toBe('1 / 3')
  })

  it('flags near-limit and over-limit usage rows (non-color cue)', () => {
    mockAgentJobUsage({
      token_usage_current_session: 4600, // 92% → near (warning)
      cumulative_iterations: 11, // > max_iterations → over (error)
      delegated_steps: 1, // no limit → no state
    })
    render(
      <AgentDetailBubble
        node={makeNode()}
        position={{ left: 0, top: 0 }}
        onDismiss={vi.fn()}
        onTerminate={vi.fn()}
      />,
    )

    expandGuardrails()
    expect(screen.getByTestId('guardrail-usage-tokens').getAttribute('data-state')).toBe('near')
    expect(screen.getByTestId('guardrail-usage-iterations').getAttribute('data-state')).toBe('over')
    // delegated_steps 1/20 → well within limits; delegation depth has no usage.
    expect(screen.getByTestId('guardrail-usage-delegated-steps').getAttribute('data-state')).toBe(
      'good',
    )
    expect(screen.getByTestId('guardrail-usage-delegation-depth').getAttribute('data-state')).toBe(
      'none',
    )
  })

  it('falls back to "—" when output_data has no guardrail usage', () => {
    mockAgentJobUsage(null)
    render(
      <AgentDetailBubble
        node={makeNode()}
        position={{ left: 0, top: 0 }}
        onDismiss={vi.fn()}
        onTerminate={vi.fn()}
      />,
    )

    expandGuardrails()
    expect(screen.getByTestId('guardrail-usage-tokens').textContent).toBe('— / 5k')
    expect(screen.getByTestId('guardrail-usage-iterations').textContent).toBe('— / 10')
  })

  it('renders guardrail usage from the conversation session for conversation nodes', () => {
    useConversationSessionsMock.mockReturnValue({
      data: [
        {
          id: 'conv-other',
          guardrail_usage: { token_usage_current_session: 1 },
        },
        {
          id: 'conv-001',
          guardrail_usage: {
            token_usage_current_session: 900,
            token_budget: 1000,
            cumulative_iterations: 1,
            max_iterations: 4,
          },
        },
      ],
    } as never)
    render(
      <AgentDetailBubble
        node={makeNode({ kind: 'conversation', status: 'sleep', parent_session_id: null, session_id: 'conv-001' })}
        position={{ left: 0, top: 0 }}
        onDismiss={vi.fn()}
        onTerminate={vi.fn()}
      />,
    )

    expandGuardrails()
    expect(screen.getByTestId('guardrail-usage-tokens').textContent).toBe('0.9k / 1k')
    expect(screen.getByTestId('guardrail-usage-iterations').textContent).toBe('1 / 4')
  })

  // ── Execution log link (agent-kind only) ─────────────────────────────────────

  it('shows the execution log link for agent-kind nodes and opens the dialog', () => {
    render(
      <AgentDetailBubble
        node={makeNode()}
        position={{ left: 0, top: 0 }}
        onDismiss={vi.fn()}
        onTerminate={vi.fn()}
      />,
    )

    expect(screen.queryByTestId('execution-log-dialog')).toBeNull()
    fireEvent.click(screen.getByTestId('agent-detail-execution-log'))
    expect(screen.getByTestId('execution-log-dialog').textContent).toBe(
      'execution-log-sess-001',
    )
  })

  it('hides the execution log link for conversation and instance nodes', () => {
    render(
      <AgentDetailBubble
        node={makeNode({ kind: 'conversation', status: 'sleep', parent_session_id: null })}
        position={{ left: 0, top: 0 }}
        onDismiss={vi.fn()}
        onTerminate={vi.fn()}
      />,
    )
    expect(screen.queryByTestId('agent-detail-execution-log')).toBeNull()

    render(
      <AgentDetailBubble
        node={makeNode({ kind: 'instance', status: 'active', parent_session_id: null })}
        position={{ left: 40, top: 0 }}
        onDismiss={vi.fn()}
        onTerminate={vi.fn()}
      />,
    )
    expect(screen.queryAllByTestId('agent-detail-execution-log')).toHaveLength(0)
  })

  it('opens terminate flow via onTerminate callback', () => {
    const onTerminate = vi.fn()
    render(
      <AgentDetailBubble
        node={makeNode()}
        position={{ left: 0, top: 0 }}
        onDismiss={vi.fn()}
        onTerminate={onTerminate}
      />,
    )

    fireEvent.click(screen.getByTestId('terminate-node-button'))
    expect(onTerminate).toHaveBeenCalledTimes(1)
    expect(onTerminate).toHaveBeenCalledWith(expect.objectContaining({ session_id: 'sess-001' }))
  })

  it('is dismissible via the close button', () => {
    const onDismiss = vi.fn()
    render(
      <AgentDetailBubble
        node={makeNode()}
        position={{ left: 0, top: 0 }}
        onDismiss={onDismiss}
        onTerminate={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByTestId('agent-detail-bubble-close'))
    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it('shows End Session (not Terminate) for a sleeping conversation node', () => {
    render(
      <AgentDetailBubble
        node={makeNode({ kind: 'conversation', status: 'sleep', parent_session_id: null })}
        position={{ left: 0, top: 0 }}
        onDismiss={vi.fn()}
        onTerminate={vi.fn()}
      />,
    )

    expect(screen.getByTestId('end-conversation-button')).toBeDefined()
    expect(screen.queryByTestId('terminate-node-button')).toBeNull()
  })

  // ── Trigger provenance (refined feature) ─────────────────────────────────────

  it('shows the triggering user as the trigger source', () => {
    render(
      <AgentDetailBubble
        node={makeNode({
          trigger_source: 'user',
          trigger_source_label: 'Alice Operator',
        })}
        position={{ left: 0, top: 0 }}
        onDismiss={vi.fn()}
        onTerminate={vi.fn()}
      />,
    )

    expect(screen.getByText('agents.sessions.runtimeTriggeredByLabel')).toBeDefined()
    expect(screen.getByTestId('agent-detail-trigger-source')).toBeDefined()
    expect(screen.getByText('Alice Operator')).toBeDefined()
  })

  it('shows the schedule CREATOR (never the schedule name) as the trigger source', () => {
    // Phase 13: the "Triggered by" row must name the triggering HUMAN —
    // for schedule-triggered nodes that is the schedule's creator
    // (`trigger_user_label`); the schedule name only identifies the
    // schedule entity and must never render as a person.
    render(
      <AgentDetailBubble
        node={makeNode({
          trigger_source: 'schedule',
          trigger_source_label: 'nightly-cleanup',
          trigger_user_label: 'Alice Operator',
        })}
        position={{ left: 0, top: 0 }}
        onDismiss={vi.fn()}
        onTerminate={vi.fn()}
      />,
    )

    expect(screen.getByTestId('agent-detail-trigger-source')).toBeDefined()
    expect(screen.getByText('Alice Operator')).toBeDefined()
    expect(screen.queryByText('nightly-cleanup')).toBeNull()
  })

  it('shows the unknown label for a schedule-triggered node without a known creator', () => {
    // Phase 13: the schedule name is no longer substituted for the human —
    // an unknown creator degrades to the unknown label.
    render(
      <AgentDetailBubble
        node={makeNode({
          trigger_source: 'schedule',
          trigger_source_label: 'nightly-cleanup',
          trigger_user_label: null,
        })}
        position={{ left: 0, top: 0 }}
        onDismiss={vi.fn()}
        onTerminate={vi.fn()}
      />,
    )

    expect(screen.getByTestId('agent-detail-trigger-source')).toBeDefined()
    expect(screen.getByText('agents.sessions.runtimeTriggerSourceUnknown')).toBeDefined()
    expect(screen.queryByText('nightly-cleanup')).toBeNull()
  })

  it('does not show a trigger source row for an unknown-trigger node', () => {
    render(
      <AgentDetailBubble
        node={makeNode({ trigger_source: 'unknown', trigger_source_label: null })}
        position={{ left: 0, top: 0 }}
        onDismiss={vi.fn()}
        onTerminate={vi.fn()}
      />,
    )

    expect(screen.queryByTestId('agent-detail-trigger-source')).toBeNull()
    expect(screen.queryByText('agents.sessions.runtimeTriggeredByLabel')).toBeNull()
  })

  it('shows the latest tool call when present', () => {
    render(
      <AgentDetailBubble
        node={makeNode({
          tool_calls: [
            { tool_name: 'github____list_prs', mcp_slug: 'github', called_at: null },
          ],
        })}
        position={{ left: 0, top: 0 }}
        onDismiss={vi.fn()}
        onTerminate={vi.fn()}
      />,
    )

    expect(screen.getByTestId('agent-detail-latest-tool-call')).toBeDefined()
    expect(screen.getByText('github____list_prs')).toBeDefined()
  })
})
