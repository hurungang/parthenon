import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'

// Mock i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// Mock MUI icons to avoid EMFILE on Windows
vi.mock('@mui/icons-material', () => ({
  Visibility: () => React.createElement('span', { 'data-testid': 'visibility-icon' }),
  VisibilityOff: () => React.createElement('span', { 'data-testid': 'visibility-off-icon' }),
  ExpandMore: () => React.createElement('span', { 'data-testid': 'expand-more-icon' }),
  ExpandLess: () => React.createElement('span', { 'data-testid': 'expand-less-icon' }),
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
  default: ({ error, fallbackMessage }: { error: unknown; fallbackMessage: string }) =>
    error ? React.createElement('div', { 'data-testid': 'error-alert' }, fallbackMessage) : null,
}))

// Mock OIDCTestConfigModal — must use path relative to test file
vi.mock('../components/system/OIDCTestConfigModal', () => ({
  OIDCTestConfigModal: ({ open, onClose }: { open: boolean; onClose: () => void }) =>
    open ? React.createElement('div', { 'data-testid': 'test-config-modal' },
      React.createElement('button', { 'data-testid': 'close-test-config', onClick: onClose }, 'Close')
    ) : null,
}))

// Mock OIDCTestLoginModal — must use path relative to test file
vi.mock('../components/system/OIDCTestLoginModal', () => ({
  OIDCTestLoginModal: ({ open, onClose }: { open: boolean; onClose: () => void }) =>
    open ? React.createElement('div', { 'data-testid': 'test-login-modal' },
      React.createElement('button', { 'data-testid': 'close-test-login', onClick: onClose }, 'Close')
    ) : null,
}))

import { IdentityProviderConfigForm } from '../components/system/IdentityProviderConfigForm'

describe('IdentityProviderConfigForm', () => {
  const mockOnSave = vi.fn().mockResolvedValue(undefined)

  it('renders provider type selector', () => {
    render(React.createElement(IdentityProviderConfigForm, { scope: 'user', onSave: mockOnSave }))
    // MUI Select renders label text in multiple places; check existence
    const elements = screen.getAllByText('systemConfig.identityProviders.providerType')
    expect(elements.length).toBeGreaterThan(0)
  })

  it('renders user provider heading for user scope', () => {
    render(React.createElement(IdentityProviderConfigForm, { scope: 'user', onSave: mockOnSave }))
    expect(screen.getByText('systemConfig.identityProviders.userProvider')).toBeDefined()
  })

  it('renders agent provider heading for agent scope', () => {
    render(React.createElement(IdentityProviderConfigForm, { scope: 'agent', onSave: mockOnSave }))
    expect(screen.getByText('systemConfig.identityProviders.agentProvider')).toBeDefined()
  })

  it('renders issuer URL text field', () => {
    render(React.createElement(IdentityProviderConfigForm, { scope: 'user', onSave: mockOnSave }))
    expect(screen.getByRole('textbox', { name: /issuerUrl/i })).toBeDefined()
  })

  it('renders client ID text field', () => {
    render(React.createElement(IdentityProviderConfigForm, { scope: 'user', onSave: mockOnSave }))
    expect(screen.getByRole('textbox', { name: /clientId/i })).toBeDefined()
  })

  it('renders client secret text field by label', () => {
    render(React.createElement(IdentityProviderConfigForm, { scope: 'user', onSave: mockOnSave }))
    // Client secret renders as TextField with label
    expect(screen.getByLabelText('systemConfig.identityProviders.clientSecret')).toBeDefined()
  })

  it('shows visibility toggle icon button', () => {
    render(React.createElement(IdentityProviderConfigForm, { scope: 'user', onSave: mockOnSave }))
    expect(screen.getByTestId('visibility-icon')).toBeDefined()
  })

  it('renders scopes text field by label', () => {
    render(React.createElement(IdentityProviderConfigForm, { scope: 'user', onSave: mockOnSave }))
    expect(screen.getByLabelText('systemConfig.identityProviders.scopes')).toBeDefined()
  })

  it('renders claims mapping text field by label', () => {
    render(React.createElement(IdentityProviderConfigForm, { scope: 'user', onSave: mockOnSave }))
    expect(screen.getByLabelText('systemConfig.identityProviders.claimsMapping')).toBeDefined()
  })

  it('renders Save button', () => {
    render(React.createElement(IdentityProviderConfigForm, { scope: 'user', onSave: mockOnSave }))
    expect(screen.getByRole('button', { name: 'systemConfig.identityProviders.save' })).toBeDefined()
  })

  it('renders Test Config button', () => {
    render(React.createElement(IdentityProviderConfigForm, { scope: 'user', onSave: mockOnSave }))
    expect(screen.getByRole('button', { name: 'systemConfig.identityProviders.testConfig' })).toBeDefined()
  })

  it('renders Test Login button', () => {
    render(React.createElement(IdentityProviderConfigForm, { scope: 'user', onSave: mockOnSave }))
    expect(screen.getByRole('button', { name: 'systemConfig.identityProviders.testLogin' })).toBeDefined()
  })

  it('calls onSave with form data when Save is clicked', async () => {
    render(React.createElement(IdentityProviderConfigForm, { scope: 'user', onSave: mockOnSave }))
    const saveBtn = screen.getByRole('button', { name: 'systemConfig.identityProviders.save' })
    fireEvent.click(saveBtn)
    await waitFor(() => {
      expect(mockOnSave).toHaveBeenCalledTimes(1)
    })
    const savedData = mockOnSave.mock.calls[0][0]
    expect(savedData.provider_type).toBe('oidc_generic')
    expect(savedData.client_id).toBe('')
    expect(savedData.scopes).toBe('openid profile email')
    expect(savedData.is_enabled).toBe(true)
  })

  it('shows configured chip when currentConfig is provided', () => {
    render(React.createElement(IdentityProviderConfigForm, {
      scope: 'user',
      onSave: mockOnSave,
      currentConfig: {
        id: '1', provider_scope: 'user', provider_type: 'oidc_generic',
        display_name: 'Test', issuer_url: 'https://example.com', client_id: 'test',
        encrypted_client_secret: 'encrypted', scopes: 'openid', claim_mappings: null,
        ui_client_id: null, public_client_id: null,
        is_enabled: true, created_at: '', updated_at: '',
      },
    }))
    expect(screen.getByText('systemConfig.identityProviders.configured')).toBeDefined()
  })

  it('shows not configured chip when no currentConfig', () => {
    render(React.createElement(IdentityProviderConfigForm, { scope: 'user', onSave: mockOnSave }))
    expect(screen.getByText('systemConfig.identityProviders.notConfigured')).toBeDefined()
  })

  it('disables all fields when disabled prop is true', () => {
    render(React.createElement(IdentityProviderConfigForm, { scope: 'user', onSave: mockOnSave, disabled: true }))
    const saveBtn = screen.getByRole('button', { name: 'systemConfig.identityProviders.save' })
    expect(saveBtn).toHaveProperty('disabled', true)
  })

  it('opens test config modal when Test Config is clicked', async () => {
    render(React.createElement(IdentityProviderConfigForm, {
      scope: 'user',
      onSave: mockOnSave,
      currentConfig: {
        id: '1', provider_scope: 'user', provider_type: 'oidc_generic',
        display_name: '', issuer_url: 'https://example.com', client_id: 'test',
        encrypted_client_secret: null, scopes: 'openid', claim_mappings: null,
        ui_client_id: null, public_client_id: null,
        is_enabled: true, created_at: '', updated_at: '',
      },
    }))
    fireEvent.click(screen.getByRole('button', { name: 'systemConfig.identityProviders.testConfig' }))
    await waitFor(() => {
      expect(screen.getByTestId('test-config-modal')).toBeDefined()
    })
  })

  it('opens test login modal when Test Login is clicked', async () => {
    render(React.createElement(IdentityProviderConfigForm, {
      scope: 'user',
      onSave: mockOnSave,
      currentConfig: {
        id: '1', provider_scope: 'user', provider_type: 'oidc_generic',
        display_name: '', issuer_url: 'https://example.com', client_id: 'test',
        encrypted_client_secret: null, scopes: 'openid', claim_mappings: null,
        ui_client_id: null, public_client_id: null,
        is_enabled: true, created_at: '', updated_at: '',
      },
    }))
    fireEvent.click(screen.getByRole('button', { name: 'systemConfig.identityProviders.testLogin' }))
    await waitFor(() => {
      expect(screen.getByTestId('test-login-modal')).toBeDefined()
    })
  })

  it('has advanced options toggle that expands', async () => {
    render(React.createElement(IdentityProviderConfigForm, { scope: 'user', onSave: mockOnSave }))
    const advancedBtn = screen.getByRole('button', { name: /advancedOptions/ })
    expect(advancedBtn).toBeDefined()
    fireEvent.click(advancedBtn)
    await waitFor(() => {
      expect(screen.getByTestId('expand-less-icon')).toBeDefined()
    })
  })
})
