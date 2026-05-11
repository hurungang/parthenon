import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import React from 'react'
import type { AgentPlan } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, opts?: Record<string, unknown>) => opts?.defaultValue ?? k }),
}))

// Mock TopologyDiagramRenderer to avoid SVG rendering complexity
vi.mock('../components/agents/TopologyDiagramRenderer', () => ({
  default: ({ nodes, edges }: { nodes: unknown[]; edges: unknown[] }) => (
    <div data-testid="topology-renderer">
      <span data-testid="node-count">{nodes.length}</span>
      <span data-testid="edge-count">{edges.length}</span>
    </div>
  ),
}))

// ── Test fixtures ──────────────────────────────────────────────────────────────

const SUCCESS_PLAN: AgentPlan = {
  id: 'plan-1',
  agent_type_id: 'at-1',
  plan_steps: [
    { order: 1, type: 'sop_invocation', name: 'Initialize', description: 'Set up context' },
    { order: 2, type: 'skill_invocation', name: 'Search', description: 'Perform search' },
    { order: 3, type: 'tool_call', name: 'Save Result', description: null },
  ],
  topology_nodes: [
    { id: 'role:r1', type: 'role', label: 'My Role' },
    { id: 'skill:s1', type: 'skill', label: 'My Skill' },
  ],
  topology_edges: [{ source: 'role:r1', target: 'skill:s1', label: 'uses skill' }],
  generation_status: 'success',
  generation_error: null,
  agent_config_hash: 'abc123',
  generated_at: '2026-05-09T12:00:00Z',
}

const FAILED_PLAN: AgentPlan = {
  id: 'plan-2',
  agent_type_id: 'at-2',
  plan_steps: [],
  topology_nodes: [],
  topology_edges: [],
  generation_status: 'failed',
  generation_error: 'LLM connection timeout',
  agent_config_hash: null,
  generated_at: null,
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('PlanPreviewModal', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders plan steps when generation_status is success', async () => {
    const { PlanPreviewModal } = await import('../components/agents/PlanPreviewModal')
    const onClose = vi.fn()

    render(
      <PlanPreviewModal
        open={true}
        onClose={onClose}
        plan={SUCCESS_PLAN}
        agentTypeName="Test Agent"
      />,
    )

    // All 3 steps should be in the DOM
    expect(screen.getByText('Initialize')).toBeDefined()
    expect(screen.getByText('Search')).toBeDefined()
    expect(screen.getByText('Save Result')).toBeDefined()
  })

  it('renders step descriptions for steps that have them', async () => {
    const { PlanPreviewModal } = await import('../components/agents/PlanPreviewModal')

    render(
      <PlanPreviewModal
        open={true}
        onClose={vi.fn()}
        plan={SUCCESS_PLAN}
        agentTypeName="Test Agent"
      />,
    )

    expect(screen.getByText('Set up context')).toBeDefined()
    expect(screen.getByText('Perform search')).toBeDefined()
  })

  it('renders step-type chips for each step', async () => {
    const { PlanPreviewModal } = await import('../components/agents/PlanPreviewModal')

    render(
      <PlanPreviewModal
        open={true}
        onClose={vi.fn()}
        plan={SUCCESS_PLAN}
        agentTypeName="Test Agent"
      />,
    )

    // Chips use t() for step type labels — key pattern agents.plan.stepTypes.<type>
    expect(screen.getByText('agents.plan.stepTypes.sop_invocation')).toBeDefined()
    expect(screen.getByText('agents.plan.stepTypes.skill_invocation')).toBeDefined()
    expect(screen.getByText('agents.plan.stepTypes.tool_call')).toBeDefined()
  })

  it('delegates topology rendering to TopologyDiagramRenderer with correct props', async () => {
    const { PlanPreviewModal } = await import('../components/agents/PlanPreviewModal')

    render(
      <PlanPreviewModal
        open={true}
        onClose={vi.fn()}
        plan={SUCCESS_PLAN}
        agentTypeName="Test Agent"
      />,
    )

    // TopologyDiagramRenderer mock renders node/edge counts
    const nodeCount = screen.getByTestId('node-count')
    const edgeCount = screen.getByTestId('edge-count')
    expect(nodeCount.textContent).toBe('2')
    expect(edgeCount.textContent).toBe('1')
  })

  it('renders error state when generation_status is failed', async () => {
    const { PlanPreviewModal } = await import('../components/agents/PlanPreviewModal')

    render(
      <PlanPreviewModal
        open={true}
        onClose={vi.fn()}
        plan={FAILED_PLAN}
        agentTypeName="Test Agent"
      />,
    )

    // Error title via t() key
    expect(screen.getByText('agents.plan.generationFailed')).toBeDefined()
    // Error detail — shows generation_error string
    expect(screen.getByText('LLM connection timeout')).toBeDefined()
  })

  it('renders error state when plan is null', async () => {
    const { PlanPreviewModal } = await import('../components/agents/PlanPreviewModal')

    render(
      <PlanPreviewModal
        open={true}
        onClose={vi.fn()}
        plan={null}
        agentTypeName="Test Agent"
      />,
    )

    // Null plan → shows failed state
    expect(screen.getByText('agents.plan.generationFailed')).toBeDefined()
  })

  it('calls onClose when close button is clicked', async () => {
    const { PlanPreviewModal } = await import('../components/agents/PlanPreviewModal')
    const onClose = vi.fn()

    render(
      <PlanPreviewModal
        open={true}
        onClose={onClose}
        plan={SUCCESS_PLAN}
        agentTypeName="Test Agent"
      />,
    )

    const closeBtn = screen.getByRole('button', { name: /agents\.plan\.close/i })
    fireEvent.click(closeBtn)
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('is not rendered when open is false', async () => {
    const { PlanPreviewModal } = await import('../components/agents/PlanPreviewModal')

    render(
      <PlanPreviewModal
        open={false}
        onClose={vi.fn()}
        plan={SUCCESS_PLAN}
        agentTypeName="Test Agent"
      />,
    )

    // MUI Dialog with open=false does not render its content in the DOM
    expect(screen.queryByText('Initialize')).toBeNull()
  })

  it('uses t() i18n keys for dialog title', async () => {
    const { PlanPreviewModal } = await import('../components/agents/PlanPreviewModal')

    render(
      <PlanPreviewModal
        open={true}
        onClose={vi.fn()}
        plan={SUCCESS_PLAN}
        agentTypeName="My Test Agent"
      />,
    )

    // Title should contain the t() key (our mock returns the key)
    expect(screen.getByText('agents.plan.previewTitle')).toBeDefined()
  })

  it('uses t() i18n key for steps section heading', async () => {
    const { PlanPreviewModal } = await import('../components/agents/PlanPreviewModal')

    render(
      <PlanPreviewModal
        open={true}
        onClose={vi.fn()}
        plan={SUCCESS_PLAN}
        agentTypeName="Test Agent"
      />,
    )

    expect(screen.getByText('agents.plan.steps')).toBeDefined()
  })

  it('uses t() i18n key for close button text', async () => {
    const { PlanPreviewModal } = await import('../components/agents/PlanPreviewModal')

    render(
      <PlanPreviewModal
        open={true}
        onClose={vi.fn()}
        plan={SUCCESS_PLAN}
        agentTypeName="Test Agent"
      />,
    )

    expect(screen.getByText('agents.plan.close')).toBeDefined()
  })

  it('renders noSteps message when plan has empty plan_steps', async () => {
    const { PlanPreviewModal } = await import('../components/agents/PlanPreviewModal')

    const emptyStepsPlan: AgentPlan = {
      ...SUCCESS_PLAN,
      plan_steps: [],
      topology_nodes: [],
      topology_edges: [],
    }

    render(
      <PlanPreviewModal
        open={true}
        onClose={vi.fn()}
        plan={emptyStepsPlan}
        agentTypeName="Test Agent"
      />,
    )

    expect(screen.getByText('agents.plan.noSteps')).toBeDefined()
  })
})
