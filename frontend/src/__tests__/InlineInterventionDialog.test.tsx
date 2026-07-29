import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { InlineInterventionDialog } from '../components/conversations/InlineInterventionDialog'
import type { InterveneRequestMessage } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, unknown>) => {
      const map: Record<string, string> = {
        'conversations.sessions.intervention.requiresYourInput': opts?.agentType
          ? `Requires your input - ${String(opts.agentType)}`
          : 'Requires your input',
        'conversations.sessions.intervention.delegatedBy': opts?.parentAgent
          ? `Delegated by ${String(opts.parentAgent)} (depth ${String(opts.depth)})`
          : 'Delegated by parent',
        'conversations.sessions.intervention.typeApproval': 'Approval',
        'conversations.sessions.intervention.typeChoice': 'Choice',
        'conversations.sessions.intervention.typeText': 'Text',
        'conversations.sessions.intervention.approve': 'Approve',
        'conversations.sessions.intervention.deny': 'Deny',
        'conversations.sessions.intervention.confirmSelection': 'Confirm Selection',
        'conversations.sessions.intervention.submitResponse': 'Submit Response',
        'conversations.sessions.intervention.dismissCancel': 'Dismiss / Cancel',
        'conversations.sessions.intervention.placeholderText': 'Enter your response...',
        'app.error': 'An error occurred',
      }
      return map[k] ?? k
    },
  }),
}))

vi.mock('../components/permissions/PermissionDeniedAlert', () => ({
  default: ({ error, fallbackMessage }: { error?: unknown; fallbackMessage?: string }) => (
    <div data-testid="permission-denied-alert">
      {error instanceof Error ? error.message : fallbackMessage ?? 'Permission denied'}
    </div>
  ),
}))

const baseRequest: InterveneRequestMessage = {
  type: 'intervene_request',
  request_id: 'req-001',
  intervention_type: 'approval',
  reason: 'Approve this action?',
  choices: undefined,
  agent_type: 'FraudCheckAgent',
  delegation_depth: 1,
  conversation_session_id: 'conv-abc',
}

describe('InlineInterventionDialog', () => {
  let onApprove: () => void | Promise<void>
  let onDeny: () => void | Promise<void>
  let onSelectChoice: (choice: string) => void | Promise<void>
  let onSubmitText: (text: string) => void | Promise<void>
  let onDismiss: () => void | Promise<void>

  beforeEach(() => {
    onApprove = vi.fn()
    onDeny = vi.fn()
    onSelectChoice = vi.fn()
    onSubmitText = vi.fn()
    onDismiss = vi.fn()
  })

  // ── Approval type ────────────────────────────────────────────────────────

  it('renders approve and deny buttons for approval type', () => {
    render(
      <InlineInterventionDialog
        request={baseRequest}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    expect(screen.getByText('Approve')).toBeDefined()
    expect(screen.getByText('Deny')).toBeDefined()
    expect(screen.getByText('Approve this action?')).toBeDefined()
  })

  it('calls onApprove when approve button clicked', async () => {
    render(
      <InlineInterventionDialog
        request={baseRequest}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    fireEvent.click(screen.getByText('Approve'))
    await waitFor(() => expect(onApprove).toHaveBeenCalledTimes(1))
  })

  it('calls onDeny when deny button clicked', async () => {
    render(
      <InlineInterventionDialog
        request={baseRequest}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    fireEvent.click(screen.getByText('Deny'))
    await waitFor(() => expect(onDeny).toHaveBeenCalledTimes(1))
  })

  // ── Choice type ──────────────────────────────────────────────────────────

  it('renders choice options for choice type', () => {
    render(
      <InlineInterventionDialog
        request={{
          ...baseRequest,
          intervention_type: 'choice',
          reason: 'Select an option:',
          choices: ['Option A', 'Option B', 'Option C'],
        }}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    expect(screen.getByText('Option A')).toBeDefined()
    expect(screen.getByText('Option B')).toBeDefined()
    expect(screen.getByText('Option C')).toBeDefined()
    expect(screen.getByText('Select an option:')).toBeDefined()
  })

  it('disables submit until a choice is selected', () => {
    render(
      <InlineInterventionDialog
        request={{
          ...baseRequest,
          intervention_type: 'choice',
          choices: ['X', 'Y'],
        }}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    const confirmBtn = screen.getByText('Confirm Selection')
    expect((confirmBtn as HTMLButtonElement).disabled).toBe(true)
  })

  it('calls onSelectChoice with selected value when submitted', async () => {
    render(
      <InlineInterventionDialog
        request={{
          ...baseRequest,
          intervention_type: 'choice',
          choices: ['Alpha', 'Beta'],
        }}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    // Select "Beta"
    fireEvent.click(screen.getByText('Beta'))
    // Click confirm
    fireEvent.click(screen.getByText('Confirm Selection'))
    await waitFor(() => {
      expect(onSelectChoice).toHaveBeenCalledWith('Beta')
    })
  })

  // ── Text type ────────────────────────────────────────────────────────────

  it('renders text input for text type', () => {
    render(
      <InlineInterventionDialog
        request={{
          ...baseRequest,
          intervention_type: 'text',
          reason: 'Describe the output:',
        }}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    expect(screen.getByPlaceholderText('Enter your response...')).toBeDefined()
  })

  it('disables submit when text is empty', () => {
    render(
      <InlineInterventionDialog
        request={{
          ...baseRequest,
          intervention_type: 'text',
        }}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    const submitBtn = screen.getByText('Submit Response')
    expect((submitBtn as HTMLButtonElement).disabled).toBe(true)
  })

  it('calls onSubmitText with entered value', async () => {
    render(
      <InlineInterventionDialog
        request={{
          ...baseRequest,
          intervention_type: 'text',
          reason: 'Your input?',
        }}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    const input = screen.getByPlaceholderText('Enter your response...')
    fireEvent.change(input, { target: { value: 'My custom response' } })
    fireEvent.click(screen.getByText('Submit Response'))
    await waitFor(() => {
      expect(onSubmitText).toHaveBeenCalledWith('My custom response')
    })
  })

  // ── Dismiss ──────────────────────────────────────────────────────────────

  it('calls onDismiss when dismiss button clicked', async () => {
    render(
      <InlineInterventionDialog
        request={baseRequest}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    fireEvent.click(screen.getByText('Dismiss / Cancel'))
    await waitFor(() => expect(onDismiss).toHaveBeenCalledTimes(1))
  })

  // ── Disabled state ───────────────────────────────────────────────────────

  it('disables all buttons when isSubmitting is true', () => {
    render(
      <InlineInterventionDialog
        request={baseRequest}
        isSubmitting
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    const approveBtn = screen.getByText('Approve') as HTMLButtonElement
    const denyBtn = screen.getByText('Deny') as HTMLButtonElement
    const dismissBtn = screen.getByText('Dismiss / Cancel') as HTMLButtonElement
    expect(approveBtn.disabled).toBe(true)
    expect(denyBtn.disabled).toBe(true)
    expect(dismissBtn.disabled).toBe(true)
  })

  // ── Error display ────────────────────────────────────────────────────────

  it('displays error banner when dialogError is set', () => {
    render(
      <InlineInterventionDialog
        request={baseRequest}
        dialogError={new Error('Permission denied')}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    expect(screen.getByTestId('permission-denied-alert')).toBeDefined()
    expect(screen.getByText('Permission denied')).toBeDefined()
  })

  it('does not display error when dialogError is null', () => {
    render(
      <InlineInterventionDialog
        request={baseRequest}
        dialogError={null}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    expect(screen.queryByTestId('permission-denied-alert')).toBeNull()
  })

  // ── Header and badge ─────────────────────────────────────────────────────

  it('renders agent type name in header', () => {
    render(
      <InlineInterventionDialog
        request={baseRequest}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    expect(screen.getByText('Requires your input - FraudCheckAgent')).toBeDefined()
  })

  it('renders delegation depth information', () => {
    render(
      <InlineInterventionDialog
        request={{ ...baseRequest, delegation_depth: 3 }}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    expect(screen.getByText('Delegated by FraudCheckAgent (depth 3)')).toBeDefined()
  })

  it('renders type badge for approval', () => {
    render(
      <InlineInterventionDialog
        request={{ ...baseRequest, intervention_type: 'approval' }}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    expect(screen.getByText('Approval')).toBeDefined()
  })

  it('renders type badge for choice', () => {
    render(
      <InlineInterventionDialog
        request={{ ...baseRequest, intervention_type: 'choice', choices: ['X'] }}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    expect(screen.getByText('Choice')).toBeDefined()
  })

  it('renders type badge for text', () => {
    render(
      <InlineInterventionDialog
        request={{ ...baseRequest, intervention_type: 'text' }}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    expect(screen.getByText('Text')).toBeDefined()
  })

  // ── Loading state ────────────────────────────────────────────────────────

  it('shows loading indicator when isSubmitting', () => {
    const { container } = render(
      <InlineInterventionDialog
        request={baseRequest}
        isSubmitting
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
    // LinearProgress renders as a div with role="progressbar"
    const progressBar = container.querySelector('[role="progressbar"]')
    expect(progressBar).not.toBeNull()
  })
})
