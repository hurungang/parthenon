import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { VerificationStep } from '../../../features/setup/VerificationStep'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

describe('VerificationStep', () => {
  it('shows spinner when isLoading=true', () => {
    render(<VerificationStep isLoading={true} result={null} error={null} />)
    expect(screen.getByText('setup.status.configuring')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toBeInTheDocument()
  })

  it('shows error when error prop is set', () => {
    render(<VerificationStep isLoading={false} result={null} error={'fail'} />)
    expect(screen.getByText('setup.status.error')).toBeInTheDocument()
    expect(screen.getByText('fail')).toBeInTheDocument()
  })

  it('shows error when result.success=false', () => {
    render(<VerificationStep isLoading={false} result={{ success: false, provider_type: '', oidc_provider_url: null, realm_name: null, client_id: null, error_code: 'err', detail: 'bad' }} error={null} />)
    expect(screen.getByText('setup.status.error')).toBeInTheDocument()
    expect(screen.getByText('bad')).toBeInTheDocument()
  })

  it('renders nothing when not loading and result.success=true', () => {
    render(<VerificationStep isLoading={false} result={{ success: true, provider_type: '', oidc_provider_url: null, realm_name: null, client_id: null, error_code: null, detail: null }} error={null} />)
    expect(screen.queryByText('setup.status.error')).not.toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })
})
