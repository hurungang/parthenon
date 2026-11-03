/**
 * FIX-20261101-223511 / FIX-20261102-015138 — SkillListPage tool bindings:
 * the table shows a COUNT ("N tools") rather than per-tool chips (full list
 * lives in the viewer/editor), plus an explicit muted "No tools bound"
 * indicator for skills WITHOUT bindings.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { SkillListPage } from '../pages/skills/SkillListPage'
import type { Skill } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, unknown>) => {
      const map: Record<string, string> = {
        'skills.title': 'Skills',
        'skills.createSkill': 'Create Skill',
        'skills.showSystem': 'Show system',
        'skills.systemChip': 'System',
        'skills.toolCount': 'Tools',
        'skills.noToolsBound': 'No tools bound',
        'skills.toolCountValue': '{{count}} tools',
        'app.name': 'Name',
        'app.status': 'Status',
        'app.actions': 'Actions',
        'app.active': 'Active',
        'app.inactive': 'Inactive',
        'app.search': 'Search',
        'app.noData': 'No data',
      }
      void opts
      const raw = map[k] ?? k
      return raw.replace('{{count}}', String(opts?.count ?? ''))
    },
  }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn(),
  },
}))

import apiClient from '../api/apiClient'
import type { Mock } from 'vitest'
const getMock = apiClient.get as unknown as Mock

vi.mock('../components/agents/SkillEditor', () => ({
  SkillEditor: () => <div data-testid="skill-editor" />,
}))

vi.mock('../hooks/usePagination', () => ({
  usePagination: () => ({
    page: 0,
    limit: 25,
    offset: 0,
    rowsPerPage: 25,
    onPageChange: vi.fn(),
    onRowsPerPageChange: vi.fn(),
    rowsPerPageOptions: [10, 25, 50],
  }),
}))

const skillWithBindings: Skill = {
  id: 's1',
  name: 'sql-runner',
  description: 'Runs SQL',
  is_active: true,
  is_system: false,
  tool_ids: ['t1', 't2'],
  tool_bindings: [
    {
      name: 'supabase____run_sql',
      original_name: 'run_sql',
      server_slug: 'supabase',
      server_name: 'Supabase',
    },
    {
      name: 'supabase____list_tables',
      original_name: 'list_tables',
      server_slug: 'supabase',
      server_name: 'Supabase',
    },
  ],
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
}

const skillWithoutBindings: Skill = {
  id: 's2',
  name: 'bare-skill',
  description: null,
  is_active: true,
  is_system: false,
  tool_ids: [],
  tool_bindings: [],
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
}

function renderPage(skills: Skill[]) {
  getMock.mockResolvedValue({ data: skills })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <SkillListPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('SkillListPage tool binding visibility (FIX-20261101-223511)', () => {
  beforeEach(() => {
    getMock.mockReset()
  })

  it('shows a tool COUNT ("2 tools") instead of per-tool chips for a skill with bindings', async () => {
    renderPage([skillWithBindings])
    await screen.findByText('sql-runner')
    expect(screen.getByText('2 tools')).toBeDefined()
    expect(screen.queryByText('run_sql')).toBeNull()
    expect(screen.queryByText('list_tables')).toBeNull()
  })

  it('the count carries a tooltip listing the bound tool names', async () => {
    renderPage([skillWithBindings])
    await screen.findByText('sql-runner')
    const node = screen.getByText('2 tools').closest('[title]') as HTMLElement | null
    expect(node?.getAttribute('title')).toContain('run_sql')
    expect(node?.getAttribute('title')).toContain('list_tables')
  })

  it('shows an explicit muted "No tools bound" indicator for a zero-binding skill', async () => {
    renderPage([skillWithBindings, skillWithoutBindings])
    await screen.findByText('bare-skill')
    expect(screen.getByText('No tools bound')).toBeDefined()
  })
})
