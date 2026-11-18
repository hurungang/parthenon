import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { StatCard } from '../../../components/dashboard/StatCard'
import type { ReactNode } from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

describe('StatCard', () => {
  const defaultProps = {
    icon: '🤖' as ReactNode,
    label: 'Agent Types',
    value: 12,
    isLoading: false,
    isPermissionDenied: false,
    colorVariant: 'blue' as const,
  }

  it('renders the value and label', () => {
    render(<StatCard {...defaultProps} />)
    expect(screen.getByText('12')).toBeTruthy()
    expect(screen.getByText('Agent Types')).toBeTruthy()
  })

  it('renders sub-breakdown chips', () => {
    render(
      <StatCard
        {...defaultProps}
        subBreakdowns={[
          { label: '8 active', color: '#15803D' },
          { label: '3 running', color: '#1D4ED8' },
        ]}
      />,
    )
    expect(screen.getByText('8 active')).toBeTruthy()
    expect(screen.getByText('3 running')).toBeTruthy()
  })

  it('renders sub-label text', () => {
    render(<StatCard {...defaultProps} subLabel="provisioned" />)
    expect(screen.getByText('provisioned')).toBeTruthy()
  })

  it('renders zero state with muted value', () => {
    render(<StatCard {...defaultProps} value={0} />)
    expect(screen.getByText('0')).toBeTruthy()
  })

  it('renders loading skeleton state', () => {
    render(<StatCard {...defaultProps} isLoading={true} />)
    // The value text should NOT be visible during loading
    expect(screen.queryByText('12')).toBeNull()
  })

  it('renders permission-denied state with lock icon', () => {
    render(<StatCard {...defaultProps} isPermissionDenied={true} />)
    expect(screen.getByText('permissions.errors.accessDeniedTitle')).toBeTruthy()
    // The value should be hidden
    expect(screen.queryByText('12')).toBeNull()
  })
})

/**
 * FIX-20261116-214714 — token-health tiles must expose a health tone and an
 * "action required" affordance so the dashboard can rank actionable tiles.
 *
 * Contract under test:
 *  - `statusTone?: 'success' | 'warning' | 'error'` on the root MUI Card as
 *    `data-status-tone` (defaulting to `neutral`).
 *  - `actionRequired?: boolean` on the root MUI Card as
 *    `data-action-required` ("true" / "false").
 *  - `actionRequired` renders the `dashboard.actionRequired` badge.
 *  - The permission-denied placeholder never renders the badge.
 */
describe('StatCard — status tone and action-required highlight', () => {
  const baseProps = {
    icon: '🪙' as ReactNode,
    label: 'Token Health',
    value: 3,
    isLoading: false,
    isPermissionDenied: false,
    colorVariant: 'red' as const,
  }

  function rootCard(container: HTMLElement): HTMLElement {
    const card = container.querySelector('.MuiCard-root')
    if (!card) throw new Error('StatCard did not render a root MuiCard element')
    return card as HTMLElement
  }

  it('renders the action-required badge and data-action-required="true" when action is required', () => {
    const { container } = render(
      <StatCard {...baseProps} statusTone="error" actionRequired={true} />,
    )
    const card = rootCard(container)

    expect(card.getAttribute('data-action-required')).toBe('true')
    expect(within(card).getByText('dashboard.actionRequired')).toBeTruthy()
  })

  it('defaults to data-action-required="false" and renders no badge', () => {
    const { container } = render(<StatCard {...baseProps} />)
    const card = rootCard(container)

    expect(card.getAttribute('data-action-required')).toBe('false')
    expect(within(card).queryByText('dashboard.actionRequired')).toBeNull()
  })

  it('exposes data-status-tone="neutral" when no status tone is supplied', () => {
    const { container } = render(<StatCard {...baseProps} />)
    expect(rootCard(container).getAttribute('data-status-tone')).toBe('neutral')
  })

  it('maps statusTone="success" to data-status-tone="success"', () => {
    const { container } = render(<StatCard {...baseProps} value={0} statusTone="success" />)
    expect(rootCard(container).getAttribute('data-status-tone')).toBe('success')
  })

  it('maps statusTone="warning" to data-status-tone="warning"', () => {
    const { container } = render(<StatCard {...baseProps} value={0} statusTone="warning" />)
    expect(rootCard(container).getAttribute('data-status-tone')).toBe('warning')
  })

  it('maps statusTone="error" to data-status-tone="error"', () => {
    const { container } = render(<StatCard {...baseProps} value={2} statusTone="error" />)
    expect(rootCard(container).getAttribute('data-status-tone')).toBe('error')
  })

  it('does NOT render the action-required badge in the permission-denied state', () => {
    const { container } = render(
      <StatCard
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
