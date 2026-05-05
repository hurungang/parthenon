import { describe, it, expect, vi } from 'vitest'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../hooks/useMcpServers', () => ({
  useAllTools: () => ({ data: [], isLoading: false }),
  useMcpServers: () => ({ data: [], isLoading: false }),
}))

vi.mock('../hooks/useSkills', () => ({
  useSkillRoles: () => ({ data: [], isLoading: false }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: [] }),
  },
}))

describe('SkillEditor — import only', () => {
  it('can import the component without errors', async () => {
    const module = await import('../pages/skills/SkillEditor')
    expect(module.SkillEditor).toBeDefined()
    expect(typeof module.SkillEditor).toBe('function')
  })
})
