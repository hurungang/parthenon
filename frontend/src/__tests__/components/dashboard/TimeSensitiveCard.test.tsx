import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { TimeSensitiveCard } from '../../../components/dashboard/TimeSensitiveCard'
import type { ReactNode } from 'react'

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
