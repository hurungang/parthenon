import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { PlanStepTree } from '../components/agents/PlanStepTree'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      (options?.defaultValue as string | undefined) ?? key,
  }),
}))

describe('PlanStepTree', () => {
  it('renders nested steps from parent_order', () => {
    render(
      <PlanStepTree
        testIdPrefix="tree"
        steps={[
          { order: 1, name: 'Root', parent_order: null },
          { order: 2, name: 'Child', parent_order: 1 },
          { order: 3, name: 'Grandchild', parent_order: 2 },
        ]}
      />,
    )

    const root = screen.getByTestId('tree-step-1')
    const child = screen.getByTestId('tree-step-2')
    const grandchild = screen.getByTestId('tree-step-3')

    // A step renders inside its parent's container (the tree nesting), not as
    // a flat sibling.
    expect(root.contains(child)).toBe(true)
    expect(child.contains(grandchild)).toBe(true)
    expect(screen.getByText('Root')).toBeDefined()
    expect(screen.getByText('Grandchild')).toBeDefined()

    // Steps carry an action marker rather than a number (numbers get
    // confusing with sub-steps).
    expect(screen.getByTestId('tree-step-icon-1').tagName.toLowerCase()).toBe('svg')
    expect(screen.getByTestId('tree-step-icon-2').tagName.toLowerCase()).toBe('svg')
    expect(screen.queryByText('#1')).toBeNull()
  })

  it('treats a missing parent as a root (and never drops the step)', () => {
    render(
      <PlanStepTree
        testIdPrefix="orphan"
        steps={[{ order: 2, name: 'Orphan', parent_order: 99 }]}
      />,
    )

    expect(screen.getByTestId('orphan-step-2')).toBeDefined()
    expect(screen.getByText('Orphan')).toBeDefined()
  })

  it('treats a self-parent as a root (cycle safety)', () => {
    render(
      <PlanStepTree
        testIdPrefix="self"
        steps={[{ order: 1, name: 'Loop', parent_order: 1 }]}
      />,
    )

    expect(screen.getByTestId('self-step-1')).toBeDefined()
  })

  it('renders the script action as a button beside the step', () => {
    const onViewScript = vi.fn()
    render(
      <PlanStepTree
        testIdPrefix="script"
        steps={[
          {
            order: 1,
            name: 'Fetch contact',
            description: 'Fetch the contact from the CRM',
            python_source: 'def run(context, tools): ...',
          },
        ]}
        onViewScript={onViewScript}
      />,
    )

    const button = screen.getByTestId('view-script-1')
    expect(button.tagName).toBe('BUTTON')
    expect(button.textContent).toBe('View script')
    fireEvent.click(button)
    expect(onViewScript).toHaveBeenCalledOnce()
  })

  it('honours hasScriptAction for non-Python steps (base plan linkage)', () => {
    render(
      <PlanStepTree
        testIdPrefix="base"
        showType
        steps={[
          { order: 1, name: 'Linked', type: 'tool_call', script_version_id: 'v1' },
          { order: 2, name: 'Plain', type: 'tool_call' },
        ]}
        hasScriptAction={(step) => Boolean(step.script_version_id)}
        onViewScript={vi.fn()}
      />,
    )

    expect(screen.getByTestId('view-script-1')).toBeDefined()
    expect(screen.queryByTestId('view-script-2')).toBeNull()
  })
})
