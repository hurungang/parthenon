import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'
import type { TopologyEdge, TopologyNode } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// ── Test fixtures ──────────────────────────────────────────────────────────────

const ROLE_NODE: TopologyNode = { id: 'role:r1', type: 'role', label: 'My Role', meta: { description: 'Role desc' } }
const SOP_NODE: TopologyNode = { id: 'sop:s1', type: 'sop', label: 'My SOP', meta: null }
const SKILL_NODE: TopologyNode = { id: 'skill:sk1', type: 'skill', label: 'My Skill', meta: undefined }
const TOOL_NODE: TopologyNode = { id: 'tool:my_tool', type: 'tool', label: 'my_tool', meta: { description: 'Tool desc' } }

const ALL_NODES: TopologyNode[] = [ROLE_NODE, SOP_NODE, SKILL_NODE, TOOL_NODE]
const ALL_EDGES: TopologyEdge[] = [
  { source: 'role:r1', target: 'sop:s1', label: 'uses SOP' },
  { source: 'sop:s1', target: 'skill:sk1', label: 'invokes' },
  { source: 'skill:sk1', target: 'tool:my_tool', label: 'calls' },
]

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('TopologyDiagramRenderer', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders without throwing with a valid non-empty payload', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    expect(() =>
      render(<TopologyDiagramRenderer nodes={ALL_NODES} edges={ALL_EDGES} />),
    ).not.toThrow()
  })

  it('renders an SVG element when nodes are present', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    const { container } = render(
      <TopologyDiagramRenderer nodes={ALL_NODES} edges={ALL_EDGES} />,
    )
    const svg = container.querySelector('svg')
    expect(svg).not.toBeNull()
  })

  it('renders node labels for all four node types', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    render(<TopologyDiagramRenderer nodes={ALL_NODES} edges={ALL_EDGES} />)

    // Node labels should appear in the SVG text elements
    expect(screen.getByText('My Role')).toBeDefined()
    expect(screen.getByText('My SOP')).toBeDefined()
    expect(screen.getByText('My Skill')).toBeDefined()
    expect(screen.getByText('my_tool')).toBeDefined()
  })

  it('renders node type labels (type badges)', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    const { container } = render(
      <TopologyDiagramRenderer nodes={ALL_NODES} edges={ALL_EDGES} />,
    )
    // Type badges are lowercase SVG text elements
    const textEls = container.querySelectorAll('text')
    const typeTexts = Array.from(textEls).map((el) => el.textContent?.toLowerCase() ?? '')
    expect(typeTexts.some((t) => t.includes('role'))).toBe(true)
    expect(typeTexts.some((t) => t.includes('sop'))).toBe(true)
    expect(typeTexts.some((t) => t.includes('skill'))).toBe(true)
    expect(typeTexts.some((t) => t.includes('tool'))).toBe(true)
  })

  it('renders empty state when nodes array is empty', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    render(<TopologyDiagramRenderer nodes={[]} edges={[]} />)

    // Should not render an SVG, should show empty state text
    const svg = document.querySelector('svg')
    expect(svg).toBeNull()

    // The empty state message uses t() key agents.plan.topology
    expect(screen.getByText(/agents\.plan\.topology/i)).toBeDefined()
  })

  it('does not throw when nodes contain unexpected extra fields', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    const nodesWithExtras = [
      { id: 'role:r1', type: 'role', label: 'Role', meta: null, extra_unknown_field: 'ignored' },
    ] as TopologyNode[]

    expect(() =>
      render(<TopologyDiagramRenderer nodes={nodesWithExtras} edges={[]} />),
    ).not.toThrow()
  })

  it('does not throw when edges contain unexpected extra fields', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    const edgesWithExtras = [
      { source: 'role:r1', target: 'sop:s1', label: 'uses SOP', extra: 'ignored' },
    ] as TopologyEdge[]

    expect(() =>
      render(
        <TopologyDiagramRenderer
          nodes={[ROLE_NODE, SOP_NODE]}
          edges={edgesWithExtras}
        />,
      ),
    ).not.toThrow()
  })

  it('renders edge lines in the SVG when edges are provided', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    const { container } = render(
      <TopologyDiagramRenderer nodes={[ROLE_NODE, SKILL_NODE]} edges={[ALL_EDGES[0]]} />,
    )
    const paths = container.querySelectorAll('path')
    // At least one path element should be rendered for the edge
    expect(paths.length).toBeGreaterThan(0)
  })

  it('renders role-only graph without throwing', async () => {
    const { default: TopologyDiagramRenderer } = await import(
      '../components/agents/TopologyDiagramRenderer'
    )
    expect(() =>
      render(<TopologyDiagramRenderer nodes={[ROLE_NODE]} edges={[]} />),
    ).not.toThrow()

    expect(screen.getByText('My Role')).toBeDefined()
  })
})
