import { describe, it, expect } from 'vitest'

/**
 * The legacy ModelUsageGuardrailDialog has been replaced by the inline
 * `AddGuardrailForm`. The unit-select default (`k`), per-period create call,
 * and edit-mode freeze semantics are now covered by `AddGuardrailForm.test.tsx`
 * and `VendorModelGuardrailPanel.test.tsx`.
 *
 * This file is kept as a no-op skip so historical test runners don't fail
 * after the refactor.
 */
describe('ModelUsageGuardrailDialog - unit selector (legacy)', () => {
  it.skip('rendered a unit Select with default value k (covered by AddGuardrailForm.test.tsx)', () => {
    expect(true).toBe(true)
  })

  it.skip('dispatched unit: "k" in the payload by default (covered by AddGuardrailForm.test.tsx)', () => {
    expect(true).toBe(true)
  })

  it.skip('let the operator change the unit and the payload reflected the choice (covered by AddGuardrailForm.test.tsx)', () => {
    expect(true).toBe(true)
  })

  it.skip('froze the unit selector in edit mode (covered by VendorModelGuardrailPanel.test.tsx)', () => {
    expect(true).toBe(true)
  })
})
