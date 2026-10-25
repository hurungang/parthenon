import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ScriptViewDialog, type ScriptViewData } from '../components/agents/ScriptViewDialog'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, params?: Record<string, unknown>) => {
      let out = k
      if (params) {
        for (const [key, value] of Object.entries(params)) {
          out = out.replace(`{{${key}}}`, String(value))
        }
      }
      return out
    },
  }),
}))

const SCRIPT: ScriptViewData = {
  name: 'fetch-contact',
  description: 'Fetches the contact from the CRM and formats the greeting.',
  version_label: 'v3',
  python_source: 'def run(context, tools):\n    return {"result": "hi"}',
}

describe('ScriptViewDialog', () => {
  it('renders the script source, description and version inline', () => {
    render(<ScriptViewDialog open script={SCRIPT} onClose={vi.fn()} />)

    expect(screen.getByTestId('script-view-source').textContent).toContain(
      'def run(context, tools)',
    )
    expect(screen.getByText(SCRIPT.description!)).toBeDefined()
    expect(screen.getByText(/v3/)).toBeDefined()
  })

  it('closes via the close button', () => {
    const onClose = vi.fn()
    render(<ScriptViewDialog open script={SCRIPT} onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: 'agents.scripts.scriptViewer.close' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('renders nothing when no script is selected', () => {
    render(<ScriptViewDialog open script={null} onClose={vi.fn()} />)
    expect(screen.queryByTestId('script-view-source')).toBeNull()
  })
})
