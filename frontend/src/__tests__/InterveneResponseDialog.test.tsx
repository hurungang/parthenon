import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { InterveneResponseDialog } from '../components/agents/InterveneResponseDialog'

const mockSetDialogError = vi.fn()
const mockClearDialogError = vi.fn()

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../hooks/useDialogErrorHandler', () => ({
  useDialogErrorHandler: () => ({
    dialogError: null,
    setDialogError: mockSetDialogError,
    clearDialogError: mockClearDialogError,
  }),
}))

const baseRequest = {
  id: 'req-123',
  agent_session_id: 'sess-abc',
  agent_type_id: 'agent-1',
  reason: 'Please approve this action',
  status: 'pending' as const,
  created_at: '2026-06-01T00:00:00Z',
}

describe('InterveneResponseDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders approval dialog with Yes/No buttons', () => {
    render(
      <InterveneResponseDialog
        open
        request={{ ...baseRequest, intervention_type: 'approval' as const }}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    )
    expect(screen.getByText('intervene.responseDialogTitle')).toBeDefined()
    expect(screen.getByText('app.yes')).toBeDefined()
    expect(screen.getByText('app.no')).toBeDefined()
    expect(screen.getByText('intervene.typeApproval')).toBeDefined()
    expect(screen.getByText('Please approve this action')).toBeDefined()
  })

  it('renders choice dialog with radio options', () => {
    render(
      <InterveneResponseDialog
        open
        request={{
          ...baseRequest,
          intervention_type: 'choice' as const,
          choices: ['Option A', 'Option B', 'Option C'],
        }}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    )
    expect(screen.getByText('intervene.typeChoice')).toBeDefined()
    expect(screen.getByText('intervene.selectOption')).toBeDefined()
    expect(screen.getByText('Option A')).toBeDefined()
    expect(screen.getByText('Option B')).toBeDefined()
    expect(screen.getByText('Option C')).toBeDefined()
  })

  it('renders text dialog with text input', () => {
    render(
      <InterveneResponseDialog
        open
        request={{
          ...baseRequest,
          intervention_type: 'text' as const,
        }}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    )
    expect(screen.getByText('intervene.typeText')).toBeDefined()
    expect(screen.getAllByText('intervene.textResponse').length).toBeGreaterThan(0)
  })

  it('calls onSubmit with approval_value=true when Yes is selected and submitted', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(
      <InterveneResponseDialog
        open
        request={{ ...baseRequest, intervention_type: 'approval' as const }}
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    )
    fireEvent.click(screen.getByText('app.yes'))
    fireEvent.click(screen.getByText('intervene.submitResponse'))
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith('req-123', { approval_value: true })
    })
  })

  it('calls onSubmit with approval_value=false when No is selected and submitted', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(
      <InterveneResponseDialog
        open
        request={{ ...baseRequest, intervention_type: 'approval' as const }}
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    )
    fireEvent.click(screen.getByText('app.no'))
    fireEvent.click(screen.getByText('intervene.submitResponse'))
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith('req-123', { approval_value: false })
    })
  })

  it('calls onSubmit with selected_choice when a choice is selected and submitted', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(
      <InterveneResponseDialog
        open
        request={{
          ...baseRequest,
          intervention_type: 'choice' as const,
          choices: ['Red', 'Green', 'Blue'],
        }}
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    )
    fireEvent.click(screen.getByText('Green'))
    fireEvent.click(screen.getByText('intervene.submitResponse'))
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith('req-123', { selected_choice: 'Green' })
    })
  })

  it('disables submit for choice when no option selected', () => {
    render(
      <InterveneResponseDialog
        open
        request={{
          ...baseRequest,
          intervention_type: 'choice' as const,
          choices: ['A', 'B'],
        }}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    )
    const submitBtn = screen.getByText('intervene.submitResponse').closest('button')
    expect(submitBtn).toBeDisabled()
  })

  it('calls onSubmit with text_value when text is entered and submitted', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(
      <InterveneResponseDialog
        open
        request={{
          ...baseRequest,
          intervention_type: 'text' as const,
        }}
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    )
    const textarea = screen.getByRole('textbox')
    fireEvent.change(textarea, { target: { value: 'My response text' } })
    fireEvent.click(screen.getByText('intervene.submitResponse'))
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith('req-123', { text_value: 'My response text' })
    })
  })

  it('shows error alert when onSubmit throws', async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error('API error'))
    render(
      <InterveneResponseDialog
        open
        request={{ ...baseRequest, intervention_type: 'approval' as const }}
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    )
    fireEvent.click(screen.getByText('app.yes'))
    fireEvent.click(screen.getByText('intervene.submitResponse'))
    await waitFor(() => {
      expect(mockSetDialogError).toHaveBeenCalled()
    })
  })

  it('returns null when request is null', () => {
    const { container } = render(
      <InterveneResponseDialog
        open
        request={null}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    )
    expect(container.innerHTML).toBe('')
  })

  it('closes dialog and clears error on cancel click', () => {
    const onClose = vi.fn()
    render(
      <InterveneResponseDialog
        open
        request={{ ...baseRequest, intervention_type: 'approval' as const }}
        onClose={onClose}
        onSubmit={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByText('app.cancel'))
    expect(onClose).toHaveBeenCalled()
    expect(mockClearDialogError).toHaveBeenCalled()
  })
})
