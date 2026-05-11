import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { WorkingStepsPanel } from '../components/logs/WorkingStepsPanel'
import type { WorkingStep, WorkingStepSpan } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

let idCounter = 0
beforeEach(() => {
  idCounter = 0
})

function makeStep(overrides: Partial<WorkingStep> = {}): WorkingStep {
  idCounter++
  return {
    id: `step-${idCounter}`,
    iconType: 'info',
    message: `Step message ${idCounter}`,
    timestamp: '2026-01-01T00:01:00Z',
    detail: null,
    ...overrides,
  }
}

function makeSpan(overrides: Partial<WorkingStepSpan> = {}): WorkingStepSpan {
  idCounter++
  return {
    id: `span-${idCounter}`,
    title: `Span ${idCounter}`,
    iconType: 'info',
    children: [],
    collapsed: false,
    ...overrides,
  }
}

/** Helper: build a Preparation span (expanded by default, info steps). */
function makePrepSpan(steps: WorkingStep[] = []): WorkingStepSpan {
  return makeSpan({
    id: 'span-preparation',
    title: 'Preparation',
    iconType: 'info',
    children: steps,
    collapsed: false,
  })
}

/** Helper: build an Agent Actions span (collapsed by default, contains iteration sub-spans). */
function makeAgentActionsSpan(iterationSpans: WorkingStepSpan[] = []): WorkingStepSpan {
  return makeSpan({
    id: 'span-agent-actions',
    title: 'Agent Actions',
    iconType: 'llm',
    children: iterationSpans,
    collapsed: true,
  })
}

/** Helper: build an iteration sub-span. */
function makeIterationSpan(num: number, steps: WorkingStep[] = []): WorkingStepSpan {
  return makeSpan({
    id: `iteration-${num}`,
    title: `Iteration ${num}`,
    iconType: 'llm',
    children: steps,
    collapsed: false,
  })
}

describe('WorkingStepsPanel', () => {
  it('renders the section title', () => {
    render(<WorkingStepsPanel spans={[]} />)
    expect(screen.getByText('agents.sessions.logViewer.workingSteps.title')).toBeDefined()
  })

  it('shows empty message when no spans provided', () => {
    render(<WorkingStepsPanel spans={[]} />)
    expect(screen.getByText('agents.sessions.logViewer.workingSteps.empty')).toBeDefined()
  })

  it('does not show empty message when spans with children are provided', () => {
    const spans = [makePrepSpan([makeStep({ iconType: 'info' })])]
    render(<WorkingStepsPanel spans={spans} />)
    expect(
      screen.queryByText('agents.sessions.logViewer.workingSteps.empty')
    ).toBeNull()
  })

  it('renders span titles as headings', () => {
    const spans = [makePrepSpan([makeStep()])]
    render(<WorkingStepsPanel spans={spans} />)
    expect(screen.getByText('Preparation')).toBeDefined()
  })

  it('expanded span (collapsed=false) shows its child steps', () => {
    const step = makeStep({ message: 'Visible step message' })
    const spans = [makePrepSpan([step])]
    render(<WorkingStepsPanel spans={spans} />)
    expect(screen.getByText('Visible step message')).toBeDefined()
  })

  it('Agent Actions span starts collapsed (aria-expanded="false")', () => {
    const llmStep = makeStep({ iconType: 'llm', message: 'LLM call' })
    const iterSpan = makeIterationSpan(1, [llmStep])
    const actionsSpan = makeAgentActionsSpan([iterSpan])
    render(<WorkingStepsPanel spans={[actionsSpan]} />)

    // The span header button should have aria-expanded="false"
    const toggleBtn = screen.getByText('Agent Actions').closest('[role="button"]')
    expect(toggleBtn?.getAttribute('aria-expanded')).toBe('false')
  })

  it('clicking collapsed span toggles it to expanded', () => {
    const actionsSpan = makeAgentActionsSpan([makeIterationSpan(1, [makeStep()])])
    render(<WorkingStepsPanel spans={[actionsSpan]} />)

    const toggleBtn = screen.getByText('Agent Actions').closest('[role="button"]')!
    fireEvent.click(toggleBtn)
    expect(toggleBtn.getAttribute('aria-expanded')).toBe('true')
  })

  it('clicking expanded span toggles it back to collapsed', () => {
    const prepSpan = makePrepSpan([makeStep()])
    render(<WorkingStepsPanel spans={[prepSpan]} />)

    const toggleBtn = screen.getByText('Preparation').closest('[role="button"]')!
    fireEvent.click(toggleBtn) // collapse
    expect(toggleBtn.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(toggleBtn) // expand again
    expect(toggleBtn.getAttribute('aria-expanded')).toBe('true')
  })

  it('renders nested iteration sub-spans inside Agent Actions', () => {
    const iter1 = makeIterationSpan(1, [makeStep({ message: 'iter1 step' })])
    const iter2 = makeIterationSpan(2, [makeStep({ message: 'iter2 step' })])
    const actionsSpan = makeAgentActionsSpan([iter1, iter2])
    render(<WorkingStepsPanel spans={[actionsSpan]} />)

    // Iteration titles are in the DOM even when parent is collapsed
    expect(screen.getByText('Iteration 1')).toBeDefined()
    expect(screen.getByText('Iteration 2')).toBeDefined()
  })

  it('step without detail has no expand detail button', () => {
    const step = makeStep({ detail: null })
    render(<WorkingStepsPanel spans={[makePrepSpan([step])]} />)

    // No aria-expanded buttons in the DOM beyond span toggles
    const expandBtns = screen.queryAllByRole('button').filter(
      (btn) => btn.getAttribute('aria-expanded') !== null
    )
    // One button for the span toggle, none for step detail
    expect(expandBtns).toHaveLength(1)
  })

  it('step with detail shows an expand detail button', () => {
    const step = makeStep({
      iconType: 'success',
      message: 'Step with detail',
      detail: { label: 'myTool', content: '{"input": 1}' },
    })
    render(<WorkingStepsPanel spans={[makePrepSpan([step])]} />)

    // The section starts collapsed — expand it first
    const sectionToggle = screen.getByRole('button', { name: /agents.sessions.logViewer.workingSteps.title/i })
    fireEvent.click(sectionToggle)

    const detailBtn = screen.getByRole('button', { name: /expand detail|collapse detail/i })
    expect(detailBtn).toBeDefined()
    expect(detailBtn.getAttribute('aria-expanded')).toBe('false')
  })

  it('clicking step expand button reveals detail content', () => {
    const step = makeStep({
      detail: { label: 'myTool', content: '{"input": 1}' },
    })
    render(<WorkingStepsPanel spans={[makePrepSpan([step])]} />)

    // The section starts collapsed — expand it first
    const sectionToggle = screen.getByRole('button', { name: /agents.sessions.logViewer.workingSteps.title/i })
    fireEvent.click(sectionToggle)

    const detailBtn = screen.getByRole('button', { name: /expand detail|collapse detail/i })
    fireEvent.click(detailBtn)

    expect(detailBtn.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByText('myTool')).toBeDefined()
  })

  it('clicking expanded step detail button collapses it', () => {
    const step = makeStep({
      detail: { label: 'myTool', content: '{}' },
    })
    render(<WorkingStepsPanel spans={[makePrepSpan([step])]} />)

    // The section starts collapsed — expand it first
    const sectionToggle = screen.getByRole('button', { name: /agents.sessions.logViewer.workingSteps.title/i })
    fireEvent.click(sectionToggle)

    const detailBtn = screen.getByRole('button', { name: /expand detail|collapse detail/i })
    fireEvent.click(detailBtn)
    fireEvent.click(detailBtn)

    expect(detailBtn.getAttribute('aria-expanded')).toBe('false')
  })

  it('handles keyboard Enter to toggle span', () => {
    const actionsSpan = makeAgentActionsSpan([makeIterationSpan(1)])
    render(<WorkingStepsPanel spans={[actionsSpan]} />)

    const toggleBtn = screen.getByText('Agent Actions').closest('[role="button"]')!
    fireEvent.keyDown(toggleBtn, { key: 'Enter' })

    expect(toggleBtn.getAttribute('aria-expanded')).toBe('true')
  })

  it('handles keyboard Space to toggle span', () => {
    const actionsSpan = makeAgentActionsSpan([makeIterationSpan(1)])
    render(<WorkingStepsPanel spans={[actionsSpan]} />)

    const toggleBtn = screen.getByText('Agent Actions').closest('[role="button"]')!
    fireEvent.keyDown(toggleBtn, { key: ' ' })

    expect(toggleBtn.getAttribute('aria-expanded')).toBe('true')
  })
})
