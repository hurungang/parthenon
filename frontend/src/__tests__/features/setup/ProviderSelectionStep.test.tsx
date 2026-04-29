import { describe, it, expect, vi } from 'vitest'
import { render, fireEvent, screen } from '@testing-library/react'
import { ProviderType } from '../../../types/setup'
import { ProviderSelectionStep } from '../../../features/setup/ProviderSelectionStep'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

describe('ProviderSelectionStep', () => {
  it('renders all provider radio options', () => {
    render(
      <ProviderSelectionStep selectedProvider={ProviderType.KEYCLOAK_BUNDLED} onChange={vi.fn()} />
    )
    expect(screen.getByLabelText('setup.provider.bundledKeycloak')).toBeInTheDocument()
    expect(screen.getByLabelText('setup.provider.externalKeycloak')).toBeInTheDocument()
    expect(screen.getByLabelText('setup.provider.azureEntraId')).toBeInTheDocument()
  })

  it('onChange fires with correct value', () => {
    const onChange = vi.fn()
    render(
      <ProviderSelectionStep selectedProvider={ProviderType.KEYCLOAK_BUNDLED} onChange={onChange} />
    )
    fireEvent.click(screen.getByLabelText('setup.provider.externalKeycloak'))
    expect(onChange).toHaveBeenCalledWith('keycloak_external')
  })
})
