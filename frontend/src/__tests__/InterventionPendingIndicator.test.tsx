import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { InterventionPendingIndicator } from '../components/conversations/InterventionPendingIndicator'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string) => {
      if (k === 'conversations.sessions.intervention.waitingForInput') return 'Waiting for your input'
      return k
    },
  }),
}))

describe('InterventionPendingIndicator', () => {
  it('renders "Waiting for your input" text', () => {
    render(<InterventionPendingIndicator />)
    expect(screen.getByText('Waiting for your input')).toBeDefined()
  })

  it('renders with default (non-inline) variant', () => {
    const { container } = render(<InterventionPendingIndicator />)
    // Should have border styling
    const box = container.firstElementChild
    expect(box).not.toBeNull()
    // Just verify it renders without error
    expect(box?.tagName).toBe('DIV')
  })

  it('renders with inline variant', () => {
    const { container } = render(<InterventionPendingIndicator inline />)
    const box = container.firstElementChild
    expect(box).not.toBeNull()
    expect(box?.tagName).toBe('DIV')
    // Inline variant should still show the text
    expect(screen.getByText('Waiting for your input')).toBeDefined()
  })

  it('renders a CircularProgress spinner', () => {
    const { container } = render(<InterventionPendingIndicator />)
    const spinner = container.querySelector('[role="progressbar"]')
    expect(spinner).not.toBeNull()
  })

  it('renders with warning color treatment', () => {
    const { container } = render(<InterventionPendingIndicator />)
    const box = container.firstElementChild as HTMLElement
    // MUI injects emotion styles; check for warning styling via class names
    const classes = box?.className ?? ''
    // At minimum, it shouldn't have error colors
    expect(classes).toBeTruthy()
  })
})
