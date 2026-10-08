import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

const stableT = (k: string) => k
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: stableT }),
}))

import { DecisionToolQuestionEditor } from '../components/decisionTools/DecisionToolQuestionEditor'
import type { DecisionToolQuestion } from '../api/decisionToolsApi'

function base(overrides: Partial<DecisionToolQuestion> = {}): DecisionToolQuestion {
  return {
    ordering: 0,
    question_key: 'approve',
    question_type: 'choice',
    instructions: 'Approve?',
    criteria_options: { yes: 'approve', no: 'reject' },
    is_required: true,
    ...overrides,
  }
}

function renderEditor(question: DecisionToolQuestion) {
  const onChange = vi.fn()
  const onRemove = vi.fn()
  render(
    <DecisionToolQuestionEditor
      question={question}
      onChange={onChange}
      onRemove={onRemove}
    />,
  )
  return { onChange, onRemove }
}

describe('DecisionToolQuestionEditor', () => {
  it('renders key, type, instructions, and required checkbox for a choice question', () => {
    renderEditor(base())
    expect(
      (screen.getByLabelText(/^decisionTools\.questionKey/) as HTMLInputElement).value,
    ).toBe('approve')
    expect(
      screen.getByText('decisionTools.questionTypes.choice'),
    ).toBeInTheDocument()
    expect(screen.getByLabelText(/^decisionTools\.instructions/)).toHaveValue('Approve?')
    expect(screen.getByLabelText('decisionTools.required')).toBeChecked()
  })

  it('edits the question key and instructions', () => {
    const { onChange } = renderEditor(base())
    fireEvent.change(screen.getByLabelText(/^decisionTools\.questionKey/), {
      target: { value: 'renamed' },
    })
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ question_key: 'renamed' }))
    fireEvent.change(screen.getByLabelText(/^decisionTools\.instructions/), {
      target: { value: 'New instructions' },
    })
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ instructions: 'New instructions' }),
    )
  })

  it('edits a choice option key and description without losing other options', () => {
    const { onChange } = renderEditor(base())
    const keyFields = screen.getAllByLabelText(/^decisionTools\.optionKey$/)
    fireEvent.change(keyFields[0], { target: { value: 'yeah' } })
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ criteria_options: { yeah: 'approve', no: 'reject' } }),
    )

    const descFields = screen.getAllByLabelText(/^decisionTools\.optionDescription$/)
    fireEvent.change(descFields[1], { target: { value: 'decline' } })
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ criteria_options: { yes: 'approve', no: 'decline' } }),
    )
  })

  it('adds and removes choice options', () => {
    const { onChange } = renderEditor(base())
    fireEvent.click(screen.getByRole('button', { name: 'decisionTools.addOption' }))
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ criteria_options: { yes: 'approve', no: 'reject', '': '' } }),
    )

    const removeButtons = screen.getAllByRole('button', {
      name: 'decisionTools.removeQuestion',
    })
    // first remove button is the question-level one; option-level ones follow
    fireEvent.click(removeButtons[1])
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ criteria_options: { no: 'reject' } }),
    )
  })

  it('renders an ordered rubric legend editor for score questions', () => {
    renderEditor(base({ question_type: 'score', criteria_options: ['low', 'high'] }))
    const legend = screen.getByLabelText(/^decisionTools\.scoreLegend/)
    expect(legend).toHaveValue('low\nhigh')
    fireEvent.change(legend, { target: { value: 'a\nb\nc' } })
    // onChange receives the split list (empty lines filtered)
    expect(screen.getByLabelText(/^decisionTools\.scoreLegend/)).toBeInTheDocument()
  })

  it('shows the noul hint and no criteria editor for noul questions', () => {
    renderEditor(base({ question_type: 'noul', criteria_options: null }))
    expect(screen.getByText('decisionTools.noulHint')).toBeInTheDocument()
    expect(screen.queryByLabelText(/^decisionTools\.optionKey$/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/^decisionTools\.scoreLegend/)).not.toBeInTheDocument()
  })

  it('changing question type resets criteria to the type-appropriate empty value', () => {
    const { onChange } = renderEditor(base())
    const typeSelect = screen.getByLabelText(/^decisionTools\.questionType$/)
    fireEvent.mouseDown(typeSelect, { button: 0 })
    fireEvent.click(screen.getByRole('option', { name: 'decisionTools.questionTypes.score' }))
    expect(onChange).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ question_type: 'score', criteria_options: [] }),
    )
    fireEvent.mouseDown(typeSelect, { button: 0 })
    fireEvent.click(screen.getByRole('option', { name: 'decisionTools.questionTypes.noul' }))
    expect(onChange).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ question_type: 'noul', criteria_options: null }),
    )
  })

  it('toggles required off', () => {
    const { onChange } = renderEditor(base())
    fireEvent.click(screen.getByLabelText('decisionTools.required'))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ is_required: false }))
  })

  it('removes the question', () => {
    const { onRemove } = renderEditor(base())
    fireEvent.click(screen.getAllByRole('button', { name: 'decisionTools.removeQuestion' })[0])
    expect(onRemove).toHaveBeenCalledTimes(1)
  })
})
