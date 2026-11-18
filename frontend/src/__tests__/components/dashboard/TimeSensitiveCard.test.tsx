import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { TimeSensitiveCard } from '../../../components/dashboard/TimeSensitiveCard'
import type { ReactNode } from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

describe('TimeSensitiveCard', () => {
  const defaultSingleProps = {
    variant: 'single' as const,
    icon: '🚨' as ReactNode,
    label: 'Guardrail Breach Events',
    value: 3,
    isLoading: false,
    isPermissionDenied: false,
    colorVariant: 'red' as const,
  }

  const defaultDualProps = {
    variant: 'dual' as const,
    icon: '▶️' as ReactNode,
    label: 'Agent Executions',
    completed: 42,
    failed: 3,
    isLoading: false,
    isPermissionDenied: false,
    colorVariant: 'blue' as const,
  }

  it('renders single-value variant with value', () => {
    render(<TimeSensitiveCard {...defaultSingleProps} />)
    expect(screen.getByText('3')).toBeTruthy()
    expect(screen.getByText('Guardrail Breach Events')).toBeTruthy()
  })

  it('renders dual-value variant with completed/failed', () => {
    render(<TimeSensitiveCard {...defaultDualProps} />)
    expect(screen.getByText('42')).toBeTruthy()
    expect(screen.getByText('3')).toBeTruthy()
  })

  it('renders loading skeleton state', () => {
    render(<TimeSensitiveCard {...defaultSingleProps} isLoading={true} />)
    expect(screen.queryByText('3')).toBeNull()
  })

  it('renders permission-denied state', () => {
    render(<TimeSensitiveCard {...defaultSingleProps} isPermissionDenied={true} />)
    expect(screen.getByText('permissions.errors.accessDeniedTitle')).toBeTruthy()
    expect(screen.queryByText('3')).toBeNull()
  })

  it('renders zero state in dual variant', () => {
    render(<TimeSensitiveCard {...defaultDualProps} completed={0} failed={0} />)
    const zeros = screen.getAllByText('0')
    expect(zeros.length).toBeGreaterThanOrEqual(1)
  })
})

/**
 * FIX-20261116-214714 — the time-sensitive cards must expose the same status
 * tone / action-required contract as `StatCard` so the dashboard can rank
 * actionable tiles (breaches, failed executions, failed notifications).
 *
 * Contract under test:
 *  - `statusTone?: 'success' | 'warning' | 'error'` on the root MUI Card as
 *    `data-status-tone` (defaulting to `neutral`).
 *  - `actionRequired?: boolean` on the root MUI Card as
 *    `data-action-required` ("true" / "false").
 *  - `actionRequired` renders the `dashboard.actionRequired` badge.
 *  - The permission-denied placeholder never renders the badge.
 */
describe('TimeSensitiveCard — status tone and action-required highlight', () => {
  const baseProps = {
    variant: 'single' as const,
    icon: '🚨' as ReactNode,
    label: 'Guardrail Breach Events',
    value: 2,
    isLoading: false,
    isPermissionDenied: false,
    colorVariant: 'red' as const,
  }

  function rootCard(container: HTMLElement): HTMLElement {
    const card = container.querySelector('.MuiCard-root')
    if (!card) throw new Error('TimeSensitiveCard did not render a root MuiCard element')
    return card as HTMLElement
  }

  it('renders the action-required badge and data-action-required="true" when action is required', () => {
    const { container } = render(
      <TimeSensitiveCard {...baseProps} statusTone="error" actionRequired={true} />,
    )
    const card = rootCard(container)

    expect(card.getAttribute('data-action-required')).toBe('true')
    expect(within(card).getByText('dashboard.actionRequired')).toBeTruthy()
  })

  it('defaults to data-action-required="false" and renders no badge', () => {
    const { container } = render(<TimeSensitiveCard {...baseProps} />)
    const card = rootCard(container)

    expect(card.getAttribute('data-action-required')).toBe('false')
    expect(within(card).queryByText('dashboard.actionRequired')).toBeNull()
  })

  it('exposes data-status-tone="neutral" when no status tone is supplied', () => {
    const { container } = render(<TimeSensitiveCard {...baseProps} />)
    expect(rootCard(container).getAttribute('data-status-tone')).toBe('neutral')
  })

  it('maps statusTone="success" to data-status-tone="success"', () => {
    const { container } = render(
      <TimeSensitiveCard {...baseProps} value={0} statusTone="success" />,
    )
    expect(rootCard(container).getAttribute('data-status-tone')).toBe('success')
  })

  it('maps statusTone="warning" to data-status-tone="warning"', () => {
    const { container } = render(
      <TimeSensitiveCard {...baseProps} value={1} statusTone="warning" />,
    )
    expect(rootCard(container).getAttribute('data-status-tone')).toBe('warning')
  })

  it('maps statusTone="error" to data-status-tone="error"', () => {
    const { container } = render(
      <TimeSensitiveCard {...baseProps} value={4} statusTone="error" />,
    )
    expect(rootCard(container).getAttribute('data-status-tone')).toBe('error')
  })

  it('supports the action-required contract on the dual variant', () => {
    const { container } = render(
      <TimeSensitiveCard
        variant="dual"
        icon={'▶️' as ReactNode}
        label="Agent Executions"
        completed={10}
        failed={3}
        isLoading={false}
        isPermissionDenied={false}
        colorVariant="blue"
        statusTone="error"
        actionRequired={true}
      />,
    )
    const card = rootCard(container)

    expect(card.getAttribute('data-status-tone')).toBe('error')
    expect(card.getAttribute('data-action-required')).toBe('true')
    expect(within(card).getByText('dashboard.actionRequired')).toBeTruthy()
  })

  it('does NOT render the action-required badge in the permission-denied state', () => {
    const { container } = render(
      <TimeSensitiveCard
        {...baseProps}
        isPermissionDenied={true}
        statusTone="error"
        actionRequired={true}
      />,
    )
    const card = rootCard(container)

    expect(within(card).getByText('permissions.errors.accessDeniedTitle')).toBeTruthy()
    expect(within(card).queryByText('dashboard.actionRequired')).toBeNull()
  })
})
