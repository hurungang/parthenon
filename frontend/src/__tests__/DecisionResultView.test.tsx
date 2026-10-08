import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, params?: Record<string, unknown>) =>
    params && 'value' in params ? `${k}:${params['value']}` : k }),
}))

import { DecisionResultView } from '../components/results/DecisionResultView'
import type { DecisionExecutionResult } from '../api/systemOneApi'

const COMPLETED_RESULT: DecisionExecutionResult = {
  id: 'r-1',
  tenant_id: null,
  decision_tool_id: 'dt-1',
  conversation_session_id: null,
  input_state_snapshot: { tier: 'gold' },
  answers: {
    gate_confidence: 0.93,
    answers: {
      route: {
        type: 'choice',
        question_type: 'choice',
        value: 'escalate',
        choice: 'escalate',
        probabilities: { escalate: 0.85, refund: 0.15 },
        confidence: 0.93,
        effective_confidence: 0.93,
      },
      severity: {
        type: 'score',
        question_type: 'score',
        value: 4,
        score: 4,
        legend: ['low', 'medium', 'high', 'critical', 'worst'],
        confidence: 0.9,
        effective_confidence: 0.9,
      },
      is_outage: {
        type: 'noul',
        question_type: 'noul',
        value: 0.95,
        noul: 0.95,
        effective_confidence: 0.9,
      },
    },
  },
  outcome: 'act',
  status: 'completed',
  provider_model: 'jev-latest',
  error_message: null,
  created_at: '2026-10-03T00:00:00Z',
}

describe('DecisionResultView', () => {
  it('renders the gate outcome, gate confidence, and provider model', () => {
    render(<DecisionResultView result={COMPLETED_RESULT} />)
    expect(screen.getByText('results.decision.outcomes.act')).toBeInTheDocument()
    expect(
      screen.getByText('results.decision.gateConfidence:93.0%'),
    ).toBeInTheDocument()
    expect(screen.getByText('jev-latest')).toBeInTheDocument()
  })

  it('renders the input state snapshot as JSON', () => {
    render(<DecisionResultView result={COMPLETED_RESULT} />)
    expect(screen.getByText('results.decision.inputState')).toBeInTheDocument()
    expect(screen.getByText(/"tier": "gold"/)).toBeInTheDocument()
  })

  it('renders a typed choice answer with probabilities', () => {
    render(<DecisionResultView result={COMPLETED_RESULT} />)
    expect(screen.getByText('route')).toBeInTheDocument()
    expect(screen.getAllByText('escalate').length).toBeGreaterThan(0)
    expect(screen.getByText('85.0%')).toBeInTheDocument()
    expect(screen.getByText('15.0%')).toBeInTheDocument()
    expect(
      screen.getByText('results.decision.confidence:93.0%'),
    ).toBeInTheDocument()
    expect(screen.getByText('results.decision.probabilities')).toBeInTheDocument()
  })

  it('renders a score answer with its legend', () => {
    render(<DecisionResultView result={COMPLETED_RESULT} />)
    expect(screen.getByText('severity')).toBeInTheDocument()
    expect(screen.getByText('4')).toBeInTheDocument()
    // Legend rendered as "index=label" entries.
    expect(screen.getByText(/0=low/)).toBeInTheDocument()
    expect(screen.getByText(/4=worst/)).toBeInTheDocument()
  })

  it('renders a noul answer as a probability', () => {
    render(<DecisionResultView result={COMPLETED_RESULT} />)
    expect(screen.getByText('is_outage')).toBeInTheDocument()
    expect(screen.getByText('95.0%')).toBeInTheDocument()
    expect(
      screen.getByText('results.decision.noulProbability'),
    ).toBeInTheDocument()
  })

  it('renders the question-type chips', () => {
    render(<DecisionResultView result={COMPLETED_RESULT} />)
    expect(
      screen.getByText('results.decision.questionTypes.choice'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('results.decision.questionTypes.score'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('results.decision.questionTypes.noul'),
    ).toBeInTheDocument()
  })

  it('renders a failed execution as an error with the message', () => {
    const failed: DecisionExecutionResult = {
      ...COMPLETED_RESULT,
      status: 'failed',
      outcome: 'escalate',
      answers: null,
      error_message: 'TypeSafe Jev returned HTTP 503',
    }
    render(<DecisionResultView result={failed} />)
    expect(screen.getByText('results.decision.failed')).toBeInTheDocument()
    expect(
      screen.getByText('TypeSafe Jev returned HTTP 503'),
    ).toBeInTheDocument()
  })

  it('shows the no-data placeholder when there are no answers', () => {
    const empty: DecisionExecutionResult = {
      ...COMPLETED_RESULT,
      answers: { answers: {}, gate_confidence: 0 },
    }
    render(<DecisionResultView result={empty} />)
    expect(screen.getByText('app.noData')).toBeInTheDocument()
  })

  it('renders confirm outcome with warning semantics (no crash)', () => {
    const confirm: DecisionExecutionResult = {
      ...COMPLETED_RESULT,
      outcome: 'confirm',
    }
    render(<DecisionResultView result={confirm} />)
    expect(screen.getByText('results.decision.outcomes.confirm')).toBeInTheDocument()
  })

  it('renders escalate outcome', () => {
    const escalate: DecisionExecutionResult = {
      ...COMPLETED_RESULT,
      outcome: 'escalate',
    }
    render(<DecisionResultView result={escalate} />)
    expect(screen.getByText('results.decision.outcomes.escalate')).toBeInTheDocument()
  })
})
