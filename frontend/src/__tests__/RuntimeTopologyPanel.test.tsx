import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { RuntimeTopologyPanel } from '../components/agents/RuntimeTopologyPanel'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

describe('RuntimeTopologyPanel', () => {
  it('renders topology depth groups and allows node selection', () => {
    const onSelectSession = vi.fn()
    const onTerminate = vi.fn()

    render(
      <RuntimeTopologyPanel
        topology={{
          nodes: [
            {
              session_id: 'sess-root-001',
              agent_type_id: 'at-root',
              agent_type_name: 'Root Agent',
              status: 'running',
              depth_from_root: 0,
              parent_session_id: null,
              started_at: null,
              created_at: '2026-06-01T00:00:00Z',
              termination_category: null,
            },
            {
              session_id: 'sess-child-001',
              agent_type_id: 'at-child',
              agent_type_name: 'Child Agent',
              status: 'queued',
              depth_from_root: 1,
              parent_session_id: 'sess-root-001',
              started_at: null,
              created_at: '2026-06-01T00:00:00Z',
              termination_category: null,
            },
          ],
          edges: [
            {
              parent_session_id: 'sess-root-001',
              child_session_id: 'sess-child-001',
              depth_from_root: 1,
            },
          ],
          root_session_ids: ['sess-root-001'],
        }}
        selectedSessionId={null}
        onSelectSession={onSelectSession}
        onTerminate={onTerminate}
        canTerminate
      />,
    )

    fireEvent.click(screen.getByText('Root Agent'))
    expect(onSelectSession).toHaveBeenCalledWith('sess-root-001')
  })

  it('disables terminate action when permission is not granted', () => {
    const onSelectSession = vi.fn()
    const onTerminate = vi.fn()

    render(
      <RuntimeTopologyPanel
        topology={{
          nodes: [
            {
              session_id: 'sess-root-001',
              agent_type_id: 'at-root',
              agent_type_name: 'Root Agent',
              status: 'running',
              depth_from_root: 0,
              parent_session_id: null,
              started_at: null,
              created_at: '2026-06-01T00:00:00Z',
              termination_category: null,
            },
          ],
          edges: [],
          root_session_ids: ['sess-root-001'],
        }}
        selectedSessionId={'sess-root-001'}
        onSelectSession={onSelectSession}
        onTerminate={onTerminate}
        canTerminate={false}
      />,
    )

    const terminateButton = screen.getByRole('button', {
      name: 'agents.sessions.runtimeTerminateNode',
    })
    expect(terminateButton).toBeDisabled()
  })
})
