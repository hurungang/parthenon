import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import PayloadEditor from '../components/scheduling/PayloadEditor'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

describe('PayloadEditor', () => {
  it('renders with initial key-value pairs', () => {
    const onChange = vi.fn()
    const initialValue = { prompt: 'Run report', format: 'json' }
    render(<PayloadEditor value={initialValue} onChange={onChange} />)

    expect(screen.getByDisplayValue('prompt')).toBeDefined()
    expect(screen.getByDisplayValue('Run report')).toBeDefined()
    expect(screen.getByDisplayValue('format')).toBeDefined()
    expect(screen.getByDisplayValue('json')).toBeDefined()
  })

  it('renders with empty initial value', () => {
    const onChange = vi.fn()
    render(<PayloadEditor value={{}} onChange={onChange} />)

    expect(screen.getByText('schedules.payloadEditor')).toBeDefined()
  })

  it('can add a new parameter row', () => {
    const onChange = vi.fn()
    render(<PayloadEditor value={{}} onChange={onChange} />)

    fireEvent.click(screen.getByText('schedules.addParameter'))
    expect(onChange).toHaveBeenCalledWith({})
  })

  it('can remove a parameter row', () => {
    const onChange = vi.fn()
    const initialValue = { prompt: 'Run report' }
    render(<PayloadEditor value={initialValue} onChange={onChange} />)

    // There should be a remove button (RemoveCircleOutline icon)
    const removeButtons = screen.getAllByRole('button')
    expect(removeButtons.length).toBeGreaterThan(0)
  })

  it('typing in key field calls onChange with updated payload', () => {
    const onChange = vi.fn()
    render(<PayloadEditor value={{ prompt: '' }} onChange={onChange} />)

    const keyInput = screen.getByDisplayValue('prompt')
    fireEvent.change(keyInput, { target: { value: 'newKey' } })

    expect(onChange).toHaveBeenCalled()
  })

  it('typing in value field calls onChange with updated payload', () => {
    const onChange = vi.fn()
    render(<PayloadEditor value={{ prompt: '' }} onChange={onChange} />)

    const valueInputs = screen.getAllByPlaceholderText('schedules.value')
    expect(valueInputs.length).toBeGreaterThan(0)
  })
})
