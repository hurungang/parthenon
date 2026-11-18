import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

/**
 * Script-based live-test approval card (optimization mode).
 *
 * The SCRIPT is the unit of approval: approving runs the whole script once, end
 * to end, in the real sandbox as the agent — MCP tools are assumed to work, and
 * the tool-call preview is informational only. Pending is the only expanded
 * state; after the decision the card collapses into a one-line history summary
 * that expands to the script run record (output + telemetry + tool calls).
 */

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // Key-echo translator; parameters are appended so assertions can prove the
    // subject name / script / count the component actually passed in.
    t: (k: string, params?: Record<string, unknown>) =>
      params
        ? `${k} ${Object.entries(params)
            .map(([key, value]) => `${key}=${String(value)}`)
            .join(' ')}`
        : k,
  }),
}))

import { LiveTestApprovalCard } from '../components/optimizer/LiveTestApprovalCard'
import type { LiveTestApprovalSummary, ScriptRunRecord } from '../types'

function makeProposal(
  overrides: Partial<LiveTestApprovalSummary> = {},
): LiveTestApprovalSummary {
  return {
    live_test_request_id: 'ltr-1',
    status: 'pending',
    // ~10 minutes left in the answer window.
    expires_at: new Date(Date.now() + 10 * 60_000).toISOString(),
    script_version_id: 'sv-3',
    script_name: 'search-flights',
    script_version_label: 'v3',
    operations: [
      {
        tool_name: 'crm____lookup_contact',
        arguments: { email: 'ada@example.com' },
        purpose: 'Confirm the contact exists',
      },
      {
        tool_name: 'crm____list_tickets',
        arguments: { contact_id: 'c-42' },
        purpose: 'Check the ticket history',
      },
    ],
    executed_operations: null,
    target_agent_type_id: 'at-1',
    ...overrides,
  }
}

function makeRun(overrides: Partial<ScriptRunRecord> = {}): ScriptRunRecord {
  return {
    kind: 'script_run',
    script_version_id: 'sv-3',
    script_name: 'search-flights',
    script_version_label: 'v3',
    status: 'success',
    result_summary: 'Found 2 itineraries for SFO→JFK',
    error: null,
    duration_ms: 1200,
    tool_calls: [
      {
        tool_name: 'crm____lookup_contact',
        status: 'success',
        duration_ms: 400,
        result_summary: '1 contact',
        error: null,
      },
      {
        tool_name: 'crm____list_tickets',
        status: 'success',
        duration_ms: 800,
        result_summary: '3 tickets',
        error: null,
      },
    ],
    telemetry: { steps: 2 },
    ...overrides,
  }
}

describe('LiveTestApprovalCard', () => {
  const onApprove = vi.fn()
  const onDeny = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('presents the script under test — not the MCP tools — as the unit', () => {
    render(
      <LiveTestApprovalCard
        liveTest={makeProposal()}
        agentTypeName="Refund Agent"
        onApprove={onApprove}
        onDeny={onDeny}
      />,
    )

    const card = screen.getByTestId('live-test-approval')
    expect(card.getAttribute('data-state')).toBe('pending')
    expect(card.getAttribute('data-expanded')).toBe('true')
    expect(card.textContent).toContain('agents.optimizer.approval.runScriptTitle')
    expect(screen.getByTestId('live-test-approval-script').textContent).toContain(
      'search-flights',
    )
    expect(screen.getByTestId('live-test-approval-script').textContent).toContain('v3')
    // End-to-end framing: MCP tools are assumed to work.
    expect(screen.getByTestId('live-test-approval-subtitle').textContent).toContain(
      'agents.optimizer.approval.scriptSubtitle',
    )
    expect(screen.getByTestId('live-test-approval-subtitle').textContent).toContain(
      'Refund Agent',
    )
  })

  it('lists the tool-call preview as informational, not individually approved', () => {
    render(
      <LiveTestApprovalCard
        liveTest={makeProposal()}
        agentTypeName="Refund Agent"
        onApprove={onApprove}
        onDeny={onDeny}
      />,
    )

    const preview = screen.getByTestId('live-test-approval-preview')
    expect(preview.textContent).toContain('agents.optimizer.approval.itWillCall')
    expect(preview.textContent).toContain('crm____lookup_contact')
    expect(preview.textContent).toContain('crm____list_tickets')
    expect(preview.textContent).toContain('agents.optimizer.approval.previewNote')
  })

  it('falls back to an explicit no-preview line when the script calls no tool', () => {
    render(
      <LiveTestApprovalCard
        liveTest={makeProposal({ operations: [] })}
        agentTypeName="Refund Agent"
        onApprove={onApprove}
        onDeny={onDeny}
      />,
    )

    expect(screen.getByTestId('live-test-approval-preview').textContent).toContain(
      'agents.optimizer.approval.noPreview',
    )
  })

  it('states "runs once as this agent; not remembered" and the expiry window', () => {
    render(
      <LiveTestApprovalCard
        liveTest={makeProposal()}
        agentTypeName="Refund Agent"
        onApprove={onApprove}
        onDeny={onDeny}
      />,
    )

    expect(screen.getByTestId('live-test-approval-note').textContent).toContain(
      'agents.optimizer.approval.runsOnceNote',
    )
    expect(screen.getByTestId('live-test-approval-note').textContent).toContain(
      'Refund Agent',
    )
    const card = screen.getByTestId('live-test-approval')
    expect(card.textContent).toContain('agents.optimizer.approval.expiryWindowMinutes')
    expect(card.textContent).toContain('agents.optimizer.approval.denyHint')
  })

  it('sends the approve decision once', () => {
    render(
      <LiveTestApprovalCard
        liveTest={makeProposal()}
        agentTypeName="Refund Agent"
        onApprove={onApprove}
        onDeny={onDeny}
      />,
    )

    fireEvent.click(screen.getByTestId('live-test-approval-approve'))
    expect(onApprove).toHaveBeenCalledTimes(1)
  })

  it('sends the deny decision once', () => {
    render(
      <LiveTestApprovalCard
        liveTest={makeProposal()}
        agentTypeName="Refund Agent"
        onApprove={onApprove}
        onDeny={onDeny}
      />,
    )

    fireEvent.click(screen.getByTestId('live-test-approval-deny'))
    expect(onDeny).toHaveBeenCalledTimes(1)
  })

  it('disables both decisions while the response is submitting', () => {
    render(
      <LiveTestApprovalCard
        liveTest={makeProposal()}
        agentTypeName="Refund Agent"
        isSubmitting
        onApprove={onApprove}
        onDeny={onDeny}
      />,
    )

    expect(
      (screen.getByTestId('live-test-approval-approve') as HTMLButtonElement).disabled,
    ).toBe(true)
    expect(
      (screen.getByTestId('live-test-approval-deny') as HTMLButtonElement).disabled,
    ).toBe(true)
  })

  it('collapses an executed run into a one-line summary and expands to the script output', () => {
    render(
      <LiveTestApprovalCard
        liveTest={makeProposal({ status: 'executed' })}
        agentTypeName="Refund Agent"
        scriptRun={makeRun()}
        onApprove={onApprove}
        onDeny={onDeny}
      />,
    )

    const card = screen.getByTestId('live-test-approval')
    expect(card.getAttribute('data-state')).toBe('executed')
    // Collapsed by default — the decision already happened.
    expect(card.getAttribute('data-expanded')).toBe('false')
    expect(screen.getByTestId('live-test-approval-summary').textContent).toBe(
      'Found 2 itineraries for SFO→JFK',
    )
    expect(screen.getByTestId('live-test-approval-script').textContent).toBe(
      'search-flights',
    )
    expect(screen.queryByTestId('live-test-approval-approve')).toBeNull()
    expect(screen.queryByTestId('live-test-approval-deny')).toBeNull()

    fireEvent.click(screen.getByTestId('live-test-approval-toggle'))

    expect(screen.getByTestId('live-test-approval').getAttribute('data-expanded')).toBe(
      'true',
    )
    expect(screen.getByTestId('live-test-approval-result').textContent).toContain(
      'Found 2 itineraries for SFO→JFK',
    )
    const telemetry = screen.getByTestId('live-test-approval-telemetry')
    expect(telemetry.textContent).toContain('agents.optimizer.approval.duration')
    expect(telemetry.textContent).toContain('1.2 s')
    expect(telemetry.textContent).toContain('agents.optimizer.approval.toolCalls')
    expect(telemetry.textContent).toContain('2')

    const calls = screen.getAllByTestId(/live-test-approval-tool-call-/)
    expect(calls).toHaveLength(2)
    expect(calls[0].textContent).toContain('crm____lookup_contact')
    expect(calls[1].textContent).toContain('crm____list_tickets')
    expect(screen.getByTestId('live-test-approval-details').textContent).toContain(
      'agents.optimizer.approval.usedOnce',
    )
  })

  it('shows a failed run with its error and keeps the detail expandable', () => {
    render(
      <LiveTestApprovalCard
        liveTest={makeProposal({ status: 'failed' })}
        agentTypeName="Refund Agent"
        scriptRun={makeRun({ status: 'error', result_summary: null, error: 'permission denied' })}
        errorText="permission denied"
        onApprove={onApprove}
        onDeny={onDeny}
      />,
    )

    const card = screen.getByTestId('live-test-approval')
    expect(card.getAttribute('data-state')).toBe('failed')
    expect(card.getAttribute('data-expanded')).toBe('false')
    expect(screen.getByTestId('live-test-approval-summary').textContent).toBe(
      'permission denied',
    )
    expect(screen.queryByTestId('live-test-approval-approve')).toBeNull()

    fireEvent.click(screen.getByTestId('live-test-approval-toggle'))
    expect(screen.getByTestId('live-test-approval-error').textContent).toBe(
      'permission denied',
    )
    expect(screen.getByTestId('live-test-approval-details').textContent).toContain(
      'agents.optimizer.approval.failedReplayOnly',
    )
  })

  it('reads a denied request as a collapsed history line (nothing ran)', () => {
    render(
      <LiveTestApprovalCard
        liveTest={makeProposal({ status: 'denied' })}
        agentTypeName="Refund Agent"
        onApprove={onApprove}
        onDeny={onDeny}
      />,
    )

    const card = screen.getByTestId('live-test-approval')
    expect(card.getAttribute('data-state')).toBe('denied')
    expect(card.getAttribute('data-expanded')).toBe('false')
    expect(screen.getByTestId('live-test-approval-summary').textContent).toBe(
      'agents.optimizer.approval.summaryDenied',
    )
    expect(screen.queryByTestId('live-test-approval-approve')).toBeNull()
    expect(screen.queryByTestId('live-test-approval-deny')).toBeNull()
  })

  it('keeps an expired request collapsed and explicitly closed', () => {
    render(
      <LiveTestApprovalCard
        liveTest={makeProposal({ status: 'expired' })}
        agentTypeName="Refund Agent"
        onApprove={onApprove}
        onDeny={onDeny}
      />,
    )

    const card = screen.getByTestId('live-test-approval')
    expect(card.getAttribute('data-state')).toBe('expired')
    expect(card.getAttribute('data-expanded')).toBe('false')
    expect(screen.getByTestId('live-test-approval-expired-chip').textContent).toBe(
      'agents.optimizer.approval.chipExpired',
    )
    expect(screen.getByTestId('live-test-approval-summary').textContent).toBe(
      'agents.optimizer.approval.summaryExpired',
    )

    fireEvent.click(screen.getByTestId('live-test-approval-toggle'))
    expect(screen.getByTestId('live-test-approval-details').textContent).toContain(
      'agents.optimizer.approval.noteExpired',
    )
    expect(screen.queryByTestId('live-test-approval-approve')).toBeNull()
    expect(screen.queryByTestId('live-test-approval-deny')).toBeNull()
  })

  it('keeps a cancelled request collapsed and closed', () => {
    render(
      <LiveTestApprovalCard
        liveTest={makeProposal({ status: 'cancelled' })}
        agentTypeName="Refund Agent"
        onApprove={onApprove}
        onDeny={onDeny}
      />,
    )

    const card = screen.getByTestId('live-test-approval')
    expect(card.getAttribute('data-state')).toBe('cancelled')
    expect(card.getAttribute('data-expanded')).toBe('false')
    expect(screen.getByTestId('live-test-approval-cancelled-chip')).toBeDefined()
    expect(screen.getByTestId('live-test-approval-summary').textContent).toBe(
      'agents.optimizer.approval.summaryCancelled',
    )
  })

  it('collapses as soon as the approval is running', () => {
    render(
      <LiveTestApprovalCard
        liveTest={makeProposal({ status: 'approved' })}
        agentTypeName="Refund Agent"
        state="running"
        onApprove={onApprove}
        onDeny={onDeny}
      />,
    )

    const card = screen.getByTestId('live-test-approval')
    expect(card.getAttribute('data-state')).toBe('running')
    expect(card.getAttribute('data-expanded')).toBe('false')
    expect(screen.getByTestId('live-test-approval-summary').textContent).toContain(
      'agents.optimizer.approval.summaryRunning',
    )
    expect(screen.getByTestId('live-test-approval-summary').textContent).toContain(
      'Refund Agent',
    )
    expect(screen.queryByTestId('live-test-approval-approve')).toBeNull()
  })
})
