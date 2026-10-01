/**
 * TenantPicker — organization chooser for multi-organization users (CS-24).
 *
 * - Renders the picker for the provided memberships (multi-org users)
 * - Selecting the CURRENT tenant continues into the workspace
 * - Selecting ANOTHER organization triggers onSelect (fresh sign-in)
 * - Loading and error states render
 * - Default-org chip and role labels render via i18n keys
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

import { TenantPicker } from '../components/auth/TenantPicker'

const memberships = [
  {
    tenant_id: 't-1',
    tenant_slug: 'acme',
    tenant_name: 'Acme Corp',
    tenant_role: 'member' as const,
    is_default: true,
  },
  {
    tenant_id: 't-2',
    tenant_slug: 'globex',
    tenant_name: 'Globex',
    tenant_role: 'tenant_admin' as const,
    is_default: false,
  },
]

function renderPicker(overrides: Record<string, unknown> = {}) {
  const onSelect = vi.fn()
  const onContinue = vi.fn()
  const props = {
    open: true,
    memberships,
    currentTenantSlug: null,
    onSelect,
    onContinue,
    ...overrides,
  }
  render(<TenantPicker {...props} />)
  return { onSelect, onContinue }
}

describe('TenantPicker', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders all memberships', () => {
    renderPicker()
    expect(screen.getByText('Acme Corp')).toBeDefined()
    expect(screen.getByText('Globex')).toBeDefined()
    expect(screen.getByTestId('tenant-picker')).toBeDefined()
  })

  it('shows the picker title and subtitle via i18n keys', () => {
    renderPicker()
    expect(screen.getByText('auth.tenantPicker.title')).toBeDefined()
    expect(screen.getByText('auth.tenantPicker.subtitle')).toBeDefined()
  })

  it('selecting the current tenant continues into the workspace', () => {
    const { onSelect, onContinue } = renderPicker({ currentTenantSlug: 'acme' })
    fireEvent.click(screen.getByText('Acme Corp'))
    expect(onContinue).toHaveBeenCalledTimes(1)
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('selecting another organization triggers a fresh sign-in (onSelect)', () => {
    const { onSelect, onContinue } = renderPicker({ currentTenantSlug: 'acme' })
    fireEvent.click(screen.getByText('Globex'))
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect.mock.calls[0][0].tenant_slug).toBe('globex')
    expect(onContinue).not.toHaveBeenCalled()
  })

  it('shows the default chip on the default membership', () => {
    renderPicker()
    expect(screen.getByText('auth.tenantPicker.default')).toBeDefined()
  })

  it('renders role labels via static i18n keys', () => {
    renderPicker()
    expect(screen.getByText('auth.tenantPicker.role.member')).toBeDefined()
    expect(screen.getByText('auth.tenantPicker.role.tenant_admin')).toBeDefined()
  })

  it('renders loading state instead of the list', () => {
    renderPicker({ loading: true })
    expect(screen.queryByText('Acme Corp')).toBeNull()
  })

  it('renders an error alert when provided', () => {
    renderPicker({ error: 'selection failed' })
    expect(screen.getByText('selection failed')).toBeDefined()
  })

  it('shows signed-in-as caption when a current tenant exists', () => {
    renderPicker({ currentTenantSlug: 'acme' })
    expect(
      screen.getByText('auth.tenantPicker.signedInAs', { exact: false })
    ).toBeDefined()
  })

  it('picker can be closed via open=false (renders nothing)', () => {
    render(<TenantPicker open={false} memberships={memberships} currentTenantSlug={null} onSelect={vi.fn()} onContinue={vi.fn()} />)
    expect(screen.queryByTestId('tenant-picker')).toBeNull()
  })
})
