import { describe, it, expect, vi } from 'vitest'
import { render, fireEvent, screen } from '@testing-library/react'
import { ExternalOidcConfigStep } from '../../../features/setup/ExternalOidcConfigStep'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

const OIDC_PLACEHOLDER =
  'https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration'

describe('ExternalOidcConfigStep', () => {
  it('renders all fields', () => {
    render(<ExternalOidcConfigStep formData={{}} onChange={vi.fn()} />)
    expect(screen.getByPlaceholderText(OIDC_PLACEHOLDER)).toBeDefined()
    expect(screen.getByPlaceholderText('your-client-id')).toBeDefined()
    // 2 text inputs + 1 password
    expect(screen.getAllByRole('textbox').length).toBeGreaterThanOrEqual(2)
  })

  it('onChange fires on oidcDiscoveryUrl input', () => {
    const onChange = vi.fn()
    render(<ExternalOidcConfigStep formData={{}} onChange={onChange} />)
    fireEvent.change(screen.getByPlaceholderText(OIDC_PLACEHOLDER), {
      target: { value: 'https://oidc.example.com' },
    })
    expect(onChange).toHaveBeenCalledWith({ oidc_discovery_url: 'https://oidc.example.com' })
  })

  it('onChange fires on clientId input', () => {
    const onChange = vi.fn()
    render(<ExternalOidcConfigStep formData={{}} onChange={onChange} />)
    fireEvent.change(screen.getByPlaceholderText('your-client-id'), {
      target: { value: 'my-app' },
    })
    expect(onChange).toHaveBeenCalledWith({ client_id: 'my-app' })
  })
})
