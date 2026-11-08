import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ResolvedInterventionBubble } from '../components/conversations/ResolvedInterventionBubble'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, unknown>) => {
      const map: Record<string, string> = {
        'conversations.sessions.intervention.resolvedTitle': `Intervention resolved — ${String(opts?.agentType ?? 'Agent')} continued`,
        'conversations.sessions.intervention.resolvedLabel': 'Intervention resolved:',
        'conversations.sessions.intervention.resolvedBadge': 'Actioned',
        'conversations.sessions.intervention.yourAnswer': 'Answer provided',
        'conversations.sessions.intervention.responseSubmittedFallback': 'Response submitted',
        'conversations.sessions.intervention.viewRequest': 'View request',
        'conversations.sessions.intervention.viewRequestTitle': 'Intervention request (actioned)',
        'conversations.sessions.intervention.requestLabel': 'Original request',
        'conversations.sessions.intervention.optionsLabel': 'Options',
        'app.close': 'Close',
      }
      return map[k] ?? k
    },
  }),
}))

vi.mock('../components/ContentRenderer', () => ({
  ContentRenderer: ({ content }: { content: string }) => <div data-testid="reason-content">{content}</div>,
}))

describe('ResolvedInterventionBubble', () => {
  const baseData = {
    id: 'resolved-1',
    interventionType: 'approval' as const,
    reason: 'Approve this action?',
    choices: null,
    agentType: 'Control Center Assistant',
    answer: 'Approve',
    resolvedAt: '2026-11-07T10:00:00Z',
  }

  it('renders the confirmation with the answer provided', () => {
    render(<ResolvedInterventionBubble data={baseData} />)
    expect(screen.getByText('Intervention resolved:')).toBeDefined()
    expect(screen.getByText('Approve')).toBeDefined()
    // No action buttons — the intervention is already actioned
    expect(screen.queryByText('Approve this action?')).toBeNull()
  })

  it('opens a view-only dialog with the original request and answer, no action buttons', () => {
    render(<ResolvedInterventionBubble data={baseData} />)
    fireEvent.click(screen.getByText('View request'))
    expect(screen.getByTestId('resolved-intervention-view')).toBeDefined()
    expect(screen.getByTestId('reason-content')).toHaveTextContent('Approve this action?')
    expect(screen.getByText('Answer provided')).toBeDefined()
    // Strictly read-only: no Approve/Deny/Submit actions in the dialog
    expect(screen.queryByRole('button', { name: /^Approve$/ })).toBeNull()
    expect(screen.queryByText('Deny')).toBeNull()
    expect(screen.queryByText('Submit Response')).toBeNull()
    expect(screen.getByText('Close')).toBeDefined()
  })

  it('falls back to a generic summary when the answer is null', () => {
    render(<ResolvedInterventionBubble data={{ ...baseData, answer: null }} />)
    expect(screen.getByText('Response submitted')).toBeDefined()
  })
})
