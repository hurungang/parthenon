import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import AgentPlanContent from '../components/agents/AgentPlanContent'
import type { AgentPlan } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../components/agents/TopologyDiagramRenderer', () => ({
  default: ({ nodes }: { nodes: { id: string }[] }) => (
    <div data-testid="plan-topology" data-node-count={nodes.length} />
  ),
}))

const MOCK_PLAN: AgentPlan = {
  id: 'plan-1',
  agent_type_id: 'at-1',
  plan_steps: [{ order: 1, type: 'tool_call', name: 'Search', description: null }],
  topology_nodes: [{ id: 'role:r1', type: 'role', label: 'Role' }],
  topology_edges: [],
  generation_status: 'success',
  generation_error: null,
  agent_config_hash: null,
  generated_at: '2026-01-01T00:00:00Z',
}

describe('AgentPlanContent', () => {
  it('renders the plan-based topology by default', () => {
    render(<AgentPlanContent plan={MOCK_PLAN} />)
    expect(screen.getByTestId('plan-topology')).toBeDefined()
    // Communication Hub is appended client-side.
    expect(screen.getByTestId('plan-topology').getAttribute('data-node-count')).toBe('2')
  })

  it('hides the plan-based topology when hideTopology is set (unified canvas lives elsewhere)', () => {
    render(<AgentPlanContent plan={MOCK_PLAN} hideTopology />)
    expect(screen.queryByTestId('plan-topology')).toBeNull()
    // Plan steps still render.
    expect(screen.getByText('Search')).toBeDefined()
    expect(screen.getByText('agents.plan.steps')).toBeDefined()
  })
})
