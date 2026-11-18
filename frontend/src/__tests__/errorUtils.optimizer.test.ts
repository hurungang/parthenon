import { describe, it, expect } from 'vitest'
import {
  CHAT_BLOCKED_REASON_DECISION_PENDING,
  OPTIMIZER_CHAT_ERROR_CODE_MODEL_NOT_CONFIGURED,
  OPTIMIZER_CHAT_ERROR_CODE_MODEL_NOT_ENABLED,
  OPTIMIZER_CHAT_ERROR_CODE_OUT_OF_SCOPE,
  OPTIMIZER_CHAT_ERROR_CODE_PERMISSION_DENIED,
  OPTIMIZER_REASON_MODEL_NOT_CONFIGURED,
  OPTIMIZER_REASON_MODEL_NOT_ENABLED,
  OPTIMIZER_REASON_NO_SUCCESSFUL_EXECUTION,
  OPTIMIZER_REASON_OUT_OF_SCOPE,
  extractOptimizerRefusal,
  isDecisionPendingBlock,
  isOptimizerChatErrorCode,
  isOptimizerModelReasonCode,
} from '../utils/errorUtils'

/**
 * Optimizer error extraction (7.6).
 *
 * Optimization errors arrive in several shapes — a conversation `422
 * {detail: {error, reason}}`, an internal `412
 * {detail: {error: 'optimizer_model_unavailable', reason_code, reason}}`, a
 * system-tool `{status: 'refused', reason_code, reason}` and WS
 * `chat_error` / `chat_blocked` payloads. All of them must reduce to ONE
 * reason vocabulary, and anything else must return null so the standard dialog
 * error handling stays in charge.
 */

describe('isOptimizerModelReasonCode', () => {
  it('accepts exactly the two "no usable optimizer model" codes', () => {
    expect(isOptimizerModelReasonCode(OPTIMIZER_REASON_MODEL_NOT_CONFIGURED)).toBe(true)
    expect(isOptimizerModelReasonCode(OPTIMIZER_REASON_MODEL_NOT_ENABLED)).toBe(true)
    // Same literal as the chat_error code — one vocabulary, not two.
    expect(OPTIMIZER_REASON_MODEL_NOT_CONFIGURED).toBe(
      OPTIMIZER_CHAT_ERROR_CODE_MODEL_NOT_CONFIGURED,
    )
    expect(OPTIMIZER_REASON_MODEL_NOT_ENABLED).toBe(OPTIMIZER_CHAT_ERROR_CODE_MODEL_NOT_ENABLED)
  })

  it('rejects every other code (authoring reasons, scope, permission, empty)', () => {
    expect(isOptimizerModelReasonCode('authoring_model_not_configured')).toBe(false)
    expect(isOptimizerModelReasonCode('authoring_model_not_enabled')).toBe(false)
    expect(isOptimizerModelReasonCode(OPTIMIZER_REASON_NO_SUCCESSFUL_EXECUTION)).toBe(false)
    expect(isOptimizerModelReasonCode(OPTIMIZER_REASON_OUT_OF_SCOPE)).toBe(false)
    expect(isOptimizerModelReasonCode('')).toBe(false)
    expect(isOptimizerModelReasonCode(null)).toBe(false)
    expect(isOptimizerModelReasonCode(undefined)).toBe(false)
  })
})

describe('isOptimizerChatErrorCode', () => {
  it('accepts the four optimization-only chat_error codes', () => {
    for (const code of [
      OPTIMIZER_CHAT_ERROR_CODE_MODEL_NOT_CONFIGURED,
      OPTIMIZER_CHAT_ERROR_CODE_MODEL_NOT_ENABLED,
      OPTIMIZER_CHAT_ERROR_CODE_OUT_OF_SCOPE,
      OPTIMIZER_CHAT_ERROR_CODE_PERMISSION_DENIED,
    ]) {
      expect(isOptimizerChatErrorCode(code)).toBe(true)
    }
    expect(OPTIMIZER_CHAT_ERROR_CODE_OUT_OF_SCOPE).toBe('optimization_out_of_scope')
    expect(OPTIMIZER_CHAT_ERROR_CODE_PERMISSION_DENIED).toBe('optimization_permission_denied')
  })

  it('leaves ordinary chat errors (guardrail, timeout) to the generic presentation', () => {
    expect(isOptimizerChatErrorCode('guardrail_max_iterations')).toBe(false)
    expect(isOptimizerChatErrorCode('timeout_or_failed')).toBe(false)
    expect(isOptimizerChatErrorCode(null)).toBe(false)
    expect(isOptimizerChatErrorCode(undefined)).toBe(false)
  })
})

describe('isDecisionPendingBlock', () => {
  it('recognises the decision-pending refusal (and the legacy intervention_pending alias)', () => {
    expect(isDecisionPendingBlock(CHAT_BLOCKED_REASON_DECISION_PENDING)).toBe(true)
    expect(CHAT_BLOCKED_REASON_DECISION_PENDING).toBe('decision_pending')
    expect(isDecisionPendingBlock('intervention_pending')).toBe(true)
  })

  it('ignores unrelated block reasons', () => {
    expect(isDecisionPendingBlock('turn_in_flight')).toBe(false)
    expect(isDecisionPendingBlock('')).toBe(false)
    expect(isDecisionPendingBlock(null)).toBe(false)
    expect(isDecisionPendingBlock(undefined)).toBe(false)
  })
})

describe('extractOptimizerRefusal', () => {
  it('extracts a conversation 422 refusal (detail with error + reason)', () => {
    const refusal = extractOptimizerRefusal({
      response: {
        status: 422,
        data: {
          detail: {
            error: 'optimization_unavailable',
            reason: 'No successful execution yet.',
          },
        },
      },
    })

    expect(refusal).toEqual({
      code: 'optimization_unavailable',
      reason_code: null,
      reason: 'No successful execution yet.',
    })
  })

  it('extracts the internal 412 optimizer_model_unavailable payload with its reason code', () => {
    const refusal = extractOptimizerRefusal({
      response: {
        status: 412,
        data: {
          detail: {
            error: 'optimizer_model_unavailable',
            reason_code: OPTIMIZER_REASON_MODEL_NOT_ENABLED,
            reason: 'The saved optimizer model is no longer available.',
          },
        },
      },
    })

    expect(refusal?.code).toBe('optimizer_model_unavailable')
    expect(refusal?.reason_code).toBe(OPTIMIZER_REASON_MODEL_NOT_ENABLED)
    expect(isOptimizerModelReasonCode(refusal?.reason_code)).toBe(true)
  })

  it('extracts a system-tool refusal (status refused + reason_code)', () => {
    const refusal = extractOptimizerRefusal({
      response: {
        data: {
          status: 'refused',
          reason_code: OPTIMIZER_REASON_OUT_OF_SCOPE,
          reason: 'That resource belongs to another agent type.',
        },
      },
    })

    expect(refusal).toEqual({
      code: 'refused',
      reason_code: OPTIMIZER_REASON_OUT_OF_SCOPE,
      reason: 'That resource belongs to another agent type.',
    })
  })

  it('extracts a bare refusal payload (no axios envelope)', () => {
    const refusal = extractOptimizerRefusal({
      status: 'refused',
      reason_code: 'out_of_scope',
      reason: 'Not this agent type.',
    })
    expect(refusal?.code).toBe('refused')
    expect(refusal?.reason_code).toBe('out_of_scope')
  })

  it('extracts a WS chat_error payload mapped to {code, message} without inventing a reason', () => {
    const refusal = extractOptimizerRefusal({
      code: OPTIMIZER_CHAT_ERROR_CODE_OUT_OF_SCOPE,
      message: 'Nothing was changed.',
    })
    expect(refusal?.code).toBe(OPTIMIZER_CHAT_ERROR_CODE_OUT_OF_SCOPE)
    expect(refusal?.reason).toBeNull()
  })

  it('returns null for non-optimizer failures so standard dialog handling applies', () => {
    expect(extractOptimizerRefusal(null)).toBeNull()
    expect(extractOptimizerRefusal(undefined)).toBeNull()
    expect(extractOptimizerRefusal('boom')).toBeNull()
    expect(extractOptimizerRefusal({})).toBeNull()
    expect(
      extractOptimizerRefusal({ response: { data: { detail: 'plain fastapi detail' } } }),
    ).toBeNull()
    expect(extractOptimizerRefusal({ response: { data: { detail: {} } } })).toBeNull()
    expect(extractOptimizerRefusal([1, 2, 3])).toBeNull()
  })

  it('prefers a present `error` discriminator over a fallback `code`', () => {
    const refusal = extractOptimizerRefusal({
      response: {
        data: { error: 'optimizer_model_unavailable', code: 'ignored', reason: 'x' },
      },
    })
    expect(refusal?.code).toBe('optimizer_model_unavailable')
  })
})
