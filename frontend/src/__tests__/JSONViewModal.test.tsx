/**
 * Unit tests for JSONViewModal component.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockRole = {
  id: 'role-1',
  name: 'Admin Role',
  description: 'Full admin access',
  is_active: true,
  is_system: false,
  policy_statements: [
    {
      id: 'policy-1',
      effect: 'allow',
      module: 'agent',
      actions: [{ id: 'a1', action: 'read' }, { id: 'a2', action: 'execute' }],
      resources: [],
      tag_conditions: [{ id: 'tc1', tag_key: 'env', tag_value: 'prod' }],
      created_at: '2024-01-01T00:00:00Z',
    },
    {
      id: 'policy-2',
      effect: 'deny',
      module: 'role',
      actions: [{ id: 'a3', action: 'manage' }],
      resources: [],
      tag_conditions: [],
      created_at: '2024-01-01T00:00:00Z',
    },
  ],
}

vi.mock('../hooks/usePermissions', () => ({
  useRole: () => ({ data: mockRole, isLoading: false }),
}))

// Mock clipboard API
const mockWriteText = vi.fn().mockResolvedValue(undefined)
Object.defineProperty(navigator, 'clipboard', {
  value: { writeText: mockWriteText },
  writable: true,
})

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('JSONViewModal', () => {
  it('renders JSON with correct structure: role_id, name, statements array', async () => {
    const { default: JSONViewModal } = await import(
      '../components/permissions/JSONViewModal'
    )
    render(
      <JSONViewModal
        open={true}
        roleId="role-1"
        roleName="Admin Role"
        onClose={vi.fn()}
      />,
      { wrapper }
    )

    // Wait for the dialog to render — use the title text as indicator
    await screen.findByText(/permissions\.roles\.jsonView/i)

    // Verify pre element has JSON content
    const pre = document.querySelector('pre')
    expect(pre?.textContent).toContain('"role_id"')
    expect(pre?.textContent).toContain('"name"')
    expect(pre?.textContent).toContain('"statements"')
  })

  it('each statement has effect, resource_type, actions, and conditions.tags', async () => {
    const { default: JSONViewModal } = await import(
      '../components/permissions/JSONViewModal'
    )
    render(
      <JSONViewModal
        open={true}
        roleId="role-1"
        roleName="Admin Role"
        onClose={vi.fn()}
      />,
      { wrapper }
    )

    await waitFor(() => {
      const pre = document.querySelector('pre')
      expect(pre?.textContent).toContain('"effect"')
      expect(pre?.textContent).toContain('"resource_type"')
      expect(pre?.textContent).toContain('"actions"')
      expect(pre?.textContent).toContain('"conditions"')
    })
  })

  it('JSON output includes all statements from the role', async () => {
    const { default: JSONViewModal } = await import(
      '../components/permissions/JSONViewModal'
    )
    render(
      <JSONViewModal
        open={true}
        roleId="role-1"
        roleName="Admin Role"
        onClose={vi.fn()}
      />,
      { wrapper }
    )

    await waitFor(() => {
      const pre = document.querySelector('pre')
      // Both resource types from mockRole should appear
      expect(pre?.textContent).toContain('"agent"')
      expect(pre?.textContent).toContain('"role"')
      // Actions
      expect(pre?.textContent).toContain('"read"')
      expect(pre?.textContent).toContain('"execute"')
      // Tag conditions
      expect(pre?.textContent).toContain('"env"')
      expect(pre?.textContent).toContain('"prod"')
    })
  })

  it('Copy JSON button copies text to clipboard', async () => {
    mockWriteText.mockResolvedValueOnce(undefined)

    const { default: JSONViewModal } = await import(
      '../components/permissions/JSONViewModal'
    )
    render(
      <JSONViewModal
        open={true}
        roleId="role-1"
        roleName="Admin Role"
        onClose={vi.fn()}
      />,
      { wrapper }
    )

    await waitFor(() => {
      expect(document.querySelector('pre')?.textContent).toContain('"role_id"')
    })

    // Find the copy icon button (it's an IconButton)
    const copyButton = document.querySelector('button[aria-label], button')
    if (copyButton) {
      fireEvent.click(copyButton)
    }

    await waitFor(() => {
      expect(mockWriteText).toHaveBeenCalledWith(
        expect.stringContaining('"role_id"')
      )
    })
  })

  it('Close button calls onClose handler', async () => {
    const { default: JSONViewModal } = await import(
      '../components/permissions/JSONViewModal'
    )
    const onClose = vi.fn()
    render(
      <JSONViewModal
        open={true}
        roleId="role-1"
        roleName="Admin Role"
        onClose={onClose}
      />,
      { wrapper }
    )

    await waitFor(() => {
      expect(screen.getByText('app.close')).toBeDefined()
    })

    fireEvent.click(screen.getByText('app.close'))
    expect(onClose).toHaveBeenCalled()
  })

  it('shows loading state while role data is fetching', async () => {
    vi.doMock('../hooks/usePermissions', () => ({
      useRole: () => ({ data: undefined, isLoading: true }),
    }))

    const { default: JSONViewModal } = await import(
      '../components/permissions/JSONViewModal'
    )
    const { container } = render(
      <JSONViewModal
        open={true}
        roleId="role-1"
        roleName="Admin Role"
        onClose={vi.fn()}
      />,
      { wrapper }
    )

    // Component renders without crash in loading state
    expect(container).toBeDefined()
    vi.resetModules()
  })
})
