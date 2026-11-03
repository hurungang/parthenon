/**
 * Tests for topology token-health badges (token-expiry-alerting):
 * per-container badge derivation in the unified topology canvas and
 * warning/error badge rendering in the shared renderer.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const { mockApiGet } = vi.hoisted(() => ({ mockApiGet: vi.fn() }))

vi.mock('../api/apiClient', () => ({
  default: { get: mockApiGet },
}))

import { PanelTopologyCanvas, buildPanelTopology, worstTokenHealth } from '../components/agents/panel/PanelTopologyCanvas'
import TopologyDiagramRenderer from '../components/agents/TopologyDiagramRenderer'
import type { AgentDraftComposition, TopologyNode } from '../types'

vi.mock('../hooks/useDataTypes', () => ({
  useDataTypes: () => ({ data: undefined }),
}))
vi.mock('../hooks/useAvailableModels', () => ({
  useAvailableModels: () => ({ data: undefined }),
}))
vi.mock('../hooks/useMcpServers', () => ({
  useAllTools: () => ({ data: [] }),
  useMcpServers: () => ({ data: [] }),
}))

const NAMES = {
  roleNames: {},
  identityNames: { 'identity-1': 'svc-agent' },
  skillNames: {},
  sopNames: {},
  dataTypeNames: {},
  modelLabels: {},
  inputDataTypeName: null,
  toolNames: {},
  toolServerSlugs: {},
  toolServerColors: {},
  skillToolIds: {},
  identityTokenHealth: { 'identity-1': 'expired' } as Record<string, 'expiring' | 'expired'>,
  sopComposedSkillIds: {},
}

const LABELS = {
  hub: 'hub',
  empty: {
    role: 'no-role', identity: 'no-identity', skills: 'no-skills', sops: 'no-sops',
    input_data_type: 'no-input', output_data_type: 'no-output', model: 'no-model',
  },
  inputSchemaLabel: 'input',
  inputNone: 'none',
  inputConversation: 'conversation',
  outputLocked: 'locked',
  outputAuto: 'auto',
  boundaryTyped: 'typed',
  boundaryConversational: 'conversational',
  sections: { contract: 'c', signsInAs: 's', assumesAs: 'a', sops: 'sops', skills: 'skills' },
  edges: { equippedWith: 'eq', grants: 'gr', composed: 'co' },
  zones: {
    config: { title: 'cfg', subtitle: '' },
    capabilities: { title: 'cap', subtitle: '' },
    tools: { title: 'tools', subtitle: '' },
  },
  noTools: 'no tools',
  loading: 'loading',
}

const DRAFT: AgentDraftComposition = {
  name: 'research-agent',
  description: '',
  systemInstruction: '',
  guardrails: {
    maxIterations: 10, maxDelegationDepth: 3, maxDelegatedSteps: 20,
    executionTimeoutSeconds: 300, tokenBudget: 100000,
    tokenEnforcementMode: 'observe', tokenFallbackMode: 'observe_and_log',
    conversationalTokenVisibilityMode: 'enabled',
    conversationalContinuationPolicy: 'allow',
  },
  identityId: 'identity-1',
  roleId: null,
  skillBindings: [],
  sopBindings: [],
  inputType: 'none',
  inputSchema: null,
  outputType: 'auto',
  outputSchema: null,
  outputDataTypeId: null,
  modelId: null,
}

beforeEach(() => {
  mockApiGet.mockReset()
  mockApiGet.mockResolvedValue({ data: [] })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('worstTokenHealth', () => {
  it('expired dominates expiring', () => {
    expect(worstTokenHealth('expiring', 'expired')).toBe('expired')
    expect(worstTokenHealth('expired', undefined)).toBe('expired')
    expect(worstTokenHealth('expiring', undefined)).toBe('expiring')
    expect(worstTokenHealth(undefined, undefined)).toBeUndefined()
  })
})

describe('buildPanelTopology token health badges', () => {
  it('badges the identity node and the agent container when the identity expired', () => {
    const { nodes } = buildPanelTopology('research-agent', DRAFT, NAMES, LABELS)
    const identity = nodes.find((n) => n.id === 'identity')
    const agent = nodes.find((n) => n.id === 'agent')
    expect(identity?.tokenHealth).toBe('expired')
    expect(agent?.tokenHealth).toBe('expired')
  })

  it('renders no badge for healthy/unknown identities', () => {
    const { nodes } = buildPanelTopology(
      'research-agent',
      DRAFT,
      { ...NAMES, identityTokenHealth: {} },
      LABELS,
    )
    expect(nodes.find((n) => n.id === 'identity')?.tokenHealth).toBeUndefined()
    expect(nodes.find((n) => n.id === 'agent')?.tokenHealth).toBeUndefined()
  })

  it('renders an expiring (warning) badge state', () => {
    const { nodes } = buildPanelTopology(
      'research-agent',
      DRAFT,
      { ...NAMES, identityTokenHealth: { 'identity-1': 'expiring' } },
      LABELS,
    )
    expect(nodes.find((n) => n.id === 'identity')?.tokenHealth).toBe('expiring')
  })
})

describe('PanelTopologyCanvas derives badge state from the token-health API', () => {
  it('marks the identity node expired when the API reports it expired', async () => {
    mockApiGet.mockImplementation((url: string) => {
      if (url === '/dashboard/token-health') {
        return Promise.resolve({
          data: {
            identities: {
              expired_count: 1, expiring_count: 0, healthy_count: 0, unknown_count: 0,
              items: [
                {
                  id: 'identity-1', name: 'svc-agent', health_state: 'expired',
                  expires_at: null, refresh_expires_at: null,
                  last_refresh_outcome: null, last_refresh_at: null,
                  remediation_target: 'agent_identity', remediation_path: '/agents/identities',
                },
              ],
            },
            mcp_sessions: {
              expired_count: 0, expiring_count: 0, healthy_count: 0, unknown_count: 0, items: [],
            },
            permission_flags: { identities: false, mcp_sessions: false },
          },
        })
      }
      return Promise.resolve({ data: [] })
    })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <PanelTopologyCanvas agentName="research-agent" draft={DRAFT} isDirty={false} />,
      { wrapper: ({ children }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider> },
    )
    await vi.waitFor(() => {
      const badge = screen.getByTestId('topology-token-badge-identity')
      expect(badge.getAttribute('data-token-health')).toBe('expired')
      expect(screen.getByTestId('topology-token-badge-agent').getAttribute('data-token-health')).toBe('expired')
    })
  })
})

describe('TopologyDiagramRenderer badge rendering', () => {
  it('renders an error badge (expired) and a warning badge (expiring), nothing for healthy', () => {
    const nodes: TopologyNode[] = [
      { id: 'a', type: 'identity', label: 'A', tokenHealth: 'expired', zone: 'config' },
      { id: 'b', type: 'identity', label: 'B', tokenHealth: 'expiring', zone: 'config' },
      { id: 'c', type: 'identity', label: 'C', zone: 'config' },
    ]
    const { container } = render(<TopologyDiagramRenderer nodes={nodes} edges={[]} />)
    expect(screen.getByTestId('topology-token-badge-a').getAttribute('data-token-health')).toBe('expired')
    expect(screen.getByTestId('topology-token-badge-b').getAttribute('data-token-health')).toBe('expiring')
    expect(screen.queryByTestId('topology-token-badge-c')).toBeNull()
    expect(container.querySelector('svg')).not.toBeNull()
  })
})
