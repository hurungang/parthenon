import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  PanelTopologyCanvas,
  buildPanelTopology,
  capabilityColor,
} from '../components/agents/panel/PanelTopologyCanvas'
import { emptyDraft } from '../hooks/useAgentDraftComposition'
import type { AgentDraftComposition, TopologyNode, TopologyZone } from '../types'

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const {
  mockApiGet,
  mockTopologyNodes,
  mockTopologyEdges,
  mockTopologyZones,
  mockTopologyHubBar,
  mockViewProps,
} = vi.hoisted(() => ({
  mockApiGet: vi.fn(),
  mockTopologyNodes: [] as unknown[],
  mockTopologyEdges: [] as unknown[],
  mockTopologyZones: [] as unknown[],
  mockTopologyHubBar: [] as unknown[],
  /** Last renderer view props (fullscreen fillHeight + viewBox zoom). */
  mockViewProps: {
    fillHeight: undefined as boolean | undefined,
    viewZoom: undefined as number | undefined,
  },
}))

vi.mock('../api/apiClient', () => ({
  default: { get: mockApiGet },
}))

vi.mock('../components/agents/TopologyDiagramRenderer', () => ({
  default: ({
    nodes,
    edges,
    zones,
    hubBar,
    fillHeight,
    viewZoom,
  }: {
    nodes: unknown[]
    edges: unknown[]
    zones?: unknown[]
    hubBar?: unknown
    fillHeight?: boolean
    viewZoom?: number
  }) => {
    mockTopologyNodes.length = 0
    mockTopologyNodes.push(...nodes)
    mockTopologyEdges.length = 0
    mockTopologyEdges.push(...edges)
    mockTopologyZones.length = 0
    mockTopologyZones.push(...(zones ?? []))
    mockTopologyHubBar.length = 0
    if (hubBar) mockTopologyHubBar.push(hubBar)
    mockViewProps.fillHeight = fillHeight
    mockViewProps.viewZoom = viewZoom
    return <div data-testid="panel-topology" data-node-count={nodes.length} data-edge-count={edges.length} />
  },
}))

// ── Fixtures ──────────────────────────────────────────────────────────────────

const NAMES = {
  roleNames: { 'role-1': 'Researcher' },
  identityNames: { 'identity-1': 'svc-agent' },
  skillNames: { 'skill-1': 'web-search' },
  sopNames: { 'sop-1': 'research-sop' },
  dataTypeNames: { 'dt-1': 'final-report' },
  modelLabels: { 'gpt-4o': 'gpt-4o (OpenAI Prod)' },
  inputDataTypeName: null,
  toolNames: { 'tool-1': 'mcp____search' },
  toolServerSlugs: { 'tool-1': 'mcp-github' },
  toolServerColors: { 'mcp-github': '#15803d' },
  skillToolIds: { 'skill-1': ['tool-1'] },
  sopComposedSkillIds: {},
}

const LABELS = {
  hub: 'agents.plan.nodeTypes.communication_hub',
  empty: {
    role: 'agents.plan.nodeTypes.empty_role',
    identity: 'agents.plan.nodeTypes.empty_identity',
    skills: 'agents.plan.nodeTypes.empty_skills',
    sops: 'agents.plan.nodeTypes.empty_sops',
    input_data_type: 'agents.plan.nodeTypes.empty_input_data_type',
    output_data_type: 'agents.plan.nodeTypes.empty_output_data_type',
    model: 'agents.plan.nodeTypes.empty_model',
  },
  inputSchemaLabel: 'agents.types.inputSchema',
  outputLocked: 'agents.panel.topologyOutputLocked',
  boundaryTyped: 'agents.plan.boundaryTyped',
  boundaryConversational: 'agents.plan.boundaryConversational',
  sections: {
    contract: 'agents.plan.sectionContract',
    signsInAs: 'agents.plan.signsInAs',
    assumesAs: 'agents.plan.assumesAs',
    sops: 'agents.plan.sectionSops',
    skills: 'agents.plan.sectionSkills',
  },
  edges: {
    equippedWith: 'agents.plan.edgeEquipped',
    grants: 'agents.plan.edgeGrants',
    composed: 'agents.plan.edgeComposed',
  },
  zones: {
    config: { title: 'agents.plan.zoneConfigTitle', subtitle: 'agents.plan.zoneConfigSubtitle' },
    capabilities: {
      title: 'agents.plan.zoneCapabilitiesTitle',
      subtitle: 'agents.plan.zoneCapabilitiesSubtitle',
    },
    tools: { title: 'agents.plan.zoneToolsTitle', subtitle: 'agents.plan.zoneToolsSubtitle' },
  },
  noTools: 'agents.plan.noTools',
}

const FULL_DRAFT: AgentDraftComposition = {
  name: 'research-agent',
  description: 'does research',
  systemInstruction: 'inst',
  guardrails: {
    maxIterations: 10,
    maxDelegationDepth: 3,
    maxDelegatedSteps: 20,
    executionTimeoutSeconds: 300,
    tokenBudget: 100000,
    tokenEnforcementMode: 'observe',
    tokenFallbackMode: 'observe_and_log',
    conversationalTokenVisibilityMode: 'enabled',
    conversationalContinuationPolicy: 'allow',
  },
  identityId: 'identity-1',
  roleId: 'role-1',
  skillBindings: [{ skill_id: 'skill-1', order: 1 }],
  sopBindings: [{ sop_id: 'sop-1', order: 1 }],
  inputType: 'typed',
  inputSchema: { type: 'object', properties: {} },
  outputType: 'typed',
  outputSchema: null,
  outputDataTypeId: 'dt-1',
  modelId: 'gpt-4o',
}

const findNode = (nodes: TopologyNode[], id: string): TopologyNode | undefined =>
  nodes.find((n) => n.id === id)

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('buildPanelTopology', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders every equipped node kind for a full draft — the hub is NOT a node', () => {
    const { nodes, edges } = buildPanelTopology('research-agent', FULL_DRAFT, NAMES, LABELS)

    const ids = nodes.map((n) => n.id)
    expect(ids).toEqual(
      expect.arrayContaining([
        'agent',
        'identity',
        'role',
        'sop_sop-1',
        'skill_skill-1',
        'tool_tool-1',
        'input_data_type',
        'output_data_type',
        'model',
      ]),
    )
    // Labels resolve through the name maps (fallback to the raw id otherwise).
    expect(findNode(nodes, 'role')?.label).toBe('Researcher')
    expect(findNode(nodes, 'model')?.label).toBe('gpt-4o (OpenAI Prod)')
    // The hub is a vertical BAR (declared separately on the renderer), never
    // a node and never an edge endpoint in the zoned panel graph.
    expect(nodes.some((n) => n.id === 'communication_hub')).toBe(false)
    expect(nodes.some((n) => n.type === 'communication_hub')).toBe(false)
    expect(edges.some((e) => e.source === 'communication_hub' || e.target === 'communication_hub')).toBe(false)
    // No "executes via" / "routes to" fan edges anymore.
    expect(edges.some((e) => e.label === 'agents.plan.edgeExecutesVia')).toBe(false)
    expect(edges.some((e) => e.label === 'agents.plan.edgeRoutesTo')).toBe(false)
  })

  it('follows the zoned prototype design — zones, containment and edge semantics', () => {
    const { nodes, edges, zones } = buildPanelTopology('research-agent', FULL_DRAFT, NAMES, LABELS)

    // Three prototype zone bands: ① configuration ② capabilities ③ tools
    // (zone ③ renamed from "Runtime" to "Tools").
    expect(zones.map((z: TopologyZone) => z.id)).toEqual(['config', 'capabilities', 'tools'])
    expect(zones[2].title).toBe('agents.plan.zoneToolsTitle')
    expect(zones[2].dashed).toBe(true)

    // Zone membership: identity/role live in the configuration zone…
    expect(findNode(nodes, 'identity')?.zone).toBe('config')
    expect(findNode(nodes, 'role')?.zone).toBe('config')
    // …INSIDE the agent boundary (containment, not edges).
    expect(findNode(nodes, 'identity')?.containedIn).toBe('agent')
    expect(findNode(nodes, 'role')?.containedIn).toBe('agent')
    // Contract chips (input/output/model) are contained in the boundary too.
    expect(findNode(nodes, 'input_data_type')?.containedIn).toBe('agent')
    expect(findNode(nodes, 'output_data_type')?.containedIn).toBe('agent')
    expect(findNode(nodes, 'model')?.containedIn).toBe('agent')
    // Containment means NO agent→identity/role/input/model edges.
    expect(edges.some((e) => e.target === 'identity')).toBe(false)
    expect(edges.some((e) => e.target === 'role')).toBe(false)
    expect(edges.some((e) => e.target === 'model')).toBe(false)

    // Capabilities zone: SOPs + Skills with section groups.
    expect(findNode(nodes, 'sop_sop-1')?.zone).toBe('capabilities')
    expect(findNode(nodes, 'sop_sop-1')?.group).toBe('sops')
    expect(findNode(nodes, 'skill_skill-1')?.group).toBe('skills')

    // Solid "equipped with" edges from the agent boundary (label on the first edge).
    const equippedSop = edges.find((e) => e.target === 'sop_sop-1' && e.source === 'agent')
    expect(equippedSop?.style).toBe('solid')
    expect(equippedSop?.label).toBe('agents.plan.edgeEquipped')
    const equippedSkill = edges.find((e) => e.target === 'skill_skill-1' && e.source === 'agent')
    expect(equippedSkill?.style).toBe('solid')
    expect(equippedSkill?.label).toBeUndefined()
    // Dotted "grants" edges from the role (label on the first edge).
    const grantsSop = edges.find((e) => e.target === 'sop_sop-1' && e.source === 'role')
    expect(grantsSop?.style).toBe('dotted')
    expect(grantsSop?.label).toBe('agents.plan.edgeGrants')
    const grantsSkill = edges.find((e) => e.target === 'skill_skill-1' && e.source === 'role')
    expect(grantsSkill?.style).toBe('dotted')

    // Tools zone: MCP-server-grouped tool node (no hub node in the zone).
    expect(findNode(nodes, 'tool_tool-1')?.zone).toBe('tools')
    expect(findNode(nodes, 'tool_tool-1')?.group).toBe('mcp-github')
  })

  it('gives capability nodes distinct deterministic border colours matching their tool connectors', () => {
    const { nodes, edges } = buildPanelTopology('research-agent', FULL_DRAFT, NAMES, LABELS)

    // Deterministic + stable across calls.
    expect(capabilityColor('skill_skill-1')).toBe(capabilityColor('skill_skill-1'))
    // Distinct across the equipped capabilities.
    const sopColor = findNode(nodes, 'sop_sop-1')?.accentColor
    const skillColor = findNode(nodes, 'skill_skill-1')?.accentColor
    expect(sopColor).toBeDefined()
    expect(skillColor).toBeDefined()
    expect(sopColor).not.toBe(skillColor)

    // The route connector skill → tool reuses the skill's OWN border colour.
    const connector = edges.find((e) => e.source === 'skill_skill-1' && e.target === 'tool_tool-1')
    expect(connector).toBeDefined()
    expect(connector?.style).toBe('dashed')
    expect(connector?.color).toBe(skillColor)

    // Direct capability → tool routing: NO hub intermediary edges at all.
    expect(edges.some((e) => e.source === 'communication_hub')).toBe(false)
  })

  it('renders the SOP composition chain — composed skill nodes, SOP→skill edges and skill→tool connectors', () => {
    // SOP "research-sop" composes skill-2 ("doc-gen"), which itself calls
    // tool-1 — while skill-1 stays directly bound.
    const names = {
      ...NAMES,
      skillNames: { ...NAMES.skillNames, 'skill-2': 'doc-gen' },
      skillToolIds: { ...NAMES.skillToolIds, 'skill-2': ['tool-1'] },
      sopComposedSkillIds: { 'sop-1': ['skill-2'] },
    }
    const { nodes, edges } = buildPanelTopology('research-agent', FULL_DRAFT, names, LABELS)

    // Composed skill node: a real skill node in the capabilities zone,
    // rendered as an INDENTED TREE CHILD beneath its SOP inside the SOPs
    // section (own group box per SOP), with its own deterministic accent
    // colour.
    const composed = findNode(nodes, 'skill_skill-2')
    expect(composed).toBeDefined()
    expect(composed?.type).toBe('skill')
    expect(composed?.zone).toBe('capabilities')
    expect(composed?.group).toBe('sops')
    expect(composed?.childOf).toBe('sop_sop-1')
    expect(composed?.label).toBe('doc-gen')
    expect(composed?.usage).toBeUndefined()
    expect(composed?.accentColor).toBe(capabilityColor('skill_skill-2'))

    // Composition edge: SOP → composed skill, coloured with the SOP's OWN
    // accent colour (label on the first composition edge only).
    const sopColor = findNode(nodes, 'sop_sop-1')?.accentColor
    const composedEdges = edges.filter((e) => e.source === 'sop_sop-1' && e.target === 'skill_skill-2')
    expect(composedEdges).toHaveLength(1)
    expect(composedEdges[0]?.color).toBe(sopColor)
    expect(composedEdges[0]?.label).toBe('agents.plan.edgeComposed')

    // The composed skill's tool connector renders like any other skill→tool
    // route: dashed, in the composed skill's own accent colour — and the tool
    // node is present in the tools zone.
    const connector = edges.find((e) => e.source === 'skill_skill-2' && e.target === 'tool_tool-1')
    expect(connector).toBeDefined()
    expect(connector?.style).toBe('dashed')
    expect(connector?.color).toBe(capabilityColor('skill_skill-2'))
    expect(findNode(nodes, 'tool_tool-1')?.zone).toBe('tools')

    // Composed-only skills are NOT directly equipped: no agent "equipped
    // with" edge and no role "grants" edge for them (permissions flow via
    // the SOP).
    expect(edges.some((e) => e.source === 'agent' && e.target === 'skill_skill-2')).toBe(false)
    expect(edges.some((e) => e.source === 'role' && e.target === 'skill_skill-2')).toBe(false)
  })

  it('reuses the existing skill node when a SOP composes an already-bound skill (no duplicates)', () => {
    // skill-1 is BOTH directly bound and composed under sop-1 → one node,
    // two incoming semantic edges (agent equipped-with + SOP composition).
    const names = {
      ...NAMES,
      sopComposedSkillIds: { 'sop-1': ['skill-1'] },
    }
    const { nodes, edges } = buildPanelTopology('research-agent', FULL_DRAFT, names, LABELS)

    // Exactly ONE skill-1 node — in the Skills section (its direct binding),
    // NOT marked as a tree child of the SOP (it renders full width there;
    // only the composition edge is added).
    const skillNodes = nodes.filter((n) => n.id === 'skill_skill-1')
    expect(skillNodes).toHaveLength(1)
    expect(skillNodes[0]?.group).toBe('skills')
    expect(skillNodes[0]?.childOf).toBeUndefined()
    expect(skillNodes[0]?.accentColor).toBe(capabilityColor('skill_skill-1'))

    // Both edges reach the SAME node: agent equipped-with + role grants (the
    // direct-binding semantics) AND the SOP composition edge.
    expect(edges.some((e) => e.source === 'agent' && e.target === 'skill_skill-1')).toBe(true)
    expect(edges.some((e) => e.source === 'role' && e.target === 'skill_skill-1')).toBe(true)
    const composition = edges.find((e) => e.source === 'sop_sop-1' && e.target === 'skill_skill-1')
    expect(composition).toBeDefined()
    expect(composition?.color).toBe(findNode(nodes, 'sop_sop-1')?.accentColor)

    // Its tool connector still exists exactly once.
    expect(edges.filter((e) => e.source === 'skill_skill-1' && e.target === 'tool_tool-1')).toHaveLength(1)
  })

  it('omits the composition chain while a SOP has no composed skills (empty details)', () => {
    // NAMES.sopComposedSkillIds is empty → only the plain SOP node renders,
    // with no composition edges and no duplicate placeholders.
    const { nodes, edges } = buildPanelTopology('research-agent', FULL_DRAFT, NAMES, LABELS)
    expect(findNode(nodes, 'sop_sop-1')).toBeDefined()
    expect(edges.some((e) => e.source === 'sop_sop-1')).toBe(false)
    expect(nodes.some((n) => n.group === 'sops' && n.type === 'skill')).toBe(false)
  })

  it('renders dashed placeholders for an empty/new agent draft — no hub node, zones still emitted', () => {
    const { nodes, edges, zones } = buildPanelTopology('new-agent', emptyDraft(), NAMES, LABELS)

    const placeholderNodes = nodes.filter((n) => n.usage === 'empty')
    expect(placeholderNodes.map((n) => n.id).sort()).toEqual([
      'identity',
      'input_data_type',
      'model',
      'output_data_type',
      'role',
      'sop_empty',
      'tool_empty',
    ])
    // No skills equipped → NO Skills section at all: no placeholder node, no
    // group frame — the Capabilities zone collapses to its SOPs empty
    // placeholder (existing zone-empty behaviour).
    expect(nodes.some((n) => n.id === 'skill_empty')).toBe(false)
    expect(nodes.some((n) => n.group === 'skills')).toBe(false)
    expect(edges.some((e) => e.target === 'skill_empty')).toBe(false)
    // The hub bar is declared by the component, never present as a node.
    expect(nodes.some((n) => n.id === 'communication_hub')).toBe(false)
    expect(edges.some((e) => e.target === 'communication_hub')).toBe(false)
    // Zones are emitted even for an empty draft (③ renamed to Tools).
    expect(zones.map((z: TopologyZone) => z.id)).toEqual(['config', 'capabilities', 'tools'])
    // No tools resolve from an empty draft — placeholder tool node, no grants
    // edges, no capability→tool connectors.
    expect(nodes.some((n) => n.id === 'tool_empty' && n.usage === 'empty')).toBe(true)
    expect(edges.some((e) => e.style === 'dotted')).toBe(false)
    expect(edges.some((e) => e.style === 'dashed')).toBe(false)
  })

  it('omits the Skills section for a SOP-only agent — the SOPs section keeps rendering', () => {
    const sopOnly: AgentDraftComposition = { ...FULL_DRAFT, skillBindings: [] }
    const { nodes, edges } = buildPanelTopology('research-agent', sopOnly, NAMES, LABELS)

    // No Skills section: no skills group, no empty placeholder skill node.
    expect(nodes.some((n) => n.group === 'skills')).toBe(false)
    expect(nodes.some((n) => n.groupLabel === 'agents.plan.sectionSkills')).toBe(false)
    expect(nodes.some((n) => n.id === 'skill_empty')).toBe(false)
    // The SOPs section keeps its own behaviour: the bound SOP renders inside
    // its group and receives the (first, labelled) equipped-with edge.
    expect(findNode(nodes, 'sop_sop-1')?.group).toBe('sops')
    const equippedTargets = edges.filter((e) => e.source === 'agent').map((e) => e.target)
    expect(equippedTargets).toEqual(['sop_sop-1'])
    expect(edges.find((e) => e.source === 'agent')?.label).toBe('agents.plan.edgeEquipped')
    // Grants edges still flow to the SOP only.
    expect(edges.filter((e) => e.source === 'role').map((e) => e.target)).toEqual(['sop_sop-1'])
  })

  it('renders composed skills under the SOPs section without a Skills section when nothing is directly bound', () => {
    // No direct bindings; sop-1 composes skill-2 → the composed skill renders
    // beneath its SOP in the SOPs section and the Skills section is omitted.
    const names = {
      ...NAMES,
      skillNames: { ...NAMES.skillNames, 'skill-2': 'doc-gen' },
      skillToolIds: { ...NAMES.skillToolIds, 'skill-2': ['tool-1'] },
      sopComposedSkillIds: { 'sop-1': ['skill-2'] },
    }
    const sopOnly: AgentDraftComposition = { ...FULL_DRAFT, skillBindings: [] }
    const { nodes, edges } = buildPanelTopology('research-agent', sopOnly, names, LABELS)

    const composed = findNode(nodes, 'skill_skill-2')
    expect(composed?.group).toBe('sops')
    expect(composed?.usage).toBeUndefined()
    expect(nodes.some((n) => n.group === 'skills')).toBe(false)
    // Chain intact: agent → SOP (equipped) and SOP → composed skill.
    expect(edges.some((e) => e.source === 'agent' && e.target === 'sop_sop-1')).toBe(true)
    expect(edges.some((e) => e.source === 'sop_sop-1' && e.target === 'skill_skill-2')).toBe(true)
  })

  it('locks the output slot for conversational agents and skips grants edges without a role', () => {
    const conversational: AgentDraftComposition = {
      ...FULL_DRAFT,
      inputType: 'conversation',
      inputSchema: null,
      roleId: null,
      outputDataTypeId: null,
    }
    const { nodes, edges } = buildPanelTopology('chat-agent', conversational, NAMES, LABELS)

    const output = findNode(nodes, 'output_data_type')
    expect(output?.usage).toBe('locked')
    expect(output?.label).toBe('agents.panel.topologyOutputLocked')
    // Conversational boundary caption.
    expect(findNode(nodes, 'agent')?.caption).toBe('agents.plan.boundaryConversational')
    // No role → no dotted grants edges.
    expect(edges.some((e) => e.style === 'dotted')).toBe(false)
  })

  it('keeps capability→tool connectors stable across rebuilds (deterministic colours)', () => {
    const once = buildPanelTopology('research-agent', FULL_DRAFT, NAMES, LABELS)
    const twice = buildPanelTopology('research-agent', FULL_DRAFT, NAMES, LABELS)
    expect(once.edges).toEqual(twice.edges)
    expect(once.nodes.map((n) => [n.id, n.accentColor])).toEqual(twice.nodes.map((n) => [n.id, n.accentColor]))
  })
})

describe('PanelTopologyCanvas', () => {
  function renderCanvas(draft: AgentDraftComposition, isDirty = false) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <PanelTopologyCanvas agentName="research-agent" draft={draft} isDirty={isDirty} />,
      { wrapper: ({ children }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider> },
    )
  }

  it('renders the composed zoned topology through the shared renderer', () => {
    mockApiGet.mockResolvedValue({ data: [] })
    renderCanvas(FULL_DRAFT)

    expect(screen.getByTestId('panel-topology')).toBeDefined()
    // The hub is declared as a vertical BAR between Capabilities and Tools —
    // not passed as a node.
    expect(mockTopologyNodes.some((n) => (n as { id: string }).id === 'communication_hub')).toBe(false)
    expect(mockTopologyNodes.some((n) => (n as { type: string }).type === 'communication_hub')).toBe(false)
    expect(mockTopologyHubBar).toEqual([
      { label: 'agents.plan.nodeTypes.communication_hub', afterZone: 'capabilities' },
    ])
    // The zoned design is passed to the renderer (③ renamed to Tools).
    expect(mockTopologyZones.map((z) => (z as TopologyZone).id)).toEqual([
      'config',
      'capabilities',
      'tools',
    ])
  })

  it('re-renders the topology synchronously when the draft changes — no new API calls', async () => {
    mockApiGet.mockResolvedValue({ data: [] })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { rerender } = render(
      <PanelTopologyCanvas agentName="research-agent" draft={FULL_DRAFT} isDirty={false} />,
      { wrapper: ({ children }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider> },
    )

    const getCallsAfterMount = mockApiGet.mock.calls.length

    // Draft mutation (role assigned) → next render already reflects it.
    const changed: AgentDraftComposition = { ...FULL_DRAFT, roleId: 'role-2' }
    rerender(<PanelTopologyCanvas agentName="research-agent" draft={changed} isDirty />)

    await waitFor(() => {
      expect(mockTopologyNodes.find((n) => (n as { id: string }).id === 'role')).toMatchObject({
        label: 'role-2',
      })
    })
    expect(mockApiGet.mock.calls.length).toBe(getCallsAfterMount)
  })

  it('renders the SOP node immediately and adds its composed skills only once SOP details load', async () => {
    const sopDetail = {
      id: 'sop-1',
      name: 'research-sop',
      description: null,
      instructions: null,
      is_active: true,
      created_at: '2026-06-01T00:00:00Z',
      updated_at: '2026-06-01T00:00:00Z',
      steps: [
        {
          id: 'step-1',
          sop_id: 'sop-1',
          order: 1,
          step_type: 'skill_invocation',
          skill_id: 'skill-1',
          target_agent_type_id: null,
          step_config: null,
          name: null,
          description: null,
          created_at: '2026-06-01T00:00:00Z',
        },
      ],
    }
    // Assigned once the component issues the (pending) detail request.
    let resolveDetail: (value: { data: unknown }) => void = () => {}
    mockApiGet.mockImplementation((url: string) => {
      if (url === '/sops/sop-1') {
        return new Promise((resolve) => {
          resolveDetail = resolve
        })
      }
      return Promise.resolve({ data: [] })
    })

    renderCanvas(FULL_DRAFT)

    // While the SOP detail request is in flight: the SOP node renders
    // immediately, but no composed chain exists yet.
    expect(
      mockTopologyNodes.some((n) => (n as { id: string }).id === 'sop_sop-1'),
    ).toBe(true)
    expect(
      mockTopologyEdges.some(
        (e) => (e as { source: string }).source === 'sop_sop-1' && (e as { target: string }).target === 'skill_skill-1',
      ),
    ).toBe(false)
    expect(mockApiGet.mock.calls.some((call) => call[0] === '/sops/sop-1')).toBe(true)

    // Detail arrives → the chain appears WITHOUT any draft change.
    resolveDetail({ data: sopDetail })
    await waitFor(() => {
      expect(
        mockTopologyEdges.some(
          (e) => (e as { source: string }).source === 'sop_sop-1' && (e as { target: string }).target === 'skill_skill-1',
        ),
      ).toBe(true)
    })
    // The composed chain reuses the already-rendered skill node (no dup).
    expect(
      mockTopologyNodes.filter((n) => (n as { id: string }).id === 'skill_skill-1'),
    ).toHaveLength(1)
  })

  it('keeps the topology free of SOP composition for drafts without bound SOPs', async () => {
    mockApiGet.mockClear()
    mockApiGet.mockResolvedValue({ data: [] })
    renderCanvas({ ...FULL_DRAFT, sopBindings: [] })

    await waitFor(() => {
      expect(mockTopologyNodes.some((n) => (n as { id: string }).id === 'sop_empty')).toBe(true)
    })
    // No SOP detail requests at all — the query is disabled without bound SOPs.
    expect(mockApiGet.mock.calls.some((call) => String(call[0]).startsWith('/sops/sop'))).toBe(false)
    expect(mockTopologyEdges.some((e) => (e as { source: string }).source?.startsWith('sop_'))).toBe(false)
  })

  it('hides the Skills section from the composed graph when the draft equips no skills', async () => {
    mockApiGet.mockClear()
    mockApiGet.mockResolvedValue({ data: [] })
    renderCanvas({ ...FULL_DRAFT, skillBindings: [] })

    await waitFor(() => {
      expect(mockTopologyNodes.some((n) => (n as { id: string }).id === 'sop_sop-1')).toBe(true)
    })
    // No Skills section reaches the renderer: no group frame, no placeholder
    // node, no orphan edges — while the SOPs section renders untouched.
    expect(mockTopologyNodes.some((n) => (n as { group?: string }).group === 'skills')).toBe(false)
    expect(mockTopologyNodes.some((n) => (n as { id: string }).id === 'skill_empty')).toBe(false)
    expect(mockTopologyEdges.some((e) => (e as { target: string }).target === 'skill_empty')).toBe(false)
    expect(mockTopologyNodes.some((n) => (n as { group?: string }).group === 'sops')).toBe(true)
  })

  it('toggles fullscreen from the header button and exits via Escape', () => {
    mockApiGet.mockResolvedValue({ data: [] })
    renderCanvas(FULL_DRAFT)

    // Inline canvas initially; no overlay.
    expect(screen.queryByTestId('panel-topology-fullscreen-overlay')).toBeNull()
    const toggle = screen.getByTestId('panel-topology-fullscreen')
    expect(toggle.getAttribute('aria-label')).toBe('agents.panel.topologyFullscreen')

    // Expand → the fixed overlay takes over with the height-filling canvas.
    fireEvent.click(toggle)
    expect(screen.getByTestId('panel-topology-fullscreen-overlay')).toBeDefined()
    expect(screen.queryByTestId('panel-topology-fullscreen')).toBeNull()
    const exit = screen.getByTestId('panel-topology-fullscreen-exit')
    expect(exit.getAttribute('aria-label')).toBe('agents.panel.topologyFullscreenExit')

    // Escape returns to the inline canvas.
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByTestId('panel-topology-fullscreen-overlay')).toBeNull()
    expect(screen.getByTestId('panel-topology-fullscreen')).toBeDefined()
  })

  it('exits fullscreen via the exit icon button', () => {
    mockApiGet.mockResolvedValue({ data: [] })
    renderCanvas(FULL_DRAFT)

    fireEvent.click(screen.getByTestId('panel-topology-fullscreen'))
    expect(screen.getByTestId('panel-topology-fullscreen-overlay')).toBeDefined()

    fireEvent.click(screen.getByTestId('panel-topology-fullscreen-exit'))
    expect(screen.queryByTestId('panel-topology-fullscreen-overlay')).toBeNull()
  })

  it('hides the zoom controls from the inline (non-fullscreen) canvas', () => {
    mockApiGet.mockResolvedValue({ data: [] })
    renderCanvas(FULL_DRAFT)

    expect(screen.queryByTestId('panel-topology-zoom-in')).toBeNull()
    expect(screen.queryByTestId('panel-topology-zoom-out')).toBeNull()
    expect(screen.queryByTestId('panel-topology-zoom-fit')).toBeNull()
    expect(screen.queryByTestId('panel-topology-zoom-level')).toBeNull()
    // Inline canvas renders WITHOUT the fullscreen view transform.
    expect(mockViewProps.fillHeight).toBe(false)
    expect(mockViewProps.viewZoom).toBeUndefined()
  })

  it('shows zoom controls in fullscreen and steps the zoom % per click', () => {
    mockApiGet.mockResolvedValue({ data: [] })
    renderCanvas(FULL_DRAFT)

    fireEvent.click(screen.getByTestId('panel-topology-fullscreen'))

    // Starts auto-fitted: 100%, fullscreen canvas receives fillHeight + zoom 1.
    const level = screen.getByTestId('panel-topology-zoom-level')
    expect(level.textContent).toBe('100%')
    expect(mockViewProps.fillHeight).toBe(true)
    expect(mockViewProps.viewZoom).toBe(1)

    // Zoom in steps ~20% per click, clamped to the 0.5×–3× range.
    fireEvent.click(screen.getByTestId('panel-topology-zoom-in'))
    expect(screen.getByTestId('panel-topology-zoom-level').textContent).toBe('120%')
    expect(mockViewProps.viewZoom).toBeGreaterThan(1)
    fireEvent.click(screen.getByTestId('panel-topology-zoom-in'))
    expect(screen.getByTestId('panel-topology-zoom-level').textContent).toBe('144%')

    // Zoom out steps back down.
    fireEvent.click(screen.getByTestId('panel-topology-zoom-out'))
    expect(screen.getByTestId('panel-topology-zoom-level').textContent).toBe('120%')
    fireEvent.click(screen.getByTestId('panel-topology-zoom-out'))
    expect(screen.getByTestId('panel-topology-zoom-level').textContent).toBe('100%')
    fireEvent.click(screen.getByTestId('panel-topology-zoom-out'))
    expect(screen.getByTestId('panel-topology-zoom-level').textContent).toBe('83%')
    fireEvent.click(screen.getByTestId('panel-topology-zoom-out'))
    expect(screen.getByTestId('panel-topology-zoom-level').textContent).toBe('69%')
    fireEvent.click(screen.getByTestId('panel-topology-zoom-out'))
    expect(screen.getByTestId('panel-topology-zoom-level').textContent).toBe('58%')
    fireEvent.click(screen.getByTestId('panel-topology-zoom-out'))
    expect(screen.getByTestId('panel-topology-zoom-level').textContent).toBe('50%')
    // Clamped at the 50% floor — further clicks keep 50%.
    fireEvent.click(screen.getByTestId('panel-topology-zoom-out'))
    expect(screen.getByTestId('panel-topology-zoom-level').textContent).toBe('50%')
    expect(screen.getByTestId('panel-topology-zoom-out').hasAttribute('disabled')).toBe(true)

    // Zoom in up to the 300% ceiling.
    for (let i = 0; i < 20; i++) fireEvent.click(screen.getByTestId('panel-topology-zoom-in'))
    expect(screen.getByTestId('panel-topology-zoom-level').textContent).toBe('300%')
    expect(screen.getByTestId('panel-topology-zoom-in').hasAttribute('disabled')).toBe(true)
  })

  it('Fit resets the zoom to 100% (auto-fit)', () => {
    mockApiGet.mockResolvedValue({ data: [] })
    renderCanvas(FULL_DRAFT)

    fireEvent.click(screen.getByTestId('panel-topology-fullscreen'))
    fireEvent.click(screen.getByTestId('panel-topology-zoom-in'))
    fireEvent.click(screen.getByTestId('panel-topology-zoom-in'))
    expect(screen.getByTestId('panel-topology-zoom-level').textContent).toBe('144%')

    fireEvent.click(screen.getByTestId('panel-topology-zoom-fit'))
    expect(screen.getByTestId('panel-topology-zoom-level').textContent).toBe('100%')
    expect(mockViewProps.viewZoom).toBe(1)
  })

  it('resets the zoom when exiting and re-entering fullscreen (exit icon and Escape)', () => {
    mockApiGet.mockResolvedValue({ data: [] })
    renderCanvas(FULL_DRAFT)

    fireEvent.click(screen.getByTestId('panel-topology-fullscreen'))
    fireEvent.click(screen.getByTestId('panel-topology-zoom-in'))
    fireEvent.click(screen.getByTestId('panel-topology-zoom-in'))
    expect(screen.getByTestId('panel-topology-zoom-level').textContent).toBe('144%')

    // Exit via Escape → zoom resets for the next fullscreen session.
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByTestId('panel-topology-fullscreen-overlay')).toBeNull()
    fireEvent.click(screen.getByTestId('panel-topology-fullscreen'))
    expect(screen.getByTestId('panel-topology-zoom-level').textContent).toBe('100%')

    // Zoom in again, exit via the icon → still resets.
    fireEvent.click(screen.getByTestId('panel-topology-zoom-in'))
    expect(screen.getByTestId('panel-topology-zoom-level').textContent).toBe('120%')
    fireEvent.click(screen.getByTestId('panel-topology-fullscreen-exit'))
    fireEvent.click(screen.getByTestId('panel-topology-fullscreen'))
    expect(screen.getByTestId('panel-topology-zoom-level').textContent).toBe('100%')
    expect(mockViewProps.viewZoom).toBe(1)
  })

  it('shows the live/unsaved indicator chips localized', () => {
    mockApiGet.mockResolvedValue({ data: [] })
    renderCanvas(FULL_DRAFT, true)

    expect(screen.getByText('agents.panel.topology')).toBeDefined()
    expect(screen.getByText('agents.panel.topologyLive')).toBeDefined()
    expect(screen.getByText('agents.panel.topologyHint')).toBeDefined()
  })
})
