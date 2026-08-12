import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import CronEditor from '../components/scheduling/CronEditor'

vi.mock('react-js-cron', () => ({ default: vi.fn(() => <div data-testid="cron-editor" />) }))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

describe('CronEditor', () => {
  it('renders without crashing', async () => {
    const onChange = vi.fn()
    const { container } = render(<CronEditor value="0 * * * *" onChange={onChange} />)
    expect(container.querySelector('[data-testid="cron-editor"]')).toBeTruthy()
  })
})
