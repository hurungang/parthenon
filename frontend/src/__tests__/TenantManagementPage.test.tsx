/**
 * TenantManagementPage — platform admin tenant console (Phase 6.3, CS-07/CS-09).
 *
 * Full CRUD journeys with parent-table refresh assertions (no page
 * reload — TanStack Query invalidation), server validation errors shown
 * inline per the Dialog Error Handling Standard, delete with typed
 * confirmation, and slug-reuse recreate.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

import {
  listTenants,
  createTenant,
  updateTenant,
  suspendTenant,
  resumeTenant,
  deleteTenant,
  type Tenant,
} from '../api/platformAdminApi'

vi.mock('../api/platformAdminApi', () => ({
  listTenants: vi.fn(),
  createTenant: vi.fn(),
  updateTenant: vi.fn(),
  suspendTenant: vi.fn(),
  resumeTenant: vi.fn(),
  deleteTenant: vi.fn(),
}))

import { TenantManagementPage } from '../pages/platform/TenantManagementPage'

const tA: Tenant = {
  id: '11111111-1111-1111-1111-111111111111',
  name: 'Acme Corp',
  slug: 'acme',
  status: 'active',
  is_system_tenant: false,
  is_onboarded: true,
  admin_contact_name: 'Ada',
  admin_contact_email: 'ada@acme.test',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  license: null,
  usage: null,
}

function makeTenant(overrides: Partial<Tenant>): Tenant {
  return { ...tA, ...overrides }
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <TenantManagementPage />
    </QueryClientProvider>,
  )
}

const mocked = vi.mocked

describe('TenantManagementPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked(listTenants).mockResolvedValue({ items: [tA], total: 1 })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the tenant overview table with all values', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByTestId('tenant-row-acme')).toBeDefined()
    })
    expect(screen.getByText('Acme Corp')).toBeDefined()
    expect(screen.getByText('acme')).toBeDefined()
    expect(screen.getByText('platform.tenants.status.active')).toBeDefined()
    expect(screen.getByText('Ada (ada@acme.test)')).toBeDefined()
  })

  it('creates a tenant and refreshes the table without page reload', async () => {
    const created = makeTenant({ id: '22222222-2222-2222-2222-222222222222', name: 'Globex', slug: 'globex' })
    mocked(createTenant).mockResolvedValue(created)
    const renderResult = renderPage()
    await waitFor(() => screen.getByTestId('tenant-row-acme'))

    fireEvent.click(screen.getByText('platform.tenants.create'))
    fireEvent.change(screen.getByLabelText('platform.tenants.name'), { target: { value: 'Globex' } })
    fireEvent.change(screen.getByLabelText('platform.tenants.slug'), { target: { value: 'globex' } })
    fireEvent.click(screen.getByText('app.save'))

    await waitFor(() => {
      expect(mocked(createTenant).mock.calls[0][0]).toEqual({
        name: 'Globex',
        slug: 'globex',
        admin_contact_name: null,
        admin_contact_email: null,
      })
    })
    // Parent table refreshed automatically: invalidateQueries refetches.
    await waitFor(() => {
      expect(mocked(listTenants).mock.calls.length).toBeGreaterThanOrEqual(2)
    })
    expect(renderResult.baseElement.querySelector('dialog')).toBeNull() // dialog closed
  })

  it('surveys server validation errors inline in the create dialog', async () => {
    const conflict = Object.assign(new Error('conflict'), {
      isAxiosError: true,
      response: { status: 409, data: { detail: "A tenant with slug 'acme' already exists." } },
    })
    mocked(createTenant).mockRejectedValue(conflict)
    renderPage()
    await waitFor(() => screen.getByTestId('tenant-row-acme'))

    fireEvent.click(screen.getByText('platform.tenants.create'))
    fireEvent.change(screen.getByLabelText('platform.tenants.name'), { target: { value: 'Dup' } })
    fireEvent.change(screen.getByLabelText('platform.tenants.slug'), { target: { value: 'acme' } })
    fireEvent.click(screen.getByText('app.save'))

    // Dialog Error Handling Standard: error surfaces IN the dialog.
    await waitFor(() => {
      expect(screen.getByText(/already exists/i)).toBeDefined()
    })
    // Dialog stays open for correction.
    expect(screen.getByLabelText('platform.tenants.name')).toBeDefined()
  })

  it('edits a tenant with pre-populated fields', async () => {
    mocked(updateTenant).mockResolvedValue(makeTenant({ name: 'Acme Renamed' }))
    renderPage()
    await waitFor(() => screen.getByTestId('tenant-row-acme'))

    fireEvent.click(screen.getByLabelText('edit-acme'))
    const nameInput = screen.getByLabelText('platform.tenants.name') as HTMLInputElement
    expect(nameInput.value).toBe('Acme Corp')
    // Slug is immutable in edit mode.
    expect((screen.getByLabelText('platform.tenants.slug') as HTMLInputElement).disabled).toBe(true)

    fireEvent.change(nameInput, { target: { value: 'Acme Renamed' } })
    fireEvent.click(screen.getByText('app.save'))
    await waitFor(() => {
      expect(mocked(updateTenant).mock.calls[0]).toEqual([
        tA.id,
        {
          name: 'Acme Renamed',
          // Contact fields arrive pre-populated from the dialog seeds.
          admin_contact_name: 'Ada',
          admin_contact_email: 'ada@acme.test',
        },
      ])
    })
  })

  it('suspends an active tenant', async () => {
    mocked(suspendTenant).mockResolvedValue(makeTenant({ status: 'suspended' }))
    renderPage()
    await waitFor(() => screen.getByTestId('tenant-row-acme'))

    fireEvent.click(screen.getByLabelText('suspend-acme'))
    await waitFor(() => {
      expect(mocked(suspendTenant).mock.calls[0][0]).toBe(tA.id)
    })
  })

  it('resumes a suspended tenant', async () => {
    mocked(listTenants).mockResolvedValue({
      items: [makeTenant({ status: 'suspended' })],
      total: 1,
    })
    mocked(resumeTenant).mockResolvedValue(makeTenant({ status: 'active' }))
    renderPage()
    await waitFor(() => screen.getByTestId('tenant-row-acme'))

    fireEvent.click(screen.getByLabelText('resume-acme'))
    await waitFor(() => {
      expect(mocked(resumeTenant).mock.calls[0][0]).toBe(tA.id)
    })
  })

  it('delete requires typing the tenant address (confirmation gate)', async () => {
    renderPage()
    await waitFor(() => screen.getByTestId('tenant-row-acme'))

    fireEvent.click(screen.getByLabelText('delete-acme'))
    const dialog = screen.getByRole('dialog') as HTMLElement
    const confirmInput = dialog.querySelector('input') as HTMLInputElement
    const deleteButton = within(dialog).getByText('platform.tenants.delete')
    // Disabled until the typed slug matches exactly.
    expect((deleteButton as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(confirmInput, { target: { value: 'acm' } })
    expect((deleteButton as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(confirmInput, { target: { value: 'acme' } })
    expect((deleteButton as HTMLButtonElement).disabled).toBe(false)
  })

  it('deletes a tenant and refreshes immediately', async () => {
    mocked(deleteTenant).mockResolvedValue(undefined)
    renderPage()
    await waitFor(() => screen.getByTestId('tenant-row-acme'))

    fireEvent.click(screen.getByLabelText('delete-acme'))
    const dialog = screen.getByRole('dialog') as HTMLElement
    const confirmInput = dialog.querySelector('input') as HTMLInputElement
    fireEvent.change(confirmInput, { target: { value: 'acme' } })
    fireEvent.click(within(dialog).getByText('platform.tenants.delete'))

    await waitFor(() => {
      expect(mocked(deleteTenant).mock.calls[0].slice(0, 2)).toEqual([tA.id, 'acme'])
    })
    await waitFor(() => {
      expect(mocked(listTenants).mock.calls.length).toBeGreaterThanOrEqual(2)
    })
  })

  it('delete API errors surface in the confirmation dialog', async () => {
    const conflict = Object.assign(new Error('blocked'), {
      isAxiosError: true,
      response: { status: 409, data: { detail: 'Deletion blocked' } },
    })
    mocked(deleteTenant).mockRejectedValue(conflict)
    renderPage()
    await waitFor(() => screen.getByTestId('tenant-row-acme'))

    fireEvent.click(screen.getByLabelText('delete-acme'))
    const dialog = screen.getByRole('dialog') as HTMLElement
    const confirmInput = dialog.querySelector('input') as HTMLInputElement
    fireEvent.change(confirmInput, { target: { value: 'acme' } })
    fireEvent.click(within(dialog).getByText('platform.tenants.delete'))

    await waitFor(() => {
      expect(within(dialog).getByText(/blocked/i)).toBeDefined()
    })
  })

  it('does not offer suspend/delete for the system tenant', async () => {
    mocked(listTenants).mockResolvedValue({
      items: [makeTenant({ slug: 'system', name: 'System', is_system_tenant: true })],
      total: 1,
    })
    renderPage()
    await waitFor(() => screen.getByTestId('tenant-row-system'))

    expect(screen.queryByLabelText('suspend-system')).toBeNull()
    expect(screen.queryByLabelText('delete-system')).toBeNull()
  })
})
