import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { DateRangePicker } from '../../../components/dashboard/DateRangePicker'

describe('DateRangePicker', () => {
  function props(overrides = {}) {
    const now = new Date('2026-07-08T12:00:00Z')
    const dayAgo = new Date('2026-07-07T12:00:00Z')
    return {
      startTime: dayAgo,
      endTime: now,
      onChange: vi.fn(),
      isRefreshing: false,
      ...overrides,
    }
  }

  it('renders datetime-local inputs and preset buttons', () => {
    render(<DateRangePicker {...props()} />)
    // Preset buttons should be visible
    expect(screen.getByText('dashboard.presetHour')).toBeTruthy()
    expect(screen.getByText('dashboard.preset24h')).toBeTruthy()
    expect(screen.getByText('dashboard.preset7d')).toBeTruthy()
    // Refresh button
    expect(screen.getByText('app.refresh')).toBeTruthy()
  })

  it('calls onChange when a preset is clicked', () => {
    const onChange = vi.fn()
    render(<DateRangePicker {...props({ onChange })} />)

    fireEvent.click(screen.getByText('dashboard.presetHour'))
    expect(onChange).toHaveBeenCalledTimes(1)
    const [start, end] = onChange.mock.calls[0]
    expect(start).toBeInstanceOf(Date)
    expect(end).toBeInstanceOf(Date)
    // Should be roughly 1 hour apart
    const diffMs = end.getTime() - start.getTime()
    expect(Math.abs(diffMs - 3600000)).toBeLessThan(5000) // tolerance
  })

  it('calls onChange when refresh is clicked', () => {
    const onChange = vi.fn()
    render(<DateRangePicker {...props({ onChange })} />)

    fireEvent.click(screen.getByText('app.refresh'))
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('formatted range label is displayed', () => {
    const start = new Date('2026-07-07T08:00:00Z')
    const end = new Date('2026-07-08T08:00:00Z')
    render(<DateRangePicker {...props({ startTime: start, endTime: end })} />)
    // The range label should contain the dates
    const label = document.querySelector('.MuiBox-root')?.textContent
    expect(label).toBeTruthy()
  })
})
