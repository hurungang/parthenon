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
})
