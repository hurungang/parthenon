import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'
import { SkillEditor } from '../pages/skills/SkillEditor'
import { SopEditor } from '../pages/skills/SopEditor'

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

vi.mock('../hooks/useMcpServers', () => ({
  useAllTools: () => ({ data: [] }),
  useMcpServers: () => ({ data: [] }),
}))

vi.mock('../hooks/useSkills', () => ({
  useSkillRoles: () => ({ data: [] }),
}))

vi.mock('../hooks/useSops', () => ({
  useSopRoles: () => ({ data: [] }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn(),
    put: vi.fn().mockResolvedValue({ data: {} }),
  },
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
  it('uses Workflow label in Skill editor and hides legacy System Instruction wording', () => {
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

    expect(screen.getByRole('textbox', { name: 'Workflow' })).toBeDefined()
    expect(screen.queryByText('System Instruction')).toBeNull()
  })

  it('uses Workflow label in SOP editor and hides legacy System Instruction wording', () => {
    render(<SopEditor sop={null} mode="create" onClose={vi.fn()} onSaved={vi.fn()} />, { wrapper })

    expect(screen.getByRole('textbox', { name: 'Workflow' })).toBeDefined()
    expect(screen.queryByText('System Instruction')).toBeNull()
  })
})
