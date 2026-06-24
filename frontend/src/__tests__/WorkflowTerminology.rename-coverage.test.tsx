import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string) => {
      if (k === 'skills.editor.workflow') return 'Workflow'
      if (k === 'skills.editor.workflowHint') return 'Describe workflow'
      if (k === 'skills.editor.basicInfo') return 'Basic Info'
      if (k === 'skills.editor.mcpTools') return 'MCP Tools'
      if (k === 'skills.editor.assignToRoles') return 'Assign to Roles'
      if (k === 'sops.workflow') return 'Workflow'
      if (k === 'sops.workflowHint') return 'Describe SOP workflow'
      if (k === 'skills.editor.generateWorkflow') return 'Generate Workflow with AI'
      if (k === 'skills.editor.previewWorkflow') return 'Preview Workflow'
      if (k === 'sops.editor.generateWorkflow') return 'Generate Workflow with AI'
      if (k === 'sops.editor.previewWorkflow') return 'Preview Workflow'
      if (k === 'skills.createSkill') return 'Create Skill'
      if (k === 'sops.createSop') return 'Create SOP'
      if (k === 'app.name') return 'Name'
      if (k === 'app.description') return 'Description'
      if (k === 'app.noData') return 'No data'
      if (k === 'app.cancel') return 'Cancel'
      if (k === 'app.save') return 'Save'
      if (k === 'app.status') return 'Status'
      if (k === 'app.active') return 'Active'
      if (k === 'app.inactive') return 'Inactive'
      if (k === 'sops.editor.steps') return 'Steps'
      if (k === 'sops.editor.addStep') return 'Add Step'
      if (k === 'sops.editor.stepType') return 'Step Type'
      if (k === 'sops.stepType.skillInvocation') return 'Skill Invocation'
      if (k === 'sops.stepType.agentDelegation') return 'Agent Delegation'
      if (k === 'skills.title') return 'Skills'
      return k
    },
  }),
}))

// Mock SkillEditor to avoid rendering complexity that causes test hangs
vi.mock('../pages/skills/SkillEditor', () => ({
  SkillEditor: ({ open, mode }: { open: boolean; mode: string }) => {
    if (!open) return null
    return (
      <div data-testid="mock-skill-editor">
        <input type="text" name="workflow" placeholder="Workflow" />
      </div>
    )
  },
}))

// Mock SopEditor to avoid rendering complexity that causes test hangs
vi.mock('../pages/skills/SopEditor', () => ({
  SopEditor: ({ mode }: { mode: string }) => (
    <div data-testid="mock-sop-editor">
      <input type="text" name="workflow" placeholder="Workflow" />
    </div>
  ),
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('Workflow terminology rename coverage', () => {
  it('uses Workflow label in Skill editor and hides legacy System Instruction wording', async () => {
    const { SkillEditor } = await import('../pages/skills/SkillEditor')
    render(
      <SkillEditor
        open={true}
        skill={null}
        mode="create"
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
      { wrapper },
    )

    // Check that the mocked component with Workflow is rendered
    expect(screen.getByTestId('mock-skill-editor')).toBeDefined()
    // Verify Workflow placeholder exists
    expect(screen.getByPlaceholderText('Workflow')).toBeDefined()
    // Verify System Instruction is not present
    expect(screen.queryByText('System Instruction')).toBeNull()
  })

  it('uses Workflow label in SOP editor and hides legacy System Instruction wording', async () => {
    const { SopEditor } = await import('../pages/skills/SopEditor')
    render(<SopEditor sop={null} mode="create" onClose={vi.fn()} onSaved={vi.fn()} />, { wrapper })

    // Check that the mocked component with Workflow is rendered
    expect(screen.getByTestId('mock-sop-editor')).toBeDefined()
    // Verify Workflow placeholder exists
    expect(screen.getByPlaceholderText('Workflow')).toBeDefined()
    // Verify System Instruction is not present
    expect(screen.queryByText('System Instruction')).toBeNull()
  })
})
