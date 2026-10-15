import { describe, it, expect } from 'vitest'
import {
  detectStatePlaceholders,
  detectStatePlaceholdersFromQuestions,
  resolveStateMapping,
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

describe('resolveStateMapping (state maps from the input only)', () => {
  it('auto-matches same-named keys silently', () => {
    expect(resolveStateMapping(['amount', 'tier'], [], ['amount', 'tier', 'x'])).toEqual({
      matched: { amount: 'amount', tier: 'tier' },
      unmatched: [],
    })
  })

  it('reports unmatched keys for the UI mapper', () => {
    expect(resolveStateMapping(['aaa'], [], ['bbb'])).toEqual({
      matched: {},
      unmatched: ['aaa'],
    })
  })

  it('explicit rename mappings win over 1:1', () => {
    expect(
      resolveStateMapping(['aaa'], [{ state_key: 'aaa', key: 'bbb' }], ['bbb']),
    ).toEqual({ matched: { aaa: 'bbb' }, unmatched: [] })
  })

  it('explicit mappings to unknown fields stay unmatched', () => {
    expect(
      resolveStateMapping(['aaa'], [{ state_key: 'aaa', key: 'nope' }], ['bbb']),
    ).toEqual({ matched: {}, unmatched: ['aaa'] })
  })

  it('dedupes preset keys and placeholders in first-seen order', () => {
    const result = resolveStateMapping(
      ['risk', 'amount'],
      [{ state_key: 'risk', key: 'risk' }],
      ['risk', 'amount'],
    )
    expect(Object.keys(result.matched)).toEqual(['risk', 'amount'])
    expect(result.unmatched).toEqual([])
  })

  it('handles empty inputs', () => {
    expect(resolveStateMapping([], [], [])).toEqual({ matched: {}, unmatched: [] })
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
