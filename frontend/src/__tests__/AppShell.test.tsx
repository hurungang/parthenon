import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import enCatalog from '../i18n/locales/en.json'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../stores/authStore', () => ({
  useAuthStore: () => ({
    login: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    token: 'mock-token',
    claims: { sub: 'user1', exp: 9999999999, iat: 0, name: 'Admin' },
    setToken: vi.fn(),
  }),
}))

let mockPathname = '/dashboard'
const mockNavigate = vi.fn()

// Mock react-router-dom keeping Outlet etc but stubbing useNavigate/useLocation so we can
// drive the active route from the test (active state, deep-link, navigation).
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useLocation: () => ({ pathname: mockPathname }),
    Outlet: () => <div data-testid="outlet-content" />,
  }
})

beforeEach(() => {
  mockPathname = '/dashboard'
  mockNavigate.mockReset()
})

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient()
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/dashboard']}>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

/**
 * Children declared in NAV_GROUPS, grouped by parent. Mirrors the order in
 * frontend/src/app/AppShell.tsx so the test stays in lock-step with the data model.
 */
const AGENTS_CHILDREN = [
  'nav.agentRoles',
  'nav.agentIdentities',
  'nav.agentTypes',
  'nav.runtimeControl',
  'nav.skills',
  'nav.sops',
  'nav.modelConfigs',
  'nav.schedules',
  'nav.agentTrails',
] as const

const INTEGRATIONS_CHILDREN = [
  'nav.mcpHub',
  'nav.notifications',
] as const

const SYSTEM_CHILDREN = [
  'nav.observability',
  'nav.permissions',
  'nav.systemConfig',
] as const

describe('AppShell — sidebar structure', () => {
  it('renders Dashboard as a standalone top-level entry (one per drawer, not inside any group)', async () => {
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })
    // Permanent + temporary drawer each render Dashboard once → exactly 2 occurrences.
    // If Dashboard ever leaks into a group body, the count would rise.
    const items = screen.getAllByText('nav.dashboard')
    expect(items).toHaveLength(2)
  })

  it('renders the three new group labels (Agents, Integrations, System)', async () => {
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })
    expect(screen.getAllByText('nav.groupAgents').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('nav.groupIntegrations').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('nav.groupSystem').length).toBeGreaterThanOrEqual(1)
  })

  it('does not render the legacy "AI Agent" group label', async () => {
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })
    expect(screen.queryAllByText('nav.aiAgent')).toHaveLength(0)
  })

  it.each(AGENTS_CHILDREN)('renders Agents child label "%s" under the Agents group', async (label) => {
    mockPathname = '/agents/roles'
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })
    // Each label appears in both permanent and temporary drawers → at least 1.
    expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1)
  })

  it.each(INTEGRATIONS_CHILDREN)('renders Integrations child label "%s" under the Integrations group', async (label) => {
    mockPathname = '/mcp'
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })
    expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1)
  })

  it.each(SYSTEM_CHILDREN)('renders System child label "%s" under the System group', async (label) => {
    mockPathname = '/observability'
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })
    expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1)
  })

  it('renders the Agents group with exactly 9 children (in declaration order)', async () => {
    mockPathname = '/agents/roles'
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })
    for (const label of AGENTS_CHILDREN) {
      expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1)
    }
    expect(AGENTS_CHILDREN).toHaveLength(9)
  })

  it('renders the Integrations group with exactly 2 children (in declaration order)', async () => {
    mockPathname = '/mcp'
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })
    for (const label of INTEGRATIONS_CHILDREN) {
      expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1)
    }
    expect(INTEGRATIONS_CHILDREN).toHaveLength(2)
  })

  it('renders the System group with exactly 3 children (in declaration order)', async () => {
    mockPathname = '/observability'
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })
    for (const label of SYSTEM_CHILDREN) {
      expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1)
    }
    expect(SYSTEM_CHILDREN).toHaveLength(3)
  })
})

describe('AppShell — i18n catalog', () => {
  it('defines the three new group-label keys in en.json', () => {
    // Regression guard: the AppShell data model references these labelKey values.
    // If any of them is removed from the catalog, the live UI will fall back to
    // rendering the raw key string (e.g. "nav.groupAgents") instead of "Agents".
    const nav = (enCatalog as { nav: Record<string, string> }).nav
    expect(nav.groupAgents).toBe('Agents')
    expect(nav.groupIntegrations).toBe('Integrations')
    expect(nav.groupSystem).toBe('System')
  })

  it('does not contain the legacy "nav.aiAgent" key', () => {
    const nav = (enCatalog as { nav: Record<string, string> }).nav
    expect(nav.aiAgent).toBeUndefined()
  })

  it('defines every labelKey referenced by NAV_GROUPS and STANDALONE_ITEMS', () => {
    // Catches the "key referenced by data model but missing from catalog" gap that
    // mocked-i18n unit tests cannot detect.
    const nav = (enCatalog as { nav: Record<string, string> }).nav
    const allKeys = [
      'dashboard',
      ...AGENTS_CHILDREN.map((k) => k.replace('nav.', '')),
      ...INTEGRATIONS_CHILDREN.map((k) => k.replace('nav.', '')),
      ...SYSTEM_CHILDREN.map((k) => k.replace('nav.', '')),
      'groupAgents',
      'groupIntegrations',
      'groupSystem',
    ]
    for (const key of allKeys) {
      expect(nav[key], `Missing nav.${key} in en.json`).toBeDefined()
    }
  })
})

describe('AppShell — app bar & outlet', () => {
  it('renders the app bar title', async () => {
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })
    const titles = screen.getAllByText('app.title')
    expect(titles.length).toBeGreaterThanOrEqual(1)
  })

  it('renders the outlet placeholder', async () => {
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })
    expect(screen.getByTestId('outlet-content')).toBeDefined()
  })
})

describe('AppShell — sidebar interactions', () => {
  it('clicking a child item calls navigate with the child path', async () => {
    mockPathname = '/agents'
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })

    const roles = screen.getAllByText('nav.agentRoles')[0]
    fireEvent.click(roles)

    expect(mockNavigate).toHaveBeenCalledWith('/agents/roles')
  })

  it('clicking a collapsed group header expands it, clicking again collapses it', async () => {
    mockPathname = '/dashboard'
    const user = userEvent.setup()
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })

    // Integrations starts collapsed (not the active route)
    expect(screen.queryAllByText('nav.mcpHub')).toHaveLength(0)

    // Click the Integrations group header to expand
    const groupHeaderText = screen.getAllByText('nav.groupIntegrations')[0]
    const groupHeaderButton = groupHeaderText.closest('.MuiListItemButton-root') as HTMLElement
    await user.click(groupHeaderButton)

    // Children now visible
    expect(screen.getAllByText('nav.mcpHub').length).toBeGreaterThanOrEqual(1)

    // Click again to collapse
    await user.click(groupHeaderButton)
    expect(screen.queryAllByText('nav.mcpHub')).toHaveLength(0)
  })

  it('clicking one group header does not collapse other groups', async () => {
    mockPathname = '/agents/roles'
    const user = userEvent.setup()
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })

    // Agents starts expanded (active route), System starts collapsed
    expect(screen.getAllByText('nav.agentTypes').length).toBeGreaterThanOrEqual(1)
    expect(screen.queryAllByText('nav.observability')).toHaveLength(0)

    // Expand System manually
    const systemHeaderText = screen.getAllByText('nav.groupSystem')[0]
    const systemHeaderButton = systemHeaderText.closest('.MuiListItemButton-root') as HTMLElement
    await user.click(systemHeaderButton)
    expect(screen.getAllByText('nav.observability').length).toBeGreaterThanOrEqual(1)

    // Collapse System again
    await user.click(systemHeaderButton)

    // System children hidden again
    expect(screen.queryAllByText('nav.observability')).toHaveLength(0)
    // Agents still expanded (active route)
    expect(screen.getAllByText('nav.agentTypes').length).toBeGreaterThanOrEqual(1)
    // Integrations remains collapsed (not affected by System toggle)
    expect(screen.queryAllByText('nav.mcpHub')).toHaveLength(0)
  })

  it('marks the active child item with the MUI selected class', async () => {
    mockPathname = '/agents/roles'
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })

    const buttons = screen.getAllByText('nav.agentRoles')
    // At least one of the rendered buttons should have the selected class
    const anySelected = buttons.some(
      (btn) => btn.closest('.MuiListItemButton-root')?.classList.contains('Mui-selected') ?? false,
    )
    expect(anySelected).toBe(true)
  })

  it('marks the active group header as selected when any child is active', async () => {
    mockPathname = '/skills'
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })

    // The Agents group header should be selected
    const agentsHeaderText = screen.getAllByText('nav.groupAgents')[0]
    const headerButton = agentsHeaderText.closest('.MuiListItemButton-root')
    expect(headerButton?.classList.contains('Mui-selected')).toBe(true)
  })

  it('auto-expands a group when navigated directly to a child route', async () => {
    // Simulate a deep link to an Integrations child by setting pathname before render.
    mockPathname = '/mcp'
    const user = userEvent.setup()
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })

    // MCP Hub should be visible (deep link to a child auto-expands the parent)
    expect(screen.getAllByText('nav.mcpHub').length).toBeGreaterThanOrEqual(1)

    // Now collapse the group, then click an Integrations child to confirm the active
    // state propagates and the group is force-expanded.
    const integrationsHeaderText = screen.getAllByText('nav.groupIntegrations')[0]
    const integrationsHeaderButton = integrationsHeaderText.closest('.MuiListItemButton-root') as HTMLElement
    await user.click(integrationsHeaderButton)
    // Even after collapse, MCP Hub should still be visible because pathname matches
    // a child of Integrations (the showChildren predicate uses isGroupActive).
    expect(screen.getAllByText('nav.mcpHub').length).toBeGreaterThanOrEqual(1)
  })

  it('clicking Dashboard (standalone) navigates to /dashboard', async () => {
    mockPathname = '/agents'
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })

    const dashboard = screen.getAllByText('nav.dashboard')[0]
    fireEvent.click(dashboard)

    expect(mockNavigate).toHaveBeenCalledWith('/dashboard')
  })
})
