import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn() }
})

const MOCK_DATA_TYPES = {
  items: [
    {
      id: 'dt-1',
      name: 'Incident Report',
      slug: 'incident-report',
      description: 'Standard incident report schema',
      fields: [
        { name: 'title', type: 'string', required: true },
        { name: 'severity', type: 'enum', enum_values: ['low', 'medium', 'high'], required: true },
      ],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    {
      id: 'dt-2',
      name: 'Metrics Snapshot',
      slug: 'metrics-snapshot',
      description: null,
      fields: [
        { name: 'metric_name', type: 'string', required: true },
        { name: 'value', type: 'number', required: true },
        { name: 'unit', type: 'string', required: false },
      ],
      created_at: '2026-01-02T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
    },
  ],
  total: 2,
  page: 1,
  page_size: 25,
}

const apiClientMock = {
  get: vi.fn().mockImplementation((url: string) => {
    if (url === '/data-types') {
      return Promise.resolve({ data: MOCK_DATA_TYPES })
    }
    return Promise.reject(new Error(`Unexpected URL: ${url}`))
  }),
  post: vi.fn().mockResolvedValue({ data: MOCK_DATA_TYPES.items[0] }),
  put: vi.fn().mockResolvedValue({ data: MOCK_DATA_TYPES.items[0] }),
  delete: vi.fn().mockResolvedValue({ data: {} }),
}

vi.mock('../api/apiClient', () => ({
  default: apiClientMock,
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('DataTypesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the page title', async () => {
    const { DataTypesPage } = await import('../pages/data-types/DataTypesPage')
    render(<DataTypesPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('admin.dataTypes.title')).toBeDefined()
    })
  })

  it('renders data type names from API data', async () => {
    const { DataTypesPage } = await import('../pages/data-types/DataTypesPage')
    render(<DataTypesPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('Incident Report')).toBeDefined()
      expect(screen.getByText('Metrics Snapshot')).toBeDefined()
    })
  })

  it('renders data type slugs', async () => {
    const { DataTypesPage } = await import('../pages/data-types/DataTypesPage')
    render(<DataTypesPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('incident-report')).toBeDefined()
      expect(screen.getByText('metrics-snapshot')).toBeDefined()
    })
  })

  it('renders field counts', async () => {
    const { DataTypesPage } = await import('../pages/data-types/DataTypesPage')
    render(<DataTypesPage />, { wrapper })
    await waitFor(() => {
      // Incident Report has 2 fields
      const fieldCounts = screen.getAllByText('2')
      expect(fieldCounts.length).toBeGreaterThan(0)
    })
  })

  it('renders create button', async () => {
    const { DataTypesPage } = await import('../pages/data-types/DataTypesPage')
    render(<DataTypesPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('admin.dataTypes.create')).toBeDefined()
    })
  })

  it('opens create dialog when create button clicked', async () => {
    const { DataTypesPage } = await import('../pages/data-types/DataTypesPage')
    render(<DataTypesPage />, { wrapper })
    await waitFor(() => {
      fireEvent.click(screen.getByText('admin.dataTypes.create'))
    })
    await waitFor(() => {
      // The dialog should show the "Add Field" button (only appears in the form dialog)
      expect(screen.getByText('admin.dataTypes.addField')).toBeDefined()
    })
  })

  it('opens edit dialog when edit button clicked', async () => {
    const { DataTypesPage } = await import('../pages/data-types/DataTypesPage')
    render(<DataTypesPage />, { wrapper })
    await waitFor(() => {
      const editButtons = screen.getAllByTestId('EditIcon')
      fireEvent.click(editButtons[0])
    })
    await waitFor(() => {
      expect(screen.getByText('admin.dataTypes.edit')).toBeDefined()
    })
  })

  it('opens delete confirmation when delete button clicked', async () => {
    const { DataTypesPage } = await import('../pages/data-types/DataTypesPage')
    render(<DataTypesPage />, { wrapper })
    await waitFor(() => {
      const deleteButtons = screen.getAllByTestId('DeleteIcon')
      fireEvent.click(deleteButtons[0])
    })
    await waitFor(() => {
      expect(screen.getByText('admin.dataTypes.confirmDelete')).toBeDefined()
    })
  })

  it('shows empty state when no data types', async () => {
    apiClientMock.get.mockResolvedValue({
      data: { items: [], total: 0, page: 1, page_size: 25 },
    })
    const { DataTypesPage } = await import('../pages/data-types/DataTypesPage')
    render(<DataTypesPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('app.noData')).toBeDefined()
    })
  })

  it('shows loading spinner while fetching', async () => {
    apiClientMock.get.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve({ data: MOCK_DATA_TYPES }), 500)),
    )
    const { DataTypesPage } = await import('../pages/data-types/DataTypesPage')
    render(<DataTypesPage />, { wrapper })
    await waitFor(() => {
      // Should show loading state
      expect(screen.getByRole('progressbar')).toBeDefined()
    })
  })
})
