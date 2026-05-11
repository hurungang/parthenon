import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LogSummaryPanel } from '../components/logs/LogSummaryPanel'
import type { LogSummary } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

function makeSummary(overrides: Partial<LogSummary> = {}): LogSummary {
  return {
    identity: 'agent@example.com',
    role: 'DataAnalyst',
    model: 'gpt-4o',
    sopsSkills: [],
    planCompleted: 0,
    planTotal: 0,
    resultStatus: 'unknown',
    startedAt: null,
    completedAt: null,
    ...overrides,
  }
}

describe('LogSummaryPanel', () => {
  it('renders identity value', () => {
    render(<LogSummaryPanel summary={makeSummary({ identity: 'my-agent@example.com' })} />)
    expect(screen.getByText('my-agent@example.com')).toBeDefined()
  })

  it('renders role value', () => {
    render(<LogSummaryPanel summary={makeSummary({ role: 'ResearchAnalyst' })} />)
    expect(screen.getByText('ResearchAnalyst')).toBeDefined()
  })

  it('renders model value', () => {
    render(<LogSummaryPanel summary={makeSummary({ model: 'claude-3-opus' })} />)
    expect(screen.getByText('claude-3-opus')).toBeDefined()
  })

  it('shows N/A placeholder for null identity', () => {
    render(<LogSummaryPanel summary={makeSummary({ identity: null })} />)
    // t('agents.sessions.logViewer.summary.notAvailable') returns the key itself
    const naElements = screen.getAllByText('agents.sessions.logViewer.summary.notAvailable')
    expect(naElements.length).toBeGreaterThanOrEqual(1)
  })

  it('shows N/A placeholder for null role', () => {
    render(<LogSummaryPanel summary={makeSummary({ role: null })} />)
    const naElements = screen.getAllByText('agents.sessions.logViewer.summary.notAvailable')
    expect(naElements.length).toBeGreaterThanOrEqual(1)
  })

  it('shows N/A placeholder for null model', () => {
    render(<LogSummaryPanel summary={makeSummary({ model: null })} />)
    const naElements = screen.getAllByText('agents.sessions.logViewer.summary.notAvailable')
    expect(naElements.length).toBeGreaterThanOrEqual(1)
  })

  it('renders each SOP/skill as a separate label', () => {
    render(<LogSummaryPanel summary={makeSummary({ sopsSkills: ['DataPipeline', 'ReportGen'] })} />)
    expect(screen.getByText('DataPipeline')).toBeDefined()
    expect(screen.getByText('ReportGen')).toBeDefined()
  })

  it('does not render SOPs/skills section when sopsSkills is empty', () => {
    render(<LogSummaryPanel summary={makeSummary({ sopsSkills: [] })} />)
    // The section label should not appear when no sopsSkills
    expect(
      screen.queryByText('agents.sessions.logViewer.summary.sopsSkills')
    ).toBeNull()
  })

  it('shows SOPs/skills section label when sopsSkills is non-empty', () => {
    render(<LogSummaryPanel summary={makeSummary({ sopsSkills: ['ToolA'] })} />)
    expect(screen.getByText('agents.sessions.logViewer.summary.sopsSkills')).toBeDefined()
  })

  it('shows success badge for success result status', () => {
    render(<LogSummaryPanel summary={makeSummary({ resultStatus: 'success' })} />)
    expect(screen.getByText('agents.sessions.logViewer.summary.statusSuccess')).toBeDefined()
  })

  it('shows failure badge for failure result status', () => {
    render(<LogSummaryPanel summary={makeSummary({ resultStatus: 'failure' })} />)
    expect(screen.getByText('agents.sessions.logViewer.summary.statusFailure')).toBeDefined()
  })

  it('shows running badge for running result status', () => {
    render(<LogSummaryPanel summary={makeSummary({ resultStatus: 'running' })} />)
    expect(screen.getByText('agents.sessions.logViewer.summary.statusRunning')).toBeDefined()
  })

  it('shows unknown badge for unknown result status', () => {
    render(<LogSummaryPanel summary={makeSummary({ resultStatus: 'unknown' })} />)
    expect(screen.getByText('agents.sessions.logViewer.summary.statusUnknown')).toBeDefined()
  })

  it('shows plan progress value when planTotal > 0', () => {
    render(
      <LogSummaryPanel summary={makeSummary({ planCompleted: 2, planTotal: 4 })} />
    )
    // t('agents.sessions.logViewer.summary.planProgressValue', { completed: 2, total: 4 })
    // With the key-returning mock, the key itself is rendered
    expect(
      screen.getByText('agents.sessions.logViewer.summary.planProgressValue')
    ).toBeDefined()
  })

  it('shows N/A for plan progress when planTotal is 0', () => {
    render(
      <LogSummaryPanel summary={makeSummary({ planCompleted: 0, planTotal: 0 })} />
    )
    const naElements = screen.getAllByText('agents.sessions.logViewer.summary.notAvailable')
    expect(naElements.length).toBeGreaterThanOrEqual(1)
  })

  it('renders the summary section title', () => {
    render(<LogSummaryPanel summary={makeSummary()} />)
    expect(screen.getByText('agents.sessions.logViewer.summary.title')).toBeDefined()
  })
})
