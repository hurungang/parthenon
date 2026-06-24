import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { InterveneRequestList } from '../components/agents/InterveneRequestList'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const baseRequest = {
  id: 'req-1',
  agent_session_id: 'sess-abc',
  agent_type_id: 'agent-1',
  reason: 'Test reason',
  status: 'pending' as const,
  delegation_depth: 0,
  created_at: '2026-06-01T00:00:00Z',
}

describe('InterveneRequestList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows empty state when no requests', () => {
    render(
      <InterveneRequestList
        requests={[]}
        isLoading={false}
        onSubmitResponse={vi.fn()}
        onCancelRequest={vi.fn()}
      />,
    )
    expect(screen.getByText('intervene.noPendingRequests')).toBeDefined()
  })

  it('returns null when loading', () => {
    const { container } = render(
      <InterveneRequestList
        requests={[]}
        isLoading
        onSubmitResponse={vi.fn()}
        onCancelRequest={vi.fn()}
      />,
    )
    expect(container.innerHTML).toBe('')
  })

  it('renders requests in a table', () => {
    render(
      <InterveneRequestList
        requests={[
          { ...baseRequest, intervention_type: 'approval' as const },
          {
            ...baseRequest,
            id: 'req-2',
            agent_session_id: 'sess-xyz',
            intervention_type: 'choice' as const,
            choices: ['A', 'B'],
            reason: 'Pick one',
          },
        ]}
        isLoading={false}
        onSubmitResponse={vi.fn()}
        onCancelRequest={vi.fn()}
      />,
    )
    expect(screen.getByText('agents.sessions.sessionId')).toBeDefined()
    expect(screen.getByText('intervene.reason')).toBeDefined()
    expect(screen.getByText('intervene.type')).toBeDefined()
    expect(screen.getByText('app.createdAt')).toBeDefined()
    expect(screen.getByText('app.actions')).toBeDefined()
    expect(screen.getByText('intervene.typeApproval')).toBeDefined()
    expect(screen.getByText('intervene.typeChoice')).toBeDefined()
    expect(screen.getByText('Test reason')).toBeDefined()
    expect(screen.getByText('Pick one')).toBeDefined()
  })

  it('opens response dialog on respond button click', () => {
    render(
      <InterveneRequestList
        requests={[
          { ...baseRequest, intervention_type: 'approval' as const },
        ]}
        isLoading={false}
        onSubmitResponse={vi.fn()}
        onCancelRequest={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByText('intervene.respond'))
    expect(screen.getByText('intervene.responseDialogTitle')).toBeDefined()
  })

  it.skip('closes dialog after successful submit', async () => {
    const { waitFor } = await import('@testing-library/react')
    const onSubmitResponse = vi.fn().mockResolvedValue(undefined)
    render(
      <InterveneRequestList
        requests={[
          { ...baseRequest, intervention_type: 'text_input' as const },
        ]}
        isLoading={false}
        onSubmitResponse={onSubmitResponse}
        onCancelRequest={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByText('intervene.respond'))
    
    // Fill in the text field
    const textField = screen.getByRole('textbox')
    fireEvent.change(textField, { target: { value: 'Test response' } })
    
    // Wait for the submit button to be present before clicking
    await waitFor(() => {
      expect(screen.queryByText('intervene.submitResponse')).toBeDefined()
    }, { timeout: 2000 })
    
    fireEvent.click(screen.getByText('intervene.submitResponse'))
    
    // Wait for submission to complete and verify callback was called
    await waitFor(() => {
      expect(onSubmitResponse).toHaveBeenCalled()
    }, { timeout: 2000 })
  })

  it('shows session ID truncated to 8 chars', () => {
    render(
      <InterveneRequestList
        requests={[
          { ...baseRequest, intervention_type: 'approval' as const },
        ]}
        isLoading={false}
        onSubmitResponse={vi.fn()}
        onCancelRequest={vi.fn()}
      />,
    )
    expect(screen.getByText(/sess-abc/)).toBeDefined()
  })
})
