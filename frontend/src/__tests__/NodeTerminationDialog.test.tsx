import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { NodeTerminationDialog } from '../components/agents/NodeTerminationDialog'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

describe('NodeTerminationDialog', () => {
  it('submits node_only scope and reason from operator input', async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined)
    const onClose = vi.fn()

    render(
      <MemoryRouter>
        <NodeTerminationDialog
          open
          onClose={onClose}
          selectedNode={{
            session_id: 'sess-node-001',
            agent_type_id: 'at-1',
            agent_type_name: 'Node Agent',
            status: 'running',
            depth_from_root: 0,
            parent_session_id: null,
            started_at: null,
            created_at: '2026-06-01T00:00:00Z',
            termination_category: null,
          }}
          onConfirm={onConfirm}
          isSubmitting={false}
        />
      </MemoryRouter>,
    )

    fireEvent.mouseDown(screen.getByRole('combobox'))
    fireEvent.click(screen.getByRole('option', { name: 'agents.sessions.runtimeTerminateNodeOnly' }))

    fireEvent.change(screen.getByLabelText('agents.sessions.runtimeTerminationReason'), {
      target: { value: 'unsafe cascade branch' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'agents.sessions.runtimeConfirmTerminate' }))

    await waitFor(() => {
      expect(onConfirm).toHaveBeenCalledWith('node_only', 'unsafe cascade branch')
    })
  })

  it('renders inline error alert when terminate action is denied', async () => {
    const onConfirm = vi.fn().mockRejectedValue(new Error('403 forbidden'))

    render(
      <MemoryRouter>
        <NodeTerminationDialog
          open
          onClose={vi.fn()}
          selectedNode={{
            session_id: 'sess-node-002',
            agent_type_id: 'at-2',
            agent_type_name: 'Node Agent',
            status: 'running',
            depth_from_root: 0,
            parent_session_id: null,
            started_at: null,
            created_at: '2026-06-01T00:00:00Z',
            termination_category: null,
          }}
          onConfirm={onConfirm}
          isSubmitting={false}
        />
      </MemoryRouter>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'agents.sessions.runtimeConfirmTerminate' }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeDefined()
    })
  })
})
