import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { TaskInterventionDialog } from '../components/executions/TaskInterventionDialog'
import type { InterveneRequest } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, vars?: Record<string, string | number>) => {
      const defaults: Record<string, string> = {
        'executions.taskIntervention.title': 'Intervention Required',
        'executions.taskIntervention.requestedByMeta': 'Requested by {{agent}} during delegation',
        'executions.taskIntervention.approve': 'Approve',
        'executions.taskIntervention.deny': 'Deny',
        'executions.taskIntervention.textPlaceholder': 'Enter your response here...',
        'executions.taskIntervention.dismiss': 'Dismiss (banner stays)',
        'executions.taskIntervention.responseSubmitted': 'Response submitted',
        'executions.taskIntervention.choicesAvailable': 'Options available: {{count}}',
        'executions.taskIntervention.expiredMessage': 'This intervention request has expired.',
        'intervene.submitResponse': 'Submit Response',
        'intervene.responseDialogTitle': 'Human Intervention Required',
        'executions.taskIntervention.requestedBy': 'Requested by',
        'app.saving': 'Submitting...',
        'app.error': 'Error',
      }
      let val = defaults[k] ?? k
      if (vars) {
        for (const [key, value] of Object.entries(vars)) {
          val = val.replace(`{{${key}}}`, String(value))
        }
      }
      return val
    },
  }),
}))

vi.mock('../components/permissions/PermissionDeniedAlert', () => ({
  default: ({ fallbackMessage }: { fallbackMessage: string }) => (
    <div data-testid="permission-denied-alert">{fallbackMessage}</div>
  ),
}))

function makeRequest(overrides: Partial<InterveneRequest> = {}): InterveneRequest {
  return {
    id: 'req-123',
    agent_session_id: 'session-abc',
    agent_type_id: 'agent-type-1',
    intervention_type: 'approval',
    reason: 'Approve transaction exceeding limit',
    status: 'pending',
    delegation_depth: 1,
    created_at: '2026-06-17T12:00:00Z',
    ...overrides,
  }
}

describe('TaskInterventionDialog', () => {
  const noop = () => Promise.resolve()

  describe('approval type', () => {
    it('renders intervention required title', () => {
      render(
        <TaskInterventionDialog request={makeRequest()} onSubmit={noop} onDismiss={() => {}} />,
      )
      expect(screen.getByText('Intervention Required')).toBeDefined()
    })

    it('renders approve and deny buttons', () => {
      render(
        <TaskInterventionDialog request={makeRequest()} onSubmit={noop} onDismiss={() => {}} />,
      )
      // Buttons contain icon prefix (✓ Approve), so use getByRole with name matcher
      expect(screen.getByRole('button', { name: /Approve/ })).toBeDefined()
      expect(screen.getByRole('button', { name: /Deny/ })).toBeDefined()
    })

    it('shows the reason text', () => {
      render(
        <TaskInterventionDialog
          request={makeRequest({ reason: 'Please approve this action' })}
          onSubmit={noop}
          onDismiss={() => {}}
        />,
      )
      expect(screen.getByText('Please approve this action')).toBeDefined()
    })

    it('shows APPROVAL badge', () => {
      render(
        <TaskInterventionDialog request={makeRequest()} onSubmit={noop} onDismiss={() => {}} />,
      )
      expect(screen.getByText('APPROVAL')).toBeDefined()
    })

    it('renders Submit Response button', () => {
      render(
        <TaskInterventionDialog request={makeRequest()} onSubmit={noop} onDismiss={() => {}} />,
      )
      expect(screen.getByText('Submit Response')).toBeDefined()
    })

    it('renders Dismiss button', () => {
      render(
        <TaskInterventionDialog request={makeRequest()} onSubmit={noop} onDismiss={() => {}} />,
      )
      expect(screen.getByText(/Dismiss/)).toBeDefined()
    })
  })

  describe('choice type', () => {
    it('renders CHOICE badge', () => {
      render(
        <TaskInterventionDialog
          request={makeRequest({ intervention_type: 'choice', choices: ['Option A', 'Option B'] })}
          onSubmit={noop}
          onDismiss={() => {}}
        />,
      )
      expect(screen.getByText('CHOICE')).toBeDefined()
    })

    it('renders choice options', () => {
      render(
        <TaskInterventionDialog
          request={makeRequest({ intervention_type: 'choice', choices: ['Option A', 'Option B'] })}
          onSubmit={noop}
          onDismiss={() => {}}
        />,
      )
      expect(screen.getByText('Option A')).toBeDefined()
      expect(screen.getByText('Option B')).toBeDefined()
    })
  })

  describe('text type', () => {
    it('renders TEXT INPUT badge', () => {
      render(
        <TaskInterventionDialog
          request={makeRequest({ intervention_type: 'text' })}
          onSubmit={noop}
          onDismiss={() => {}}
        />,
      )
      expect(screen.getByText('TEXT INPUT')).toBeDefined()
    })

    it('renders a text input field', () => {
      render(
        <TaskInterventionDialog
          request={makeRequest({ intervention_type: 'text' })}
          onSubmit={noop}
          onDismiss={() => {}}
        />,
      )
      expect(screen.getByPlaceholderText('Enter your response here...')).toBeDefined()
    })

    it('shows character count for text input', () => {
      render(
        <TaskInterventionDialog
          request={makeRequest({ intervention_type: 'text' })}
          onSubmit={noop}
          onDismiss={() => {}}
        />,
      )
      expect(screen.getByText('0/2000')).toBeDefined()
    })
  })

  describe('expired state', () => {
    it('shows expired message when expired is true', () => {
      render(
        <TaskInterventionDialog
          request={makeRequest()}
          onSubmit={noop}
          onDismiss={() => {}}
          expired={true}
        />,
      )
      expect(screen.getByText(/expired/)).toBeDefined()
    })

    it('does not show approve/deny buttons when expired', () => {
      render(
        <TaskInterventionDialog
          request={makeRequest()}
          onSubmit={noop}
          onDismiss={() => {}}
          expired={true}
        />,
      )
      // Can't interact when expired
      expect(screen.queryByText('Submit Response')).toBeNull()
    })
  })
})
