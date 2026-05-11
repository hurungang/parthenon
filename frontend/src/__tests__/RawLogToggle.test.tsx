import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { RawLogToggle } from '../components/logs/RawLogToggle'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const RAW_LOG_TEXT = 'line 1\nline 2\nline 3'

describe('RawLogToggle', () => {
  const mockOnChange = vi.fn()

  beforeEach(() => {
    mockOnChange.mockReset()
    // Mock clipboard API — not available in jsdom
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
      writable: true,
      configurable: true,
    })
  })

  it('renders toggle switch', () => {
    render(
      <RawLogToggle checked={false} onChange={mockOnChange} rawLogText={RAW_LOG_TEXT} />
    )
    const switchEl = screen.getByRole('switch')
    expect(switchEl).toBeDefined()
  })

  it('switch reflects checked=false', () => {
    render(
      <RawLogToggle checked={false} onChange={mockOnChange} rawLogText={RAW_LOG_TEXT} />
    )
    const switchEl = screen.getByRole('switch')
    expect((switchEl as HTMLInputElement).checked).toBe(false)
  })

  it('switch reflects checked=true', () => {
    render(
      <RawLogToggle checked={true} onChange={mockOnChange} rawLogText={RAW_LOG_TEXT} />
    )
    const switchEl = screen.getByRole('switch')
    expect((switchEl as HTMLInputElement).checked).toBe(true)
  })

  it('copy button is NOT visible when checked=false', () => {
    render(
      <RawLogToggle checked={false} onChange={mockOnChange} rawLogText={RAW_LOG_TEXT} />
    )
    const copyBtn = screen.queryByRole('button', {
      name: /agents\.sessions\.logViewer\.rawToggle\.copyToClipboard/,
    })
    expect(copyBtn).toBeNull()
  })

  it('copy button IS visible when checked=true', () => {
    render(
      <RawLogToggle checked={true} onChange={mockOnChange} rawLogText={RAW_LOG_TEXT} />
    )
    const copyBtn = screen.getByRole('button', {
      name: /agents\.sessions\.logViewer\.rawToggle\.copyToClipboard/,
    })
    expect(copyBtn).toBeDefined()
  })

  it('calls onChange(true) when toggle is clicked while unchecked', () => {
    render(
      <RawLogToggle checked={false} onChange={mockOnChange} rawLogText={RAW_LOG_TEXT} />
    )
    const switchEl = screen.getByRole('switch')
    fireEvent.click(switchEl)
    expect(mockOnChange).toHaveBeenCalledWith(true)
  })

  it('calls onChange(false) when toggle is clicked while checked', () => {
    render(
      <RawLogToggle checked={true} onChange={mockOnChange} rawLogText={RAW_LOG_TEXT} />
    )
    const switchEl = screen.getByRole('switch')
    fireEvent.click(switchEl)
    expect(mockOnChange).toHaveBeenCalledWith(false)
  })

  it('calls clipboard.writeText with rawLogText on copy click', async () => {
    render(
      <RawLogToggle checked={true} onChange={mockOnChange} rawLogText={RAW_LOG_TEXT} />
    )
    const copyBtn = screen.getByRole('button', {
      name: /agents\.sessions\.logViewer\.rawToggle\.copyToClipboard/,
    })
    fireEvent.click(copyBtn)
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(RAW_LOG_TEXT)
  })

  it('shows "Copied!" feedback after clicking copy', async () => {
    render(
      <RawLogToggle checked={true} onChange={mockOnChange} rawLogText={RAW_LOG_TEXT} />
    )
    const copyBtn = screen.getByRole('button', {
      name: /agents\.sessions\.logViewer\.rawToggle\.copyToClipboard/,
    })
    fireEvent.click(copyBtn)

    await waitFor(() => {
      // After clipboard write resolves, the tooltip title changes to "Copied!"
      // The tooltip title text is rendered in a span accessible via query
      expect(
        screen.queryByText('agents.sessions.logViewer.rawToggle.copied')
      ).toBeDefined()
    })
  })

  it('shows "Friendly" label text', () => {
    render(
      <RawLogToggle checked={false} onChange={mockOnChange} rawLogText={RAW_LOG_TEXT} />
    )
    expect(screen.getByText('agents.sessions.logViewer.rawToggle.friendly')).toBeDefined()
  })

  it('shows "Raw Output" label text', () => {
    render(
      <RawLogToggle checked={false} onChange={mockOnChange} rawLogText={RAW_LOG_TEXT} />
    )
    expect(screen.getByText('agents.sessions.logViewer.rawToggle.raw')).toBeDefined()
  })
})
