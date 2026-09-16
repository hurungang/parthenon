import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, unknown>) =>
      k === 'agents.panel.pendingChanges' && opts && 'count' in opts
        ? `Pending changes (${opts.count})`
        : k,
  }),
}))

vi.mock('../components/permissions/PermissionDeniedAlert', () => ({
  default: ({ error }: { error: unknown; fallbackMessage?: string }) => (
    <div data-testid="tray-error">{error instanceof Error ? error.message : 'error'}</div>
  ),
}))

import { PendingChangesTray } from '../components/agents/panel/PendingChangesTray'
import type { AgentEquipmentSlotId } from '../types'

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('PendingChangesTray', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  function renderTray(overrides: Partial<Parameters<typeof PendingChangesTray>[0]> = {}) {
    const props = {
      dirty: false,
      changedSlotIds: [] as AgentEquipmentSlotId[],
      saving: false,
      saveError: null,
      onSave: vi.fn(),
      onDiscard: vi.fn(),
      ...overrides,
    }
    render(<PendingChangesTray {...props} />)
    return props
  }

  it('is inert while the draft is pristine: save and discard disabled, no slot chips', () => {
    renderTray()

    expect(screen.getByRole('button', { name: 'agents.panel.save' }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByRole('button', { name: 'agents.panel.discard' }).hasAttribute('disabled')).toBe(true)
    expect(screen.queryByText('agents.panel.slots.role.label')).toBeNull()
    expect(screen.getByText('agents.panel.savedChip')).toBeDefined()
  })

  it('shows pending slot chips and enables save/discard when dirty', () => {
    const props = renderTray({
      dirty: true,
      changedSlotIds: ['role', 'skills', 'model'],
    })

    expect(screen.getByText('agents.panel.unsavedChip')).toBeDefined()
    expect(screen.getByText('agents.panel.slots.role.label')).toBeDefined()
    expect(screen.getByText('agents.panel.slots.skills.label')).toBeDefined()
    expect(screen.getByText('agents.panel.slots.model.label')).toBeDefined()
    expect(screen.getByRole('button', { name: 'agents.panel.save' }).hasAttribute('disabled')).toBe(false)
    expect(screen.getByRole('button', { name: 'agents.panel.discard' }).hasAttribute('disabled')).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: 'agents.panel.save' }))
    expect(props.onSave).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByRole('button', { name: 'agents.panel.discard' }))
    expect(props.onDiscard).toHaveBeenCalledOnce()
  })

  it('shows the properties chip and includes it in the pending count', () => {
    renderTray({ dirty: true, changedSlotIds: ['role'], propertiesChanged: true })

    expect(screen.getByText('agents.panel.properties.label')).toBeDefined()
    expect(screen.getByText('Pending changes (2)')).toBeDefined()
  })

  it('lists only the properties chip when just base properties changed', () => {
    renderTray({ dirty: true, changedSlotIds: [], propertiesChanged: true })

    expect(screen.getByText('agents.panel.properties.label')).toBeDefined()
    expect(screen.queryByText('agents.panel.slots.role.label')).toBeNull()
    expect(screen.getByText('Pending changes (1)')).toBeDefined()
  })

  it('disables save when the draft name is invalid (saveDisabled) while discard stays enabled', () => {
    renderTray({ dirty: true, changedSlotIds: [], propertiesChanged: true, saveDisabled: true })

    expect(screen.getByRole('button', { name: 'agents.panel.save' }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByRole('button', { name: 'agents.panel.discard' }).hasAttribute('disabled')).toBe(false)
  })

  it('disables actions while saving is in flight', () => {
    renderTray({ dirty: true, changedSlotIds: ['role'], saving: true })

    expect(screen.getByRole('button', { name: 'agents.panel.save' }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByRole('button', { name: 'agents.panel.discard' }).hasAttribute('disabled')).toBe(true)
  })

  it('renders a save failure inside the tray area (never silent)', () => {
    renderTray({ dirty: true, changedSlotIds: ['role'], saveError: new Error('403 Forbidden') })

    expect(screen.getByTestId('tray-error')).toBeDefined()
    expect(screen.getByText('403 Forbidden')).toBeDefined()
    // The failure does not stop the tray from offering Save again.
    expect(screen.getByRole('button', { name: 'agents.panel.save' }).hasAttribute('disabled')).toBe(false)
  })

  it('renders each structured binding-validation error from the backend 422 detail', () => {
    const bindingError = {
      response: {
        status: 422,
        data: {
          detail: {
            error: 'binding_validation_failed',
            messages: [
              'Skill 38ec91c7-4378-42f6-b5b8-61d8cf5bfdba is not accessible through the assigned role.',
              'Duplicate SOP binding: sop_id=sop-9 appears more than once.',
            ],
            errors: [
              {
                resource_type: 'skill',
                resource_id: '38ec91c7-4378-42f6-b5b8-61d8cf5bfdba',
                rule: 'role_access',
                message: 'Skill 38ec91c7-4378-42f6-b5b8-61d8cf5bfdba is not accessible through the assigned role.',
              },
              {
                resource_type: 'sop',
                resource_id: 'sop-9',
                rule: 'duplicate',
                message: 'Duplicate SOP binding: sop_id=sop-9 appears more than once.',
              },
            ],
          },
        },
      },
    }
    renderTray({ dirty: true, changedSlotIds: ['skills'], saveError: bindingError })

    // Title renders (i18n key) and BOTH specific errors are listed — not the
    // generic fallback and not just the vague error code.
    expect(screen.getByText('agents.panel.bindingValidationFailed')).toBeDefined()
    expect(screen.getByText(/Skill 38ec91c7-4378-42f6-b5b8-61d8cf5bfdba is not accessible/)).toBeDefined()
    expect(screen.getByText(/Duplicate SOP binding: sop_id=sop-9 appears more than once/)).toBeDefined()
    expect(screen.queryByTestId('tray-error')).toBeNull()
    // Save stays available after the failure.
    expect(screen.getByRole('button', { name: 'agents.panel.save' }).hasAttribute('disabled')).toBe(false)
  })

  it('falls back to the generic error alert when a 422 detail has no messages', () => {
    const emptyBindingError = {
      response: {
        status: 422,
        data: { detail: { error: 'binding_validation_failed', messages: [], errors: [] } },
      },
    }
    renderTray({ dirty: true, changedSlotIds: ['skills'], saveError: emptyBindingError })

    expect(screen.queryByText('agents.panel.bindingValidationFailed')).toBeNull()
    expect(screen.getByTestId('tray-error')).toBeDefined()
  })
})
