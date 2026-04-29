import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CompletionStep } from '../../../features/setup/CompletionStep'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

describe('CompletionStep', () => {
  it('renders success message', () => {
    render(<CompletionStep onGoToLogin={vi.fn()} />)
    expect(screen.getByText('setup.status.success')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'setup.action.goToLogin' })).toBeInTheDocument()
  })

  it('Go to Login button calls onGoToLogin', () => {
    const onGoToLogin = vi.fn()
    render(<CompletionStep onGoToLogin={onGoToLogin} />)
    fireEvent.click(screen.getByRole('button', { name: 'setup.action.goToLogin' }))
    expect(onGoToLogin).toHaveBeenCalled()
  })
})
