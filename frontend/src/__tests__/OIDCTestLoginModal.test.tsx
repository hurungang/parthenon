import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'

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

// Mock systemConfigApi
const mockInitiateTestLogin = vi.fn()
const mockGetTestLoginStatus = vi.fn()
vi.mock('../../api/systemConfigApi', () => ({
  initiateTestLogin: (...args: any[]) => mockInitiateTestLogin(...args),
  getTestLoginStatus: (...args: any[]) => mockGetTestLoginStatus(...args),
}))

import { OIDCTestLoginModal } from '../components/system/OIDCTestLoginModal'

describe('OIDCTestLoginModal', () => {
  const mockOnClose = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    mockInitiateTestLogin.mockResolvedValue({
      test_id: 'test-123',
      redirect_url: 'https://example.com/auth',
      status: 'initiated',
    })
    mockGetTestLoginStatus.mockResolvedValue({
      status: 'completed',
      claims: { sub: 'user1', email: 'user@example.com' },
    })
  })

  it('does not render when open is false', () => {
    render(React.createElement(OIDCTestLoginModal, {
      open: false, onClose: mockOnClose,
      issuerUrl: 'https://example.com', clientId: 'test-client',
    }))
    expect(screen.queryByText('systemConfig.oidcTest.testLoginTitle')).toBeNull()
  })

  it('renders when open is true', () => {
    render(React.createElement(OIDCTestLoginModal, {
      open: true, onClose: mockOnClose,
      issuerUrl: 'https://example.com', clientId: 'test-client',
    }))
    expect(screen.getByText('systemConfig.oidcTest.testLoginTitle')).toBeDefined()
  })

  it('shows pre-test state with warning', () => {
    render(React.createElement(OIDCTestLoginModal, {
      open: true, onClose: mockOnClose,
      issuerUrl: 'https://example.com', clientId: 'test-client',
    }))
    expect(screen.getByText('systemConfig.oidcTest.testLoginWarning')).toBeDefined()
  })

  it('shows issuer URL in pre-test state', () => {
    render(React.createElement(OIDCTestLoginModal, {
      open: true, onClose: mockOnClose,
      issuerUrl: 'https://example.com', clientId: 'test-client',
    }))
    expect(screen.getByText('https://example.com')).toBeDefined()
  })

  it('shows client ID in pre-test state', () => {
    render(React.createElement(OIDCTestLoginModal, {
      open: true, onClose: mockOnClose,
      issuerUrl: 'https://example.com', clientId: 'test-client',
    }))
    expect(screen.getByText('test-client')).toBeDefined()
  })

  it('has Initiate Test Login button in pre-test state', () => {
    render(React.createElement(OIDCTestLoginModal, {
      open: true, onClose: mockOnClose,
      issuerUrl: 'https://example.com', clientId: 'test-client',
    }))
    expect(screen.getByText('systemConfig.oidcTest.initiateLogin')).toBeDefined()
  })

  it('closes when close button is clicked', async () => {
    render(React.createElement(OIDCTestLoginModal, {
      open: true, onClose: mockOnClose,
      issuerUrl: 'https://example.com', clientId: 'test-client',
    }))
    const closeBtn = screen.getByText('app.close')
    fireEvent.click(closeBtn)
    expect(mockOnClose).toHaveBeenCalledTimes(1)
  })

  it('shows testing state when Initiate is clicked', async () => {
    // Don't resolve immediately so we can check the loading state
    mockInitiateTestLogin.mockImplementation(() => new Promise(() => { /* never resolves */ }))
    render(React.createElement(OIDCTestLoginModal, {
      open: true, onClose: mockOnClose,
      issuerUrl: 'https://example.com', clientId: 'test-client',
    }))
    const initiateBtn = screen.getByText('systemConfig.oidcTest.initiateLogin')
    fireEvent.click(initiateBtn)
    await waitFor(() => {
      expect(screen.getByText('systemConfig.oidcTest.testing')).toBeDefined()
    })
  })
})
