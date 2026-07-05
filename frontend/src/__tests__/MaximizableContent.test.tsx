import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MaximizableContent } from '../components/MaximizableContent'

describe('MaximizableContent', () => {
  it('renders children inline', () => {
    render(
      <MaximizableContent>
        <p>Test content</p>
      </MaximizableContent>,
    )
    expect(screen.getByText('Test content')).toBeDefined()
  })

  it('renders the maximize button', () => {
    render(
      <MaximizableContent>
        <p>Content</p>
      </MaximizableContent>,
    )
    const button = screen.getByRole('button')
    expect(button).toBeDefined()
  })

  it('has accessible label on maximize button', () => {
    render(
      <MaximizableContent title="Agent Output">
        <p>Content</p>
      </MaximizableContent>,
    )
    const button = screen.getByLabelText('Maximize: Agent Output')
    expect(button).toBeDefined()
  })

  it('uses generic label when no title provided', () => {
    render(
      <MaximizableContent>
        <p>Content</p>
      </MaximizableContent>,
    )
    const button = screen.getByLabelText('Maximize content')
    expect(button).toBeDefined()
  })

  it('opens dialog when maximize button is clicked', async () => {
    render(
      <MaximizableContent title="Test">
        <p>Dialog content</p>
      </MaximizableContent>,
    )

    // Dialog should not be present initially
    expect(screen.queryByRole('dialog')).toBeNull()

    // Click maximize button
    const maximizeButton = screen.getByLabelText('Maximize: Test')
    fireEvent.click(maximizeButton)

    // Dialog should now be present
    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeDefined()

    // Title should be visible in dialog
    expect(screen.getByText('Test')).toBeDefined()

    // Content should be in dialog (appears both inline and in dialog)
    const contentEls = screen.getAllByText('Dialog content')
    expect(contentEls.length).toBe(2)
  })

  it('closes dialog via close button', async () => {
    render(
      <MaximizableContent title="Test">
        <p>Dialog content</p>
      </MaximizableContent>,
    )

    // Open dialog
    fireEvent.click(screen.getByLabelText('Maximize: Test'))
    expect(screen.getByRole('dialog')).toBeDefined()

    // Close via X button
    const closeButton = screen.getByLabelText('Close maximized view')
    fireEvent.click(closeButton)

    // Dialog should be gone after click
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull()
    })
  })

  it('closes dialog via Escape key', async () => {
    render(
      <MaximizableContent title="Test">
        <p>Dialog content</p>
      </MaximizableContent>,
    )

    // Open dialog
    fireEvent.click(screen.getByLabelText('Maximize: Test'))
    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeDefined()

    // Close by pressing Escape key on the dialog
    fireEvent.keyDown(dialog, { key: 'Escape', code: 'Escape' })

    // Dialog should be gone
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull()
    })
  })

  it('displays title in dialog header', async () => {
    render(
      <MaximizableContent title="Agent Output Report">
        <p>Data here</p>
      </MaximizableContent>,
    )

    // Open dialog
    fireEvent.click(screen.getByLabelText('Maximize: Agent Output Report'))

    // Title should appear in dialog
    const dialogTitle = screen.getByText('Agent Output Report')
    expect(dialogTitle).toBeDefined()
  })

  it('renders dialog without title text when title not provided', async () => {
    render(
      <MaximizableContent>
        <p>Content only</p>
      </MaximizableContent>,
    )

    fireEvent.click(screen.getByLabelText('Maximize content'))

    // Dialog should still open and contain the content
    expect(screen.getByRole('dialog')).toBeDefined()
    expect(screen.getAllByText('Content only')).toHaveLength(2)
  })

  it('closes dialog on backdrop click', async () => {
    render(
      <MaximizableContent title="Test">
        <p>Dialog content</p>
      </MaximizableContent>,
    )

    // Open dialog
    fireEvent.click(screen.getByLabelText('Maximize: Test'))
    expect(screen.getByRole('dialog')).toBeDefined()

    // MUI Dialog renders a backdrop element before the dialog container.
    // Click the backdrop to trigger the onClose handler.
    const backdrop = document.querySelector('.MuiBackdrop-root') as HTMLElement
    expect(backdrop).toBeDefined()
    fireEvent.click(backdrop)

    // Dialog should close
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull()
    })
  })
})
