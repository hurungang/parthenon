import { describe, expect, it } from 'vitest'

import { canonicalizeToolName } from '../utils/toolNaming'

describe('system tool naming', () => {
  it('keeps legacy save_result canonicalization for backward compatibility', () => {
    expect(canonicalizeToolName('save_result')).toBe('system____save_result')
  })

  it('does not remap save_data/get_data/get_output in frontend naming helper', () => {
    expect(canonicalizeToolName('save_data')).toBe('save_data')
    expect(canonicalizeToolName('get_data')).toBe('get_data')
    expect(canonicalizeToolName('get_output')).toBe('get_output')
  })
})
