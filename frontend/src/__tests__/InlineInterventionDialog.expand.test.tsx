/**
 * FIX-20261101-223511 — Expand/Maximize approval card:
 * - the approval card gains an Expand control;
 * - the expanded dialog renders the SAME full-width preview table;
 * - approving from the EXPANDED dialog invokes the same approve handler;
 * - collapsing returns to the inline card without losing state.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { InlineInterventionDialog } from '../components/conversations/InlineInterventionDialog'
import type { InterveneRequestMessage } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, unknown>) => {
      const map: Record<string, string> = {
        'conversations.sessions.intervention.requiresYourInput': 'Requires your input',
        'conversations.sessions.intervention.delegatedBy': 'Delegated by parent',
        'conversations.sessions.intervention.typeApproval': 'Approval',
        'conversations.sessions.intervention.approve': 'Approve',
        'conversations.sessions.intervention.deny': 'Deny',
        'conversations.sessions.intervention.expand': 'Expand',
        'conversations.sessions.intervention.collapse': 'Collapse',
        'conversations.sessions.intervention.previewTitle': 'Approval Preview',
        'conversations.sessions.intervention.dismissCancel': 'Dismiss / Cancel',
        'app.error': 'An error occurred',
      }
      void opts
      return map[k] ?? k
    },
  }),
}))

const markdownTable = [
  '**Create Skill: sql-runner**',
  '',
  '| Field | Value |',
  '|-------|-------|',
  '| Operation | create |',
  '| Resource Type | skill |',
  '| Name | sql-runner |',
  '| Tools | supabase____run_sql |',
].join('\n')

const baseRequest: InterveneRequestMessage = {
  type: 'intervene_request',
  request_id: 'req-223511',
  intervention_type: 'approval',
  reason: markdownTable,
  agent_type: 'AssistantAgent',
  delegation_depth: 1,
  conversation_session_id: 'conv-223511',
}

describe('InlineInterventionDialog expand (FIX-20261101-223511)', () => {
  const onApprove = vi.fn<() => void | Promise<void>>()
  const onDeny = vi.fn<() => void | Promise<void>>()
  const onSelectChoice = vi.fn<(choice: string) => void | Promise<void>>()
  const onSubmitText = vi.fn<(text: string) => void | Promise<void>>()
  const onDismiss = vi.fn<() => void | Promise<void>>()

  beforeEach(() => {
    onApprove.mockClear()
    onDeny.mockClear()
    onSelectChoice.mockClear()
    onSubmitText.mockClear()
    onDismiss.mockClear()
  })

  function renderCard() {
    return render(
      <InlineInterventionDialog
        request={baseRequest}
        onApprove={onApprove}
        onDeny={onDeny}
        onSelectChoice={onSelectChoice}
        onSubmitText={onSubmitText}
        onDismiss={onDismiss}
      />,
    )
  }

  it('renders an Expand control on the approval card', () => {
    const { container } = renderCard()
    const expandBtn = screen.getByRole('button', { name: 'Expand' })
    expect(expandBtn).toBeDefined()
    // Inline preview already renders the table.
    expect(container.querySelector('table')).not.toBeNull()
  })

  it('expanded dialog shows the full-width preview table', async () => {
    const { container } = renderCard()
    fireEvent.click(screen.getByRole('button', { name: 'Expand' }))
    await waitFor(() => {
      expect(screen.getByText('Approval Preview')).toBeDefined()
    })
    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeDefined()
    const table = dialog.querySelector('table')
    expect(table).not.toBeNull()
    expect(table?.querySelectorAll('tr').length).toBe(5)
    expect(dialog.textContent).toContain('supabase____run_sql')
    void container
  })

  it('approving from the EXPANDED dialog invokes the same onApprove handler', async () => {
    renderCard()
    fireEvent.click(screen.getByRole('button', { name: 'Expand' }))
    await waitFor(() => expect(screen.getByRole('dialog')).toBeDefined())
    const dialog = screen.getByRole('dialog')
    const approveInDialog = Array.from(dialog.querySelectorAll('button')).find(
      (b) => b.textContent === 'Approve',
    )
    expect(approveInDialog).toBeDefined()
    fireEvent.click(approveInDialog!)
    await waitFor(() => expect(onApprove).toHaveBeenCalledTimes(1))
  })

  it('deny from the EXPANDED dialog invokes the same onDeny handler', async () => {
    renderCard()
    fireEvent.click(screen.getByRole('button', { name: 'Expand' }))
    await waitFor(() => expect(screen.getByRole('dialog')).toBeDefined())
    const dialog = screen.getByRole('dialog')
    const denyInDialog = Array.from(dialog.querySelectorAll('button')).find(
      (b) => b.textContent === 'Deny',
    )
    fireEvent.click(denyInDialog!)
    await waitFor(() => expect(onDeny).toHaveBeenCalledTimes(1))
  })

  it('collapsing back keeps the inline card usable (approve from inline still works)', async () => {
    renderCard()
    fireEvent.click(screen.getByRole('button', { name: 'Expand' }))
    await waitFor(() => expect(screen.getByRole('dialog')).toBeDefined())
    // Two "Collapse" controls exist (title-bar icon + footer button) — use the footer one.
    const collapseButtons = screen.getAllByRole('button', { name: 'Collapse' })
    fireEvent.click(collapseButtons[collapseButtons.length - 1])
    await waitFor(() => {
      // Expanded dialog no longer contains an Approve button — back to inline.
      expect(screen.queryByRole('dialog')).toBeNull()
    })
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(onApprove).toHaveBeenCalledTimes(1))
  })

  it('inline approve still works without expanding (round-trip untouched)', async () => {
    renderCard()
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(onApprove).toHaveBeenCalledTimes(1))
  })
})
