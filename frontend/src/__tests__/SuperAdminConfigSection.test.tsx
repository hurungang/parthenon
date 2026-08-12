import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SuperAdminConfigSection } from '../components/system/SuperAdminConfigSection'

// Mock i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// Mock useDialogErrorHandler
vi.mock('../../hooks/useDialogErrorHandler', () => ({
  useDialogErrorHandler: () => ({
    dialogError: null,
    setDialogError: vi.fn(),
    clearDialogError: vi.fn(),
  }),
}))

// Mock PermissionDeniedAlert
vi.mock('../permissions/PermissionDeniedAlert', () => ({
  default: ({ error }: { error: unknown }) =>
    error ? React.createElement('div', { 'data-testid': 'error-alert' }, 'Error') : null,
}))

// Mock apiClient with default export (global mock lacks default export)
vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: null }),
    post: vi.fn().mockResolvedValue({ data: null }),
    put: vi.fn().mockResolvedValue({ data: null }),
    patch: vi.fn().mockResolvedValue({ data: null }),
    delete: vi.fn().mockResolvedValue({ data: null }),
  },
}))

// Mock systemConfigApi
const mockToggleSuperAdmin = vi.fn()
const mockUpdatePassword = vi.fn()
vi.mock('../../api/systemConfigApi', () => ({
  toggleSuperAdmin: (...args: any[]) => mockToggleSuperAdmin(...args),
  updateSuperAdminPassword: (...args: any[]) => mockUpdatePassword(...args),
}))

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return React.createElement(QueryClientProvider, { client: qc }, children)
}

describe('SuperAdminConfigSection', () => {

  beforeEach(() => {
    vi.clearAllMocks()
    mockToggleSuperAdmin.mockResolvedValue({ is_enabled: true, username: 'admin', last_login_at: null })
    mockUpdatePassword.mockResolvedValue({ is_enabled: true, username: 'admin', last_login_at: null })
  })

  const enabledStatus = {
    is_enabled: true,
    username: 'admin',
    last_login_at: '2025-01-15T10:00:00Z',
    env_controlled: false,
  }

  const disabledStatus = {
    is_enabled: false,
    username: 'admin',
    last_login_at: null,
    env_controlled: false,
  }

  it('renders the title', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: enabledStatus,
    }), { wrapper: Wrapper })
    expect(screen.getByText('systemConfig.superAdmin.title')).toBeDefined()
  })

  it('shows enabled label when enabled', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: enabledStatus,
    }), { wrapper: Wrapper })
    expect(screen.getByText('systemConfig.superAdmin.enabled')).toBeDefined()
  })

  it('shows disabled label when disabled', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: disabledStatus,
    }), { wrapper: Wrapper })
    expect(screen.getByText('systemConfig.superAdmin.disabled')).toBeDefined()
  })

  it('shows username in status', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: enabledStatus,
    }), { wrapper: Wrapper })
    expect(screen.getByText('admin')).toBeDefined()
  })

  it('shows last login timestamp content', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: enabledStatus,
    }), { wrapper: Wrapper })
    // The text is rendered as "systemConfig.superAdmin.lastLogin: <date>"
    // Use a regex partial match
    const el = screen.getByText(/systemConfig\.superAdmin\.lastLogin/)
    expect(el).toBeDefined()
  })

  it('shows never when no last login', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: { ...enabledStatus, last_login_at: null },
    }), { wrapper: Wrapper })
    expect(screen.getByText('systemConfig.superAdmin.never')).toBeDefined()
  })

  it('shows info alert when enabled', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: enabledStatus,
    }), { wrapper: Wrapper })
    expect(screen.getByText('systemConfig.superAdmin.enableDescription')).toBeDefined()
  })

  it('shows warning alert when disabled', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: disabledStatus,
    }), { wrapper: Wrapper })
    expect(screen.getByText('systemConfig.superAdmin.disableDescription')).toBeDefined()
  })

  it('renders password change button', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: enabledStatus,
    }), { wrapper: Wrapper })
    expect(screen.getByText('systemConfig.superAdmin.passwordChange')).toBeDefined()
  })

  it('disables password change button when super admin is disabled', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: disabledStatus,
    }), { wrapper: Wrapper })
    const passBtn = screen.getByText('systemConfig.superAdmin.passwordChange')
    expect(passBtn.closest('button')).toHaveProperty('disabled', true)
  })

  it('opens disable confirmation modal when toggling off', async () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: enabledStatus,
    }), { wrapper: Wrapper })

    // MUI Switch renders with role="checkbox" inside a label
    // The label contains the enabled/disabled text
    const toggleLabel = screen.getByText('systemConfig.superAdmin.enabled')
    fireEvent.click(toggleLabel)

    await waitFor(() => {
      expect(screen.getByText('systemConfig.superAdmin.disableWarningTitle')).toBeDefined()
    })
    expect(screen.getByText('systemConfig.superAdmin.disableWarningBody')).toBeDefined()
  })

  it('shows guard rail modal when disabling without OIDC provider', async () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: enabledStatus,
    }), { wrapper: Wrapper })

    const toggleLabel = screen.getByText('systemConfig.superAdmin.enabled')
    fireEvent.click(toggleLabel)

    await waitFor(() => {
      expect(screen.getByText('systemConfig.superAdmin.guardRailTitle')).toBeDefined()
    })
    expect(screen.getByText('systemConfig.superAdmin.disableGuardRail')).toBeDefined()
  })

  it('opens password change dialog', async () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: enabledStatus,
    }), { wrapper: Wrapper })
    const passBtn = screen.getByText('systemConfig.superAdmin.passwordChange')
    fireEvent.click(passBtn)
    await waitFor(() => {
      // Labels appear in dialog; use getAllByText and check for at least one
      const labels = screen.getAllByText('systemConfig.superAdmin.currentPassword')
      expect(labels.length).toBeGreaterThan(0)
    })
  })

  it('can open and close the disable confirmation modal', async () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: enabledStatus,
    }), { wrapper: Wrapper })

    // Click the label text to toggle switch and open the modal
    const switchLabel = screen.getByText('systemConfig.superAdmin.enabled')
    fireEvent.click(switchLabel)

    await waitFor(() => {
      expect(screen.getByText('systemConfig.superAdmin.disableWarningTitle')).toBeDefined()
    })

    // Close the modal using cancel button
    const cancelBtn = screen.getByText('app.cancel')
    fireEvent.click(cancelBtn)

    // Modal should close
    await waitFor(() => {
      expect(screen.queryByText('systemConfig.superAdmin.disableWarningTitle')).toBeNull()
    })
  })
})
