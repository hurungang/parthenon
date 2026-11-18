import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

/**
 * Optimization-mode chrome primitives.
 *
 * These are the operator-visible safety surfaces of an optimization
 * conversation: the mode/scope bar (identity parity, typed vs conversational
 * scope, replay-only / live-used chip), the expandable activity block ("what it
 * looked at"), the replay-vs-live audit block, and the optimizer-model alert.
 * Everything renders from `t()` keys (no hardcoded copy).
 */

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // Key-echo translator; parameters are appended so assertions can prove the
    // subject name / model id / count the component actually passed in.
    t: (k: string, params?: Record<string, unknown>) =>
      params
        ? `${k} ${Object.entries(params)
            .map(([key, value]) => `${key}=${String(value)}`)
            .join(' ')}`
        : k,
  }),
}))

import { OptimizationSessionBar } from '../components/optimizer/OptimizationSessionBar'
import { OptimizerActivityBlock } from '../components/optimizer/OptimizerActivityBlock'
import { OptimizerAuditBlock } from '../components/optimizer/OptimizerAuditBlock'
import { OptimizerModelAlert } from '../components/optimizer/OptimizerModelAlert'
import {
  OPTIMIZER_REASON_MODEL_NOT_CONFIGURED,
  OPTIMIZER_REASON_MODEL_NOT_ENABLED,
} from '../utils/errorUtils'
import type { OptimizationAudit } from '../types'

describe('OptimizationSessionBar', () => {
  const replayOnlyAudit: OptimizationAudit = {
    replay_verifications: 2,
    live_operations: 0,
    last_live_at: null,
    replay_only: true,
  }
  const liveUsedAudit: OptimizationAudit = {
    replay_verifications: 5,
    live_operations: 2,
    last_live_at: '2026-01-02T08:30:00.000Z',
    replay_only: false,
  }

  it('is a compact, default-collapsed "What ran in this session" bar', () => {
    render(<OptimizationSessionBar audit={replayOnlyAudit} subjectName="Refund Agent" />)

    const bar = screen.getByTestId('optimization-session-bar')
    expect(bar.getAttribute('data-expanded')).toBe('false')
    expect(screen.getByTestId('optimization-session-bar-toggle').textContent).toContain(
      'agents.optimizer.sessionBar.title',
    )
    // The full mode/scope header block is gone from the chat.
    expect(screen.queryByTestId('optimization-mode-bar')).toBeNull()
  })

  it('keeps the replay-only safety signal visible at a glance', () => {
    render(<OptimizationSessionBar audit={replayOnlyAudit} subjectName="A" />)

    expect(screen.getByTestId('optimization-session-bar-replay-chip').textContent).toContain(
      'agents.optimizer.audit.replay',
    )
    expect(screen.getByTestId('optimization-session-bar-live-chip').textContent).toBe(
      'agents.optimizer.audit.noLive',
    )
    expect(screen.getByTestId('optimization-session-bar-replay-only-chip').textContent).toBe(
      'agents.optimizer.replayOnly',
    )
  })

  it('switches to the live-used chip once an approved script ran', () => {
    render(<OptimizationSessionBar audit={liveUsedAudit} subjectName="A" />)

    const chip = screen.getByTestId('optimization-session-bar-live-chip')
    expect(chip.textContent).toContain('agents.optimizer.audit.liveUsed')
    expect(chip.textContent).toContain('2')
    expect(screen.queryByTestId('optimization-session-bar-replay-only-chip')).toBeNull()
  })

  it('shows the running chip between an approval and its result', () => {
    render(
      <OptimizationSessionBar audit={replayOnlyAudit} subjectName="A" liveTestRunning />,
    )

    expect(screen.getByTestId('optimization-session-bar-running-chip').textContent).toBe(
      'agents.optimizer.liveRunning',
    )
  })

  it('expands to the audit details, identity parity and scope', () => {
    render(
      <OptimizationSessionBar
        audit={replayOnlyAudit}
        subjectName="Chat Agent"
        isConversational
      />,
    )

    fireEvent.click(screen.getByTestId('optimization-session-bar-toggle'))

    const bar = screen.getByTestId('optimization-session-bar')
    expect(bar.getAttribute('data-expanded')).toBe('true')
    expect(screen.getByTestId('optimization-session-bar-audit')).toBeVisible()
    expect(screen.getByTestId('optimization-session-bar-identity').textContent).toBe(
      'agents.optimizer.identityParity',
    )
    expect(screen.getByTestId('optimization-session-bar-scope').textContent).toContain(
      'agents.optimizer.scopeConversational',
    )
    expect(screen.getByTestId('optimization-session-bar-scope').textContent).not.toContain(
      'agents.optimizer.scopePlan',
    )
  })

  it('renders safely before the audit has been read', () => {
    render(<OptimizationSessionBar audit={null} subjectName="A" />)

    expect(screen.getByTestId('optimization-session-bar-live-chip').textContent).toBe(
      'agents.optimizer.audit.noLive',
    )
    expect(screen.getByTestId('optimization-session-bar-replay-only-chip')).toBeDefined()
  })
})

describe('OptimizerActivityBlock', () => {
  const steps = [
    {
      id: 'step-1',
      toolName: 'execute_script',
      state: 'done' as const,
      timestamp: '2026-01-01T10:00:00.000Z',
    },
    {
      id: 'step-2',
      toolName: 'get_execution_log',
      state: 'done' as const,
      timestamp: '2026-01-01T10:00:05.000Z',
    },
  ]

  it('renders nothing when the turn touched no tool', () => {
    const { container } = render(<OptimizerActivityBlock steps={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('summarises a finished turn and expands to every step it took', () => {
    render(<OptimizerActivityBlock steps={steps} outcome="plan ready" />)

    const block = screen.getByTestId('optimizer-activity')
    expect(block.getAttribute('data-running')).toBe('false')
    expect(screen.getByTestId('optimizer-activity-toggle').textContent).toContain(
      'agents.optimizer.activity.worked',
    )

    // Collapsed by default: detail stays hidden, the turn is readable at a glance.
    for (const hiddenStep of screen.queryAllByTestId('optimizer-activity-step')) {
      expect(hiddenStep).not.toBeVisible()
    }

    fireEvent.click(screen.getByTestId('optimizer-activity-toggle'))

    const rendered = screen.getAllByTestId('optimizer-activity-step')
    expect(rendered).toHaveLength(2)
    expect(rendered[0]).toBeVisible()
    expect(rendered[0].textContent).toContain('execute_script')
    expect(rendered[1].textContent).toContain('get_execution_log')
    expect(rendered[0].textContent).toContain('agents.optimizer.activity.stepDone')
    expect(screen.getByTestId('optimizer-activity').textContent).toContain(
      'agents.optimizer.activity.note',
    )
    // A finished turn reports its outcome, never an indefinite spinner.
    expect(screen.getByTestId('optimizer-activity-outcome').textContent).toBe('plan ready')
  })

  it('shows a working state while a step is still running', () => {
    render(
      <OptimizerActivityBlock
        steps={[{ ...steps[0], state: 'running' }]}
      />,
    )

    expect(screen.getByTestId('optimizer-activity').getAttribute('data-running')).toBe('true')
    expect(screen.getByTestId('optimizer-activity-running')).toBeDefined()
    expect(screen.getByTestId('optimizer-activity-toggle').textContent).toContain(
      'agents.optimizer.activity.working',
    )
  })
})

describe('OptimizerAuditBlock', () => {
  const replayOnlyAudit: OptimizationAudit = {
    replay_verifications: 3,
    live_operations: 0,
    last_live_at: null,
    replay_only: true,
  }

  it('shows replay count, "0 live", and the replay-only chip by default', () => {
    render(<OptimizerAuditBlock audit={replayOnlyAudit} />)

    expect(screen.getByTestId('optimizer-audit-replay').textContent).toContain('3')
    expect(screen.getByTestId('optimizer-audit-live').textContent).toBe(
      'agents.optimizer.audit.noLive',
    )
    expect(screen.getByTestId('optimizer-audit-replay-only').textContent).toBe(
      'agents.optimizer.audit.replayOnlyChip',
    )
    expect(screen.getByTestId('optimizer-audit').textContent).toContain(
      'agents.optimizer.audit.noteReplayOnly',
    )
  })

  it('distinguishes approved live operations from replay work (single use)', () => {
    render(
      <OptimizerAuditBlock
        audit={{
          replay_verifications: 1,
          live_operations: 2,
          last_live_at: '2026-01-02T08:30:00.000Z',
          replay_only: false,
        }}
        agentTypeName="Refund Agent"
        operatorName="ada"
      />,
    )

    expect(screen.getByTestId('optimizer-audit-replay').textContent).toContain('1')
    const live = screen.getByTestId('optimizer-audit-live')
    expect(live.textContent).toContain('agents.optimizer.audit.liveUsed')
    expect(live.textContent).toContain('2')
    // Replay-only chip disappears once live work actually ran.
    expect(screen.queryByTestId('optimizer-audit-replay-only')).toBeNull()
    const block = screen.getByTestId('optimizer-audit')
    expect(block.textContent).toContain('agents.optimizer.audit.noteLive')
    expect(block.textContent).toContain('agents.optimizer.audit.lastLiveAt')
    expect(block.textContent).toContain('Refund Agent')
    expect(block.textContent).toContain('ada')
  })
})

describe('OptimizerModelAlert', () => {
  it('explains an unconfigured workspace and points at System Config', () => {
    render(
      <OptimizerModelAlert
        reasonCode={OPTIMIZER_REASON_MODEL_NOT_CONFIGURED}
        action={<button data-testid="shortcut">go</button>}
      />,
    )

    const alert = screen.getByTestId('optimizer-model-alert')
    expect(alert.textContent).toContain('agents.optimizer.modelAlertTitle')
    expect(alert.textContent).toContain('agents.optimizer.modelAlertBodyNotConfigured')
    // The shortcut is rendered as the alert action.
    expect(screen.getByTestId('shortcut')).toBeDefined()
  })

  it('names the stale model and states no model is substituted', () => {
    render(
      <OptimizerModelAlert
        reasonCode={OPTIMIZER_REASON_MODEL_NOT_ENABLED}
        modelId="retired-model"
      />,
    )

    const alert = screen.getByTestId('optimizer-model-alert')
    expect(alert.textContent).toContain('agents.optimizer.modelAlertBodyNotEnabled')
    expect(alert.textContent).toContain('retired-model')
  })

  it('falls back to the unknown-model label when the stale id is absent', () => {
    render(<OptimizerModelAlert reasonCode={OPTIMIZER_REASON_MODEL_NOT_ENABLED} />)
    expect(screen.getByTestId('optimizer-model-alert').textContent).toContain(
      'agents.optimizer.modelAlertUnknownModel',
    )
  })

  it('falls back to generic guidance for an unrecognised reason', () => {
    render(<OptimizerModelAlert reasonCode="something_else" />)
    expect(screen.getByTestId('optimizer-model-alert').textContent).toContain(
      'agents.optimizer.modelAlertBodyGeneric',
    )
  })
})
