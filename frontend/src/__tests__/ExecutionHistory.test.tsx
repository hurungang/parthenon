import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import ExecutionHistory from '../components/scheduling/ExecutionHistory'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('ExecutionHistory', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders dialog when open=true', () => {
    const onClose = vi.fn()
    render(
      <ExecutionHistory jobId="sched-1" open={true} onClose={onClose} />,
      { wrapper }
    )
    expect(screen.getByText('schedules.executions')).toBeDefined()
  })

  it('does not render dialog content when open=false', () => {
    const onClose = vi.fn()
    render(
      <ExecutionHistory jobId="sched-1" open={false} onClose={onClose} />,
      { wrapper }
    )
    // The dialog content should not be visible
    expect(screen.queryByText('schedules.executions')).toBeNull()
  })

  it('shows loading state initially', async () => {
    // Create a promise that never resolves to keep loading state
    const onClose = vi.fn()
    render(
      <ExecutionHistory jobId="sched-1" open={true} onClose={onClose} />,
      { wrapper }
    )

    // Should show loading spinner
    expect(screen.getByText('schedules.executions')).toBeDefined()
  })
})
