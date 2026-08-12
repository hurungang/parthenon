import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatCard } from '../../../components/dashboard/StatCard'
import type { ReactNode } from 'react'

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
