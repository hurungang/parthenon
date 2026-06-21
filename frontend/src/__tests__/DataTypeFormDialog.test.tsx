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

const apiClientMock = {
  get: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }),
  post: vi.fn().mockResolvedValue({ data: { id: 'new-dt', name: 'Test Type' } }),
  put: vi.fn().mockResolvedValue({ data: { id: 'dt-1', name: 'Updated Type' } }),
  delete: vi.fn().mockResolvedValue({ data: {} }),
}

vi.mock('../api/apiClient', () => ({
  default: apiClientMock,
}))

const MOCK_DATA_TYPE = {
  id: 'dt-1',
  name: 'Incident Report',
  slug: 'incident-report',
  description: 'Standard incident report schema',
  fields: [
    { name: 'title', type: 'string' as const, required: true },
    { name: 'severity', type: 'enum' as const, enum_values: ['low', 'medium', 'high'], required: true },
  ],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('DataTypeFormDialog', () => {
  const onClose = vi.fn()
  const onSaved = vi.fn().mockResolvedValue(undefined)

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders create mode with empty fields', async () => {
    const { DataTypeFormDialog } = await import('../pages/data-types/DataTypeFormDialog')
    render(
      <DataTypeFormDialog open={true} editDataType={null} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )
    await waitFor(() => {
      expect(screen.getByText('admin.dataTypes.create')).toBeDefined()
      expect(screen.getByText('admin.dataTypes.addField')).toBeDefined()
    })
  })

  it('renders edit mode with pre-populated data', async () => {
    const { DataTypeFormDialog } = await import('../pages/data-types/DataTypeFormDialog')
    render(
      <DataTypeFormDialog open={true} editDataType={MOCK_DATA_TYPE} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )
    await waitFor(() => {
      expect(screen.getByText('admin.dataTypes.edit')).toBeDefined()
      // Use getByDisplayValue to find pre-populated fields
      expect(screen.getByDisplayValue('Incident Report')).toBeDefined()
      expect(screen.getByDisplayValue('incident-report')).toBeDefined()
    })
  })

  it('adds a new field when Add Field is clicked', async () => {
    const { DataTypeFormDialog } = await import('../pages/data-types/DataTypeFormDialog')
    render(
      <DataTypeFormDialog open={true} editDataType={null} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )
    await waitFor(() => {
      // Initially there is one field row (the default empty field)
      fireEvent.click(screen.getByText('admin.dataTypes.addField'))
    })
    // After clicking add, there should be more field name inputs
    const fieldNameInputs = screen.getAllByLabelText('admin.dataTypes.fieldName')
    expect(fieldNameInputs.length).toBeGreaterThanOrEqual(2)
  })

  it('removes a field when remove button is clicked', async () => {
    const { DataTypeFormDialog } = await import('../pages/data-types/DataTypeFormDialog')
    render(
      <DataTypeFormDialog open={true} editDataType={MOCK_DATA_TYPE} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )
    await waitFor(() => {
      // There should be 2 field rows initially from MOCK_DATA_TYPE
      const removeButtons = screen.getAllByTestId('DeleteIcon')
      fireEvent.click(removeButtons[0])
    })
    // After removing one, only 1 field row should remain
    const fieldNameInputs = screen.getAllByLabelText('admin.dataTypes.fieldName')
    expect(fieldNameInputs.length).toBe(1)
  })

  it('calls onClose when cancel is clicked', async () => {
    const { DataTypeFormDialog } = await import('../pages/data-types/DataTypeFormDialog')
    render(
      <DataTypeFormDialog open={true} editDataType={null} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )
    await waitFor(() => {
      fireEvent.click(screen.getByText('app.cancel'))
    })
    expect(onClose).toHaveBeenCalled()
  })

  it('calls onClose when dialog is closed after successful save', async () => {
    apiClientMock.post.mockResolvedValue({ data: { id: 'new-dt', name: 'Test Type' } })
    const { DataTypeFormDialog } = await import('../pages/data-types/DataTypeFormDialog')
    render(
      <DataTypeFormDialog open={true} editDataType={null} onClose={onClose} onSaved={onSaved} />,
      { wrapper },
    )
    await waitFor(() => {
      // Fill in the name field using getByRole to find the text input
      const nameInputs = screen.getAllByRole('textbox')
      const nameField = nameInputs[0]
      fireEvent.change(nameField, { target: { value: 'Test Data Type' } })
    })
    await waitFor(() => {
      const slugInputs = screen.getAllByRole('textbox')
      const slugField = slugInputs[1]
      fireEvent.change(slugField, { target: { value: 'test-data-type' } })
    })
    await waitFor(() => {
      fireEvent.click(screen.getByText('app.save'))
    })
    await waitFor(() => {
      expect(onClose).toHaveBeenCalled()
    })
  })
})
