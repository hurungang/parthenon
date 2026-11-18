import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

/**
 * In-chat ask/decide card (optimization mode).
 *
 * The optimizer asks a question inline; the operator answers with one of the
 * offered choices, an approval, or free text. The answer is recorded once and
 * the optimizer never proceeds on an assumption. A resolved card stays in the
 * record read-only.
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

import { OptimizerAskCard } from '../components/optimizer/OptimizerAskCard'

const baseProps = {
  reason: 'Which field should the script summarise?',
  interventionType: 'choice' as const,
  choices: ['summary', 'raw_json'],
  onSelectChoice: vi.fn(),
  onSubmitText: vi.fn(),
  onCancel: vi.fn(),
}

describe('OptimizerAskCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the question inline with a needs-your-answer chip', () => {
    render(<OptimizerAskCard {...baseProps} />)

    const card = screen.getByTestId('optimizer-ask')
    expect(card.textContent).toContain('Which field should the script summarise?')
    expect(card.textContent).toContain('agents.optimizer.askTitle')
    expect(screen.getByTestId('optimizer-ask-chip').textContent).toBe(
      'agents.optimizer.askChip',
    )
  })

  it('offers every requested choice and reports the selected answer once', async () => {
    render(<OptimizerAskCard {...baseProps} />)

    expect(screen.getByTestId('optimizer-ask-choice-summary')).toBeDefined()
    expect(screen.getByTestId('optimizer-ask-choice-raw_json')).toBeDefined()

    fireEvent.click(screen.getByTestId('optimizer-ask-choice-summary'))

    await waitFor(() => {
      expect(baseProps.onSelectChoice).toHaveBeenCalledWith('summary')
    })
    expect(baseProps.onSelectChoice).toHaveBeenCalledTimes(1)
    expect(baseProps.onSubmitText).not.toHaveBeenCalled()
  })

  it('accepts a free-text answer alongside the choices', async () => {
    render(<OptimizerAskCard {...baseProps} />)

    const textarea = screen.getByTestId('optimizer-ask-text')
    // Nothing to submit while empty.
    expect(
      (screen.getByTestId('optimizer-ask-submit') as HTMLButtonElement).disabled,
    ).toBe(true)

    fireEvent.change(textarea, { target: { value: '  Use the customer name  ' } })
    fireEvent.click(screen.getByTestId('optimizer-ask-submit'))

    await waitFor(() => {
      // Trimmed, single submission.
      expect(baseProps.onSubmitText).toHaveBeenCalledWith('Use the customer name')
    })
    expect(baseProps.onSubmitText).toHaveBeenCalledTimes(1)
  })

  it('dismisses the request without answering', async () => {
    render(<OptimizerAskCard {...baseProps} />)

    fireEvent.click(screen.getByTestId('optimizer-ask-cancel'))

    await waitFor(() => {
      expect(baseProps.onCancel).toHaveBeenCalledTimes(1)
    })
    expect(baseProps.onSelectChoice).not.toHaveBeenCalled()
    expect(baseProps.onSubmitText).not.toHaveBeenCalled()
  })

  it('renders approve / deny for a plain approval request', async () => {
    const onApprove = vi.fn()
    const onDeny = vi.fn()
    render(
      <OptimizerAskCard
        {...baseProps}
        interventionType="approval"
        choices={null}
        onApprove={onApprove}
        onDeny={onDeny}
      />,
    )

    // No choices for an approval — the two buttons are the answer surface.
    expect(screen.queryByTestId('optimizer-ask-choice-summary')).toBeNull()

    fireEvent.click(screen.getByTestId('optimizer-ask-approve'))
    await waitFor(() => expect(onApprove).toHaveBeenCalledTimes(1))

    fireEvent.click(screen.getByTestId('optimizer-ask-deny'))
    await waitFor(() => expect(onDeny).toHaveBeenCalledTimes(1))
  })

  it('renders read-only with the recorded answer once resolved', () => {
    render(<OptimizerAskCard {...baseProps} resolvedAnswer="summary" />)

    const resolved = screen.getByTestId('optimizer-ask-resolved')
    expect(resolved.textContent).toContain('agents.optimizer.askResolved')
    expect(resolved.textContent).toContain('summary')

    // The input surfaces are gone: the decision cannot be answered twice.
    expect(screen.queryByTestId('optimizer-ask-choice-summary')).toBeNull()
    expect(screen.queryByTestId('optimizer-ask-text')).toBeNull()
    expect(screen.queryByTestId('optimizer-ask-submit')).toBeNull()
    expect(screen.queryByTestId('optimizer-ask-cancel')).toBeNull()
  })

  it('blocks the answer surface while a submission is in flight', () => {
    render(<OptimizerAskCard {...baseProps} isSubmitting />)

    expect(
      (screen.getByTestId('optimizer-ask-choice-summary') as HTMLButtonElement).disabled,
    ).toBe(true)
    expect(
      (screen.getByTestId('optimizer-ask-text') as HTMLTextAreaElement).disabled,
    ).toBe(true)
    expect(
      (screen.getByTestId('optimizer-ask-cancel') as HTMLButtonElement).disabled,
    ).toBe(true)
  })

  it('surfaces a response failure through the dialog error standard', () => {
    render(
      <OptimizerAskCard
        {...baseProps}
        dialogError={{ response: { status: 403, data: { detail: 'Not allowed' } } }}
      />,
    )

    expect(screen.getByText('Not allowed')).toBeDefined()
  })
})
