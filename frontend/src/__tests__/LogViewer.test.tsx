import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { LogViewer } from '../components/logs/LogViewer'
import type { ExecutionLogEntry, ExecutionLogRead } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

beforeEach(() => {
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    writable: true,
    configurable: true,
  })
})

// ── Fixtures ───────────────────────────────────────────────────────────────────

const EXECUTION_LOG: ExecutionLogRead = {
  id: 'log-1',
  session_id: 'sess-1',
  system_instruction:
    'Identity: agent@example.com\nRole: DataAnalyst\nModel: gpt-4o\nAssigned SOPs: DataPipeline\n\n1. Load data\n2. Analyse\n',
  user_prompt: 'Analyse the quarterly report',
  logged_at: '2026-01-01T00:00:00Z',
}

const LOG_ENTRIES: ExecutionLogEntry[] = [
  {
    id: 'e0',
    timestamp: '2026-01-01T00:00:00Z',
    event_type: 'session_started',
    log_level: 'INFO',
    message: 'Session started',
    data: {
      identity_name: 'agent@example.com',
      role_name: 'DataAnalyst',
      model_id: 'gpt-4o',
    },
  },
  {
    id: 'e1',
    timestamp: '2026-01-01T00:01:00Z',
    event_type: 'llm_call',
    log_level: 'INFO',
    message: 'LLM call initiated',
    data: {},
  },
  {
    id: 'e2',
    timestamp: '2026-01-01T00:02:00Z',
    event_type: 'tool_call',
    log_level: 'INFO',
    message: 'Tool invoked',
    data: { tool_name: 'QueryDB', input: 'SELECT *' },
  },
  {
    id: 'e3',
    timestamp: '2026-01-01T00:03:00Z',
    event_type: 'agent_finish',
    log_level: 'INFO',
    message: 'Agent finished',
    data: {},
  },
]

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('LogViewer', () => {
  it('renders the log viewer title', () => {
    render(<LogViewer executionLog={EXECUTION_LOG} entries={LOG_ENTRIES} />)
    expect(screen.getByText('agents.sessions.logViewer.title')).toBeDefined()
  })

  it('renders the RawLogToggle in the header', () => {
    render(<LogViewer executionLog={EXECUTION_LOG} entries={LOG_ENTRIES} />)
    const switchEl = screen.getByRole('switch')
    expect(switchEl).toBeDefined()
  })

  it('renders LogSummaryPanel in friendly mode (default)', () => {
    render(<LogViewer executionLog={EXECUTION_LOG} entries={LOG_ENTRIES} />)
    expect(screen.getByText('agents.sessions.logViewer.summary.title')).toBeDefined()
  })

  it('renders WorkingStepsPanel in friendly mode (default)', () => {
    render(<LogViewer executionLog={EXECUTION_LOG} entries={LOG_ENTRIES} />)
    expect(
      screen.getByText('agents.sessions.logViewer.workingSteps.title')
    ).toBeDefined()
  })

  it('does NOT render raw log pre block in friendly mode (default)', () => {
    render(<LogViewer executionLog={EXECUTION_LOG} entries={LOG_ENTRIES} />)
    const rawPre = document.querySelector('pre[aria-label]')
    expect(rawPre).toBeNull()
  })

  it('renders raw log pre block after toggling to raw mode', () => {
    render(<LogViewer executionLog={EXECUTION_LOG} entries={LOG_ENTRIES} />)
    const switchEl = screen.getByRole('switch')
    fireEvent.click(switchEl)

    const rawPre = document.querySelector(
      `pre[aria-label="agents.sessions.logViewer.rawLogAriaLabel"]`
    )
    expect(rawPre).not.toBeNull()
  })

  it('hides summary panel when in raw mode', () => {
    render(<LogViewer executionLog={EXECUTION_LOG} entries={LOG_ENTRIES} />)
    const switchEl = screen.getByRole('switch')
    fireEvent.click(switchEl)

    expect(
      screen.queryByText('agents.sessions.logViewer.summary.title')
    ).toBeNull()
  })

  it('hides working steps panel when in raw mode', () => {
    render(<LogViewer executionLog={EXECUTION_LOG} entries={LOG_ENTRIES} />)
    const switchEl = screen.getByRole('switch')
    fireEvent.click(switchEl)

    expect(
      screen.queryByText('agents.sessions.logViewer.workingSteps.title')
    ).toBeNull()
  })

  it('raw log block contains the raw log text', () => {
    render(<LogViewer executionLog={EXECUTION_LOG} entries={LOG_ENTRIES} />)
    const switchEl = screen.getByRole('switch')
    fireEvent.click(switchEl)

    const rawPre = document.querySelector('pre[aria-label]') as HTMLPreElement
    expect(rawPre?.textContent).toContain('agent@example.com')
    expect(rawPre?.textContent).toContain('LLM call initiated')
  })

  it('toggles back to friendly mode on second click', () => {
    render(<LogViewer executionLog={EXECUTION_LOG} entries={LOG_ENTRIES} />)
    const switchEl = screen.getByRole('switch')

    fireEvent.click(switchEl) // → raw mode
    fireEvent.click(switchEl) // → friendly mode

    expect(screen.getByText('agents.sessions.logViewer.summary.title')).toBeDefined()
    expect(document.querySelector('pre[aria-label]')).toBeNull()
  })

  it('shows "no logs" message when rawLog is empty and in raw mode', () => {
    const emptyLog: ExecutionLogRead = {
      id: 'log-empty',
      session_id: 'sess-empty',
      system_instruction: null,
      user_prompt: null,
      logged_at: '2026-01-01T00:00:00Z',
    }
    render(<LogViewer executionLog={emptyLog} entries={[]} />)
    const switchEl = screen.getByRole('switch')
    fireEvent.click(switchEl)

    // t('agents.sessions.logViewer.noLogs') returns the key
    expect(screen.getByText('agents.sessions.logViewer.noLogs')).toBeDefined()
  })

  it('handles empty entries gracefully without crashing', () => {
    const emptyLog: ExecutionLogRead = {
      id: 'log-empty',
      session_id: 'sess-empty',
      system_instruction: null,
      user_prompt: null,
      logged_at: '2026-01-01T00:00:00Z',
    }
    expect(() =>
      render(<LogViewer executionLog={emptyLog} entries={[]} />)
    ).not.toThrow()
  })

  it('parsed summary identity is passed to LogSummaryPanel', () => {
    render(<LogViewer executionLog={EXECUTION_LOG} entries={LOG_ENTRIES} />)
    expect(screen.getByText('agent@example.com')).toBeDefined()
  })

  it('parsed summary role is passed to LogSummaryPanel', () => {
    render(<LogViewer executionLog={EXECUTION_LOG} entries={LOG_ENTRIES} />)
    expect(screen.getByText('DataAnalyst')).toBeDefined()
  })
})
