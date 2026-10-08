import { describe, it, expect } from 'vitest'
import {
  detectStatePlaceholders,
  detectStatePlaceholdersFromQuestions,
} from '../utils/decisionStatePaths'
import {
  RESERVED_SERVER_NAMES,
  DECISION_SERVER_SLUG,
  buildToolName,
} from '../utils/toolNaming'

describe('detectStatePlaceholders', () => {
  it('extracts backtick-quoted dot paths', () => {
    expect(detectStatePlaceholders('Check `input.tier` and `input.amount`')).toEqual([
      'input.tier',
      'input.amount',
    ])
  })

  it('extracts bracket paths', () => {
    expect(detectStatePlaceholders('First `input.items[0].sku` only')).toEqual([
      'input.items[0].sku',
    ])
  })

  it('dedupes repeated paths', () => {
    expect(detectStatePlaceholders('`a.b` then `a.b` then `a.b`')).toEqual(['a.b'])
  })

  it('returns empty for empty or backtick-free text', () => {
    expect(detectStatePlaceholders('')).toEqual([])
    expect(detectStatePlaceholders('nothing quoted')).toEqual([])
  })

  it('trims whitespace inside the backticks', () => {
    expect(detectStatePlaceholders('`  spaced.path  `')).toEqual(['spaced.path'])
  })

  it('collects paths across question instructions in first-seen order', () => {
    expect(
      detectStatePlaceholdersFromQuestions([
        'Given `state.risk`',
        null,
        'and `state.tier` then `state.risk` again',
      ]),
    ).toEqual(['state.risk', 'state.tier'])
  })
})

describe('toolNaming reserved server names (round 2)', () => {
  it('reserves "decision" alongside "system"', () => {
    expect(RESERVED_SERVER_NAMES).toContain('decision')
    expect(RESERVED_SERVER_NAMES).toContain('system')
  })

  it('exposes decision as the reserved decision server slug', () => {
    expect(DECISION_SERVER_SLUG).toBe('decision')
  })

  it('builds canonical decision____ tool names', () => {
    expect(buildToolName('decision', 'tool_a')).toBe('decision____tool_a')
  })
})
