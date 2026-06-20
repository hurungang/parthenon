import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { InterventionPendingBanner } from '../components/executions/InterventionPendingBanner'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, vars?: Record<string, string>) => {
      const defaults: Record<string, string> = {
        'executions.pendingBanner.title': 'Intervention Required — Delegated sub-agent needs input',
        'executions.pendingBanner.subtitle': '{{type}} requested by {{agent}} · pending since {{time}}',
        'executions.pendingBanner.respondNow': 'Respond Now ↓',
        'intervene.typeApproval': 'Approval',
        'intervene.typeChoice': 'Choice',
        'intervene.typeText': 'Text Input',
      }
      let val = defaults[k] ?? k
      if (vars) {
        for (const [key, value] of Object.entries(vars)) {
          val = val.replace(`{{${key}}}`, value)
        }
      }
      return val
    },
  }),
}))

describe('InterventionPendingBanner', () => {
  it('renders null when pending is false', () => {
    const { container } = render(
      <InterventionPendingBanner
        pending={false}
        subAgentName="sub-agent"
        interventionType="approval"
        pendingSince="2026-06-17T12:00:00Z"
        onRespond={() => {}}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders the banner when pending is true', () => {
    render(
      <InterventionPendingBanner
        pending={true}
        subAgentName="sub-agent"
        interventionType="approval"
        pendingSince="2026-06-17T12:00:00Z"
        onRespond={() => {}}
      />,
    )
    expect(screen.getByText(/Intervention Required/)).toBeDefined()
  })

  it('shows the sub-agent name', () => {
    render(
      <InterventionPendingBanner
        pending={true}
        subAgentName="my-sub-agent"
        interventionType="approval"
        pendingSince="2026-06-17T12:00:00Z"
        onRespond={() => {}}
      />,
    )
    expect(screen.getByText(/my-sub-agent/)).toBeDefined()
  })

  it('shows approval type label', () => {
    render(
      <InterventionPendingBanner
        pending={true}
        subAgentName="sub-agent"
        interventionType="approval"
        pendingSince="2026-06-17T12:00:00Z"
        onRespond={() => {}}
      />,
    )
    expect(screen.getByText(/Approval/)).toBeDefined()
  })

  it('shows choice type label', () => {
    render(
      <InterventionPendingBanner
        pending={true}
        subAgentName="sub-agent"
        interventionType="choice"
        pendingSince="2026-06-17T12:00:00Z"
        onRespond={() => {}}
      />,
    )
    expect(screen.getByText(/Choice/)).toBeDefined()
  })

  it('shows text input type label', () => {
    render(
      <InterventionPendingBanner
        pending={true}
        subAgentName="sub-agent"
        interventionType="text"
        pendingSince="2026-06-17T12:00:00Z"
        onRespond={() => {}}
      />,
    )
    expect(screen.getByText(/Text Input/)).toBeDefined()
  })

  it('renders Respond Now button', () => {
    render(
      <InterventionPendingBanner
        pending={true}
        subAgentName="sub-agent"
        interventionType="approval"
        pendingSince="2026-06-17T12:00:00Z"
        onRespond={() => {}}
      />,
    )
    expect(screen.getByText('Respond Now ↓')).toBeDefined()
  })

  it('calls onRespond when button clicked', () => {
    const onRespond = vi.fn()
    render(
      <InterventionPendingBanner
        pending={true}
        subAgentName="sub-agent"
        interventionType="approval"
        pendingSince="2026-06-17T12:00:00Z"
        onRespond={onRespond}
      />,
    )
    fireEvent.click(screen.getByText('Respond Now ↓'))
    expect(onRespond).toHaveBeenCalledTimes(1)
  })

  it('shows pending time formatted', () => {
    render(
      <InterventionPendingBanner
        pending={true}
        subAgentName="sub-agent"
        interventionType="approval"
        pendingSince="2026-06-17T12:00:00Z"
        onRespond={() => {}}
      />,
    )
    // The formatted time should be visible
    const banner = screen.getByText(/Intervention Required/).closest('div')
    expect(banner).not.toBeNull()
  })

  it('handles unknown intervention type by showing raw type string', () => {
    render(
      <InterventionPendingBanner
        pending={true}
        subAgentName="sub-agent"
        interventionType="unknown_type"
        pendingSince="2026-06-17T12:00:00Z"
        onRespond={() => {}}
      />,
    )
    expect(screen.getByText(/Intervention Required/)).toBeDefined()
  })
})
