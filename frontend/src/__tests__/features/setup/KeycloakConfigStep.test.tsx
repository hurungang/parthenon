import { describe, it, expect, vi } from 'vitest'
import { render, fireEvent, screen } from '@testing-library/react'
import { KeycloakConfigStep } from '../../../features/setup/KeycloakConfigStep'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

describe('KeycloakConfigStep', () => {
  it('renders all fields', () => {
    render(<KeycloakConfigStep formData={{}} onChange={vi.fn()} />)
    // 4 text inputs + 2 password inputs
    expect(screen.getAllByRole('textbox').length).toBeGreaterThanOrEqual(4)
    expect(screen.getByPlaceholderText('http://localhost:8080')).toBeDefined()
    expect(screen.getByPlaceholderText('parthenon')).toBeDefined()
    expect(screen.getByPlaceholderText('parthenon-api')).toBeDefined()
    expect(screen.getByPlaceholderText('admin')).toBeDefined()
  })

  it('onChange fires on keycloakUrl input', () => {
    const onChange = vi.fn()
    render(<KeycloakConfigStep formData={{}} onChange={onChange} />)
    fireEvent.change(screen.getByPlaceholderText('http://localhost:8080'), {
      target: { value: 'http://test' },
    })
    expect(onChange).toHaveBeenCalledWith({ keycloak_url: 'http://test' })
  })

  it('onChange fires on realm input', () => {
    const onChange = vi.fn()
    render(<KeycloakConfigStep formData={{}} onChange={onChange} />)
    fireEvent.change(screen.getByPlaceholderText('parthenon'), {
      target: { value: 'myrealm' },
    })
    expect(onChange).toHaveBeenCalledWith({ realm_name: 'myrealm' })
  })
})
