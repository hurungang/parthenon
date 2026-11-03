/**
 * FIX-20261102-015138 — SkillEditor (viewer AND editor modes) displays the
 * FULL list of bound tools (tool name + owning server) from the
 * `tool_bindings` payload delivered by the API (added in FIX-223511).
 */
import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SkillEditor } from '../components/agents/SkillEditor'
import type { Skill } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, unknown>) => {
      const map: Record<string, string> = {
        'skills.editor.boundTools': 'Bound tools',
        'skills.noToolsBound': 'No tools bound',
      }
      const raw = map[k] ?? k
      return raw.replace(/\{\{(\w+)\}\}/g, (_, name) => String(opts?.[name] ?? ''))
    },
  }),
}))

const EMPTY_ARRAY: unknown[] = []

vi.mock('../hooks/useMcpServers', () => ({
  useAllTools: () => ({ data: EMPTY_ARRAY, isLoading: false }),
  useMcpServers: () => ({ data: EMPTY_ARRAY, isLoading: false }),
}))

vi.mock('../hooks/useSkills', () => ({
  useSkillRoles: () => ({ data: EMPTY_ARRAY, isLoading: false }),
}))

vi.mock('../api/apiClient', () => ({
  default: { get: vi.fn() },
}))

import apiClient from '../api/apiClient'
const getMock = apiClient.get as unknown as Mock

const skill: Skill = {
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
      name: 'github____create_issue',
      original_name: 'create_issue',
      server_slug: 'github',
      server_name: 'GitHub',
    },
  ],
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
}

function renderEditor(mode: 'view' | 'edit') {
  getMock.mockImplementation(async (url: string) => {
    if (url === '/skills/s1') return { data: skill }
    return { data: [] }
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <SkillEditor open skill={skill} mode={mode} onClose={vi.fn()} onSaved={vi.fn()} />
    </QueryClientProvider>,
  )
}

describe('SkillEditor bound tools display (FIX-20261102-015138)', () => {
  beforeEach(() => {
    getMock.mockReset()
  })

  it('view mode shows the full bound-tools list (names + owning servers)', async () => {
    renderEditor('view')
    expect(await screen.findByText('Bound tools')).toBeDefined()
    expect(screen.getByText('run_sql')).toBeDefined()
    expect(screen.getByText('create_issue')).toBeDefined()
    expect(screen.getByText(/Supabase/)).toBeDefined()
    expect(screen.getByText(/GitHub/)).toBeDefined()
    // canonical names visible too
    expect(screen.getByText('supabase____run_sql')).toBeDefined()
    expect(screen.getByText('github____create_issue')).toBeDefined()
  })

  it('edit mode shows the same full list, read-only', async () => {
    renderEditor('edit')
    expect(await screen.findByText('Bound tools')).toBeDefined()
    expect(screen.getByText('run_sql')).toBeDefined()
    expect(screen.getByText(/GitHub/)).toBeDefined()
  })

  it('shows the muted "No tools bound" indicator when the skill has no bindings', async () => {
    const bare: Skill = { ...skill, tool_ids: [], tool_bindings: [] }
    getMock.mockImplementation(async (url: string) => {
      if (url === '/skills/s1') return { data: bare }
      return { data: [] }
    })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <SkillEditor open skill={bare} mode="view" onClose={vi.fn()} onSaved={vi.fn()} />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('Bound tools')).toBeDefined()
    expect(screen.getByText('No tools bound')).toBeDefined()
  })
})
