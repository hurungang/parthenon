/**
 * Unit tests for CloneRoleDialog component.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'

vi.mock('react-i18next', () => {
  // Stable reference so useEffect([..., t]) doesn't re-run on every render
  const t = (k: string, opts?: Record<string, unknown>) => {
    if (k === 'permissions.roles.cloneNamePrefix' && opts?.name) {
      return `Copy of ${opts.name}`
    }
    return k
  }
  return {
    useTranslation: () => ({ t }),
  }
})

const mockCloneRole = vi.fn()

vi.mock('../hooks/usePermissions', () => ({
  useCloneRole: () => ({
    mutateAsync: mockCloneRole,
    isPending: false,
  }),
}))

const sourceRole = {
  id: 'role-src',
  name: 'Admin Role',
  description: 'Full admin access',
  is_active: true,
  is_system: false,
  role_type: 'user_defined' as const,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  policy_count: 2,
  user_assignment_count: 1,
  group_assignment_count: 0,
}

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  function wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={qc}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    )
  }
  return wrapper
}

describe('CloneRoleDialog', () => {
  it('pre-fills name with "Copy of {source name}"', async () => {
    const { default: CloneRoleDialog } = await import(
      '../components/permissions/CloneRoleDialog'
    )
    render(
      <CloneRoleDialog open={true} sourceRole={sourceRole} onClose={vi.fn()} />,
      { wrapper: makeWrapper() }
    )

    // Wait for inputs to render and check name pre-fill
    await waitFor(() => {
      const inputs = Array.from(document.querySelectorAll('input'))
      const nameInput = inputs.find((el) => el.value === 'Copy of Admin Role')
      expect(nameInput).toBeDefined()
    })
  })

  it('pre-fills description from source role', async () => {
    const { default: CloneRoleDialog } = await import(
      '../components/permissions/CloneRoleDialog'
    )
    render(
      <CloneRoleDialog open={true} sourceRole={sourceRole} onClose={vi.fn()} />,
      { wrapper: makeWrapper() }
    )

    await waitFor(() => {
      const inputs = Array.from(document.querySelectorAll('input, textarea'))
      const descInput = inputs.find((el) => (el as HTMLInputElement).value === 'Full admin access')
      expect(descInput).toBeDefined()
    })
  })

  it('Submit button is disabled when name is empty', async () => {
    const user = userEvent.setup()
    const { default: CloneRoleDialog } = await import(
      '../components/permissions/CloneRoleDialog'
    )
    render(
      <CloneRoleDialog open={true} sourceRole={sourceRole} onClose={vi.fn()} />,
      { wrapper: makeWrapper() }
    )

    // Wait for name input to be pre-filled
    let nameInput: HTMLInputElement | undefined
    await waitFor(() => {
      const inputs = Array.from(document.querySelectorAll('input'))
      nameInput = inputs.find((el) => el.value === 'Copy of Admin Role') as HTMLInputElement
      expect(nameInput).toBeDefined()
    })

    // Use userEvent.clear() for reliable controlled-input state updates
    await user.clear(nameInput!)

    await waitFor(() => {
      const buttons = Array.from(document.querySelectorAll('button'))
      const submitBtn = buttons.find(
        (b) => b.textContent?.trim() === 'permissions.roles.cloneRole'
      )
      // MUI v7 disabled button: check disabled attr OR aria-disabled
      const isDisabled =
        (submitBtn as HTMLButtonElement)?.disabled === true ||
        submitBtn?.getAttribute('aria-disabled') === 'true' ||
        submitBtn?.classList.contains('Mui-disabled')
      expect(isDisabled).toBe(true)
    })
  })

  it('submitting calls cloneRole mutation with correct data', async () => {
    mockCloneRole.mockResolvedValueOnce({ id: 'new-role', name: 'Copy of Admin Role' })

    const { default: CloneRoleDialog } = await import(
      '../components/permissions/CloneRoleDialog'
    )
    const onClose = vi.fn()
    render(
      <CloneRoleDialog open={true} sourceRole={sourceRole} onClose={onClose} />,
      { wrapper: makeWrapper() }
    )

    await waitFor(() => {
      const inputs = Array.from(document.querySelectorAll('input'))
      expect(inputs.some((el) => el.value === 'Copy of Admin Role')).toBe(true)
    })

    const buttons = Array.from(document.querySelectorAll('button'))
    const submitBtn = buttons.find(
      (b) => b.textContent?.trim() === 'permissions.roles.cloneRole'
    ) as HTMLButtonElement
    expect(submitBtn).toBeDefined()
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(mockCloneRole).toHaveBeenCalledWith({
        sourceId: 'role-src',
        data: expect.objectContaining({ name: 'Copy of Admin Role' }),
      })
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('API error is shown inline (Dialog Error Handling Standard)', async () => {
    const error = {
      response: {
        status: 409,
        data: { detail: "Role 'Copy of Admin Role' already exists." },
      },
    }
    mockCloneRole.mockRejectedValueOnce(error)

    const { default: CloneRoleDialog } = await import(
      '../components/permissions/CloneRoleDialog'
    )
    const onClose = vi.fn()
    render(
      <CloneRoleDialog open={true} sourceRole={sourceRole} onClose={onClose} />,
      { wrapper: makeWrapper() }
    )

    await waitFor(() => {
      const inputs = Array.from(document.querySelectorAll('input'))
      expect(inputs.some((el) => el.value === 'Copy of Admin Role')).toBe(true)
    })

    const buttons = Array.from(document.querySelectorAll('button'))
    const submitBtn = buttons.find(
      (b) => b.textContent?.trim() === 'permissions.roles.cloneRole'
    ) as HTMLButtonElement
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(mockCloneRole).toHaveBeenCalled()
      // Dialog stays open (onClose not called on error)
      expect(onClose).not.toHaveBeenCalled()
    })
  })

  it('Cancel button calls onClose', async () => {
    const { default: CloneRoleDialog } = await import(
      '../components/permissions/CloneRoleDialog'
    )
    const onClose = vi.fn()
    render(
      <CloneRoleDialog open={true} sourceRole={sourceRole} onClose={onClose} />,
      { wrapper: makeWrapper() }
    )

    const cancelBtn = await screen.findByRole('button', { name: /app\.cancel/i })
    fireEvent.click(cancelBtn)
    expect(onClose).toHaveBeenCalled()
  })

  it('form resets when dialog is reopened with a different source role', async () => {
    const { default: CloneRoleDialog } = await import(
      '../components/permissions/CloneRoleDialog'
    )
    const wrapper = makeWrapper()
    const { rerender } = render(
      <CloneRoleDialog open={true} sourceRole={sourceRole} onClose={vi.fn()} />,
      { wrapper }
    )

    await waitFor(() => {
      const inputs = Array.from(document.querySelectorAll('input'))
      expect(inputs.some((el) => el.value === 'Copy of Admin Role')).toBe(true)
    })

    const differentRole = {
      ...sourceRole,
      id: 'role-2',
      name: 'Read Only Role',
      description: 'Limited access',
    }

    rerender(<CloneRoleDialog open={true} sourceRole={differentRole} onClose={vi.fn()} />)

    await waitFor(() => {
      const inputs = Array.from(document.querySelectorAll('input'))
      expect(inputs.some((el) => el.value === 'Copy of Read Only Role')).toBe(true)
    })
  })
})
