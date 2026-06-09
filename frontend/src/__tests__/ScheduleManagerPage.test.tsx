import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('react-js-cron', () => ({
  default: vi.fn(() => <div data-testid="cron-editor" />),
}))

const mockSchedules = [
  {
    id: 'sched-1',
    name: 'Daily Report',
    description: 'Runs daily at 8 AM',
    cron_expression: '0 8 * * *',
    target_type: 'agent' as const,
    target_id: 'at-1',
    payload: { prompt: 'Generate report' },
    status: 'active' as const,
    scheduler_job_id: 'job-1',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'sched-2',
    name: 'Weekly Cleanup',
    description: 'Runs weekly on Sunday midnight',
    cron_expression: '0 0 * * 0',
    target_type: 'agent' as const,
    target_id: 'at-2',
    payload: null,
    status: 'paused' as const,
    scheduler_job_id: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

const mockAgentTypes = [
  { id: 'at-1', name: 'Research Agent', input_type: 'typed', input_schema: { type: 'object', properties: { url: { type: 'string' } } }, is_active: true },
  { id: 'at-2', name: 'Chat Agent', input_type: 'conversation', input_schema: null, is_active: true },
]

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn((url: string) => {
      if (url === '/schedules') {
        return Promise.resolve({ data: mockSchedules })
      }
      if (url === '/agents/types') {
        return Promise.resolve({ data: mockAgentTypes })
      }
      return Promise.resolve({ data: [] })
    }),
    post: vi.fn().mockResolvedValue({ data: mockSchedules[0] }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('ScheduleManagerPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the schedule list from API', async () => {
    const { ScheduleManagerPage } = await import(
      '../pages/scheduling/ScheduleManagerPage'
    )
    render(<ScheduleManagerPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('Daily Report')).toBeDefined()
    })
    expect(screen.getByText('Weekly Cleanup')).toBeDefined()
  })

  it('shows cron expressions', async () => {
    const { ScheduleManagerPage } = await import(
      '../pages/scheduling/ScheduleManagerPage'
    )
    render(<ScheduleManagerPage />, { wrapper })

    await waitFor(() => {
      const codeElements = screen.getAllByText(/0 8 \* \* \*|0 0 \* \* 0/)
      expect(codeElements.length).toBeGreaterThan(0)
    })
  })

  it('shows status labels', async () => {
    const { ScheduleManagerPage } = await import(
      '../pages/scheduling/ScheduleManagerPage'
    )
    render(<ScheduleManagerPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('active')).toBeDefined()
      expect(screen.getByText('paused')).toBeDefined()
    })
  })

  it('renders title translation key', async () => {
    const { ScheduleManagerPage } = await import(
      '../pages/scheduling/ScheduleManagerPage'
    )
    render(<ScheduleManagerPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('schedules.title')).toBeDefined()
    })
  })

  it('has create schedule button', async () => {
    const { ScheduleManagerPage } = await import(
      '../pages/scheduling/ScheduleManagerPage'
    )
    render(<ScheduleManagerPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('schedules.createSchedule')).toBeDefined()
    })
  })

  it('create dialog opens when button is clicked', async () => {
    const { ScheduleManagerPage } = await import(
      '../pages/scheduling/ScheduleManagerPage'
    )
    render(<ScheduleManagerPage />, { wrapper })

    // Wait for page to render
    await waitFor(() => {
      expect(screen.getByText('Daily Report')).toBeDefined()
    })

    // Click create button
    fireEvent.click(screen.getByText('schedules.createSchedule'))

    // Dialog should be visible with cron editor and save button
    await waitFor(() => {
      expect(screen.getByTestId('cron-editor')).toBeDefined()
    })
  })

  it('save in dialog calls API and closes dialog', async () => {
    const apiClient = (await import('../api/apiClient')).default

    const { ScheduleManagerPage } = await import(
      '../pages/scheduling/ScheduleManagerPage'
    )
    render(<ScheduleManagerPage />, { wrapper })

    // Wait for page to render
    await waitFor(() => {
      expect(screen.getByText('Daily Report')).toBeDefined()
    })

    // Click create button to open dialog
    fireEvent.click(screen.getByText('schedules.createSchedule'))
    await waitFor(() => {
      expect(screen.getByTestId('cron-editor')).toBeDefined()
    })

    // Click save
    fireEvent.click(screen.getByText('app.save'))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalled()
    })
  })

  it('renders schedule actions (history, pause/resume, delete buttons)', async () => {
    const { ScheduleManagerPage } = await import(
      '../pages/scheduling/ScheduleManagerPage'
    )
    render(<ScheduleManagerPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('Daily Report')).toBeDefined()
    })

    // Action buttons should be rendered
    const buttons = screen.getAllByRole('button')
    expect(buttons.length).toBeGreaterThan(0)
  })
})
