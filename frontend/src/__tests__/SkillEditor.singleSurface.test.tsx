/**
 * FIX-20261102-062047 — ONE tool-selection surface in the skill editor.
 *
 * The picker and the "Bound Tools" display used to be two separate surfaces;
 * existing bindings were not pre-selected when they were missing from the
 * (truncated) tool list.  The editor now:
 *
 * - initialises the picker selection from the skill's ``tool_bindings``;
 * - renders ONE grouped list (name + owning server) that IS the display and
 *   the editor (deselect -> remove; toggling in the picker updates it);
 * - in view mode renders that same list read-only;
 * - keeps already-referenced Control Center tools visible READ-ONLY when the
 *   caller lacks ``integration::control_center:read`` (they are not part of
 *   general browsing), with an explanatory note, and never drops them from the
 *   saved payload.
 */
import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SkillEditor } from '../components/agents/SkillEditor'
import type { McpTool, Skill } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, unknown>) => {
      const map: Record<string, string> = {
        'skills.editor.boundTools': 'Bound tools',
        'skills.noToolsBound': 'No tools bound',
        'skills.editor.selectTools': 'Select Tools',
        'skills.editor.selectToolsDialogTitle': 'Select Tools',
        'skills.editor.confirmSelection': 'Confirm Selection',
        'skills.editor.filterByServer': 'Filter by MCP Server',
        'skills.editor.noToolsAvailable': 'No tools available',
        'skills.editor.referencedTools': 'Referenced (read-only)',
        'skills.editor.referencedToolReadOnlyNote':
          'Access to this tool requires the Control Center integration permission — shown read-only because this skill uses it.',
        'skills.editor.removeTool': 'Remove {{name}}',
        'skills.viewSkill': 'View Skill',
        'skills.editSkill': 'Edit Skill',
        'skills.createSkill': 'Create Skill',
        'app.save': 'Save',
        'app.cancel': 'Cancel',
        'app.close': 'Close',
        'app.loading': 'Loading',
        'app.name': 'Name',
        'app.description': 'Description',
        'app.noData': 'No data',
      }
      const raw = map[k] ?? k
      return raw.replace(/\{\{(\w+)\}\}/g, (_, name) => String(opts?.[name] ?? ''))
    },
  }),
}))

const EMPTY_ARRAY: unknown[] = []

vi.mock('../hooks/useMcpServers', () => ({
  useAllTools: vi.fn(),
  useMcpServers: vi.fn(),
}))

vi.mock('../hooks/useSkills', () => ({
  useSkillRoles: () => ({ data: EMPTY_ARRAY, isLoading: false }),
}))

vi.mock('../api/apiClient', () => ({
  default: { get: vi.fn(), put: vi.fn(), post: vi.fn() },
}))

import apiClient from '../api/apiClient'
import { useAllTools, useMcpServers } from '../hooks/useMcpServers'

const getMock = apiClient.get as unknown as Mock
const putMock = apiClient.put as unknown as Mock

const RUN_SQL: McpTool = {
  id: 't-run',
  server_id: 'srv-supabase',
  server_slug: 'supabase',
  server_name: 'Supabase',
  name: 'supabase____run_sql',
  original_name: 'run_sql',
  description: 'Runs SQL',
  input_schema: {},
  is_active: true,
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
}

const CREATE_ISSUE: McpTool = {
  id: 't-issue',
  server_id: 'srv-github',
  server_slug: 'github',
  server_name: 'GitHub',
  name: 'github____create_issue',
  original_name: 'create_issue',
  description: 'Creates an issue',
  input_schema: {},
  is_active: true,
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
}

// Referenced cc tool the caller cannot browse (no cc permission): it is
// intentionally ABSENT from the catalogue.
const CC_TOOL_ID = 't-cc'

const skill: Skill = {
  id: 's1',
  name: 'sql-runner',
  description: 'Runs SQL',
  instructions: '',
  is_active: true,
  is_system: false,
  tool_ids: ['t-run', CC_TOOL_ID],
  tool_bindings: [
    {
      tool_id: 't-run',
      name: 'supabase____run_sql',
      original_name: 'run_sql',
      server_slug: 'supabase',
      server_name: 'Supabase',
    },
    {
      tool_id: CC_TOOL_ID,
      name: 'cc____create_skill',
      original_name: 'create_skill',
      server_slug: 'cc',
      server_name: 'Control Center',
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

beforeEach(() => {
  vi.mocked(useAllTools).mockReturnValue({
    data: [RUN_SQL, CREATE_ISSUE],
    isLoading: false,
  } as unknown as ReturnType<typeof useAllTools>)
  vi.mocked(useMcpServers).mockReturnValue({
    data: [
      { id: 'srv-supabase', name: 'Supabase', slug: 'supabase' },
      { id: 'srv-github', name: 'GitHub', slug: 'github' },
    ],
    isLoading: false,
  } as unknown as ReturnType<typeof useMcpServers>)
  getMock.mockReset()
  putMock.mockReset()
  putMock.mockResolvedValue({ data: skill })
})

describe('SkillEditor single tool surface (FIX-20261102-062047)', () => {
  it('pre-selects existing bindings from tool_bindings in the single list', async () => {
    renderEditor('edit')
    expect(await screen.findByText('run_sql')).toBeDefined()
    // Referenced cc tool: metadata comes from the binding (not the catalogue).
    expect(screen.getByText('create_skill')).toBeDefined()
    expect(screen.getAllByText('supabase____run_sql').length).toBeGreaterThan(0)
    expect(screen.getAllByText('cc____create_skill').length).toBeGreaterThan(0)
    // ONE surface: the duplicate read-only card is gone.
    expect(screen.getAllByText('Bound tools')).toHaveLength(1)
  })

  it('shows the cc dependency read-only with the permission note', async () => {
    renderEditor('edit')
    expect(
      await screen.findByText(
        'Access to this tool requires the Control Center integration permission — shown read-only because this skill uses it.',
      ),
    ).toBeDefined()
    // The referenced cc tool cannot be removed from the editor.
    expect(screen.queryByLabelText('Remove create_skill')).toBeNull()
  })

  it('toggling a tool in the picker updates the SAME list', async () => {
    renderEditor('edit')
    await screen.findByText('run_sql')
    fireEvent.click(screen.getByText('Select Tools'))

    const issueCheckbox = await screen.findByRole('checkbox', {
      name: /github____create_issue/,
    })
    fireEvent.click(issueCheckbox)
    fireEvent.click(screen.getByText('Confirm Selection'))

    await waitFor(() => {
      expect(screen.getByText('create_issue')).toBeDefined()
    })
    expect(screen.getAllByText('Bound tools')).toHaveLength(1)
  })

  it('saves the union of bound + newly selected tools, never dropping the referenced cc tool', async () => {
    renderEditor('edit')
    await screen.findByText('run_sql')

    // Deselect the browsable tool via the single list's remove affordance.
    fireEvent.click(screen.getByLabelText('Remove run_sql'))
    await waitFor(() => expect(screen.queryByLabelText('Remove run_sql')).toBeNull())

    fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(putMock).toHaveBeenCalled())
    const [url, payload] = putMock.mock.calls[0] as [string, { tool_ids: string[] }]
    expect(url).toBe('/skills/s1')
    expect(payload.tool_ids).toContain(CC_TOOL_ID)
    expect(payload.tool_ids).not.toContain('t-run')
  })

  it('view mode renders the same single list read-only', async () => {
    renderEditor('view')
    expect(await screen.findByText('run_sql')).toBeDefined()
    expect(screen.getByText('create_skill')).toBeDefined()
    expect(screen.getByText('Supabase')).toBeDefined()
    expect(screen.getByText('Control Center')).toBeDefined()
    expect(screen.getAllByText('Bound tools')).toHaveLength(1)
    // No edit affordances in view mode.
    expect(screen.queryByLabelText('Remove run_sql')).toBeNull()
  })

  it('shows the muted empty indicator when nothing is bound', async () => {
    const bare: Skill = { ...skill, tool_ids: [], tool_bindings: [] }
    vi.mocked(useAllTools).mockReturnValue({
      data: [RUN_SQL],
      isLoading: false,
    } as unknown as ReturnType<typeof useAllTools>)
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
    expect(await screen.findByText('No tools bound')).toBeDefined()
  })
})
