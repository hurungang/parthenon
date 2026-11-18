/**
 * Shared vocabulary for the durable conversational-turn resume projection
 * (resumable-agent-turn-persistence, Phase 6).
 *
 * One vocabulary is used by three surfaces so they can never drift apart:
 * - `useChatSession` (status model + persisted `activity_state` hydration),
 * - `ConversationDialog` (waiting / resumed / resolved / no-longer-resumable),
 * - `ConversationSessionsTab` (badges projected by the sessions API).
 */

/** Durable lifecycle state of a paused conversational turn. */
export type ResumeState = 'waiting_for_human' | 'resuming' | 'resolved' | 'unresumable'

/** Terminal outcome recorded on the resume record (server enum). */
export type ResumeOutcome =
  | 'approved_applied'
  | 'denied'
  | 'cancelled'
  | 'expired'
  | 'superseded'
  | 'resume_failed'

const RESUME_STATES: readonly ResumeState[] = [
  'waiting_for_human',
  'resuming',
  'resolved',
  'unresumable',
]

const RESUME_OUTCOMES: readonly ResumeOutcome[] = [
  'approved_applied',
  'denied',
  'cancelled',
  'expired',
  'superseded',
  'resume_failed',
]

/** Normalizes an unknown wire value into a `ResumeState` (or null). */
export function normalizeResumeState(value: unknown): ResumeState | null {
  if (typeof value !== 'string') {
    return null
  }
  const trimmed = value.trim()
  return RESUME_STATES.includes(trimmed as ResumeState) ? (trimmed as ResumeState) : null
}

/** Normalizes an unknown wire value into a `ResumeOutcome` (or null). */
export function normalizeResumeOutcome(value: unknown): ResumeOutcome | null {
  if (typeof value !== 'string') {
    return null
  }
  const trimmed = value.trim()
  return RESUME_OUTCOMES.includes(trimmed as ResumeOutcome) ? (trimmed as ResumeOutcome) : null
}

/**
 * i18n keys for the four state labels rendered by the conversation dialog
 * (status chip + activity bubble vocabulary).
 */
export const RESUME_STATE_LABEL_KEYS: Record<ResumeState, string> = {
  waiting_for_human: 'conversations.sessions.resumeState.waiting',
  resuming: 'conversations.sessions.resumeState.resumed',
  resolved: 'conversations.sessions.resumeState.resolved',
  unresumable: 'conversations.sessions.resumeState.unresumable',
}

/** i18n keys for the sessions-list badges (same vocabulary, own key group). */
export const RESUME_BADGE_LABEL_KEYS: Record<ResumeState, string> = {
  waiting_for_human: 'conversations.sessions.resumeBadge.waiting',
  resuming: 'conversations.sessions.resumeBadge.resumed',
  resolved: 'conversations.sessions.resumeBadge.resolved',
  unresumable: 'conversations.sessions.resumeBadge.unresumable',
}

/** MUI Chip colour per resume state — mirrors the prototype palette. */
export const RESUME_STATE_CHIP_COLORS: Record<
  ResumeState,
  'default' | 'primary' | 'secondary' | 'success' | 'warning' | 'error'
> = {
  waiting_for_human: 'warning',
  resuming: 'secondary',
  resolved: 'success',
  unresumable: 'error',
}

/**
 * True when a projected resume state means the operator's confirmation is the
 * thing the turn is waiting on. A `resolved` / `unresumable` turn is never
 * displayed as "waiting for your input".
 */
export function isWaitingResumeState(state: ResumeState | null | undefined): boolean {
  return state === 'waiting_for_human'
}

/**
 * Minimal structural shape of the chat status needed to decide whether a pause
 * is answerable. Kept structural (not `ChatStatus`) so pure UI modules never
 * depend on the WebSocket hook module.
 */
export interface ResumeStatusProjection {
  kind: string
  activeResumeId?: string | null
  pendingIntervention?: boolean
  persisted?: boolean
}

/** True when the status is backed by a live durable resume record. */
export function hasLiveResume(status: ResumeStatusProjection | null): boolean {
  return Boolean(status?.activeResumeId)
}

/**
 * True when a pause may be rendered as "waiting for your input".
 *
 * A pause is answerable only when a durable resume record backs it. The two
 * exceptions are deliberate:
 * - the hydrated `pendingIntervention` flag (the server only sets it for a live
 *   resume id), and
 * - a *live* (non-hydrated) `waiting_for_human` wire status, which the runtime
 *   emits only after the resume index write, immediately before the
 *   `intervene_request` arrives.
 *
 * A stale `waiting_for_human` restored from persisted activity without a live
 * resume id therefore never renders as waiting.
 */
export function isActionableWaiting(status: ResumeStatusProjection | null): boolean {
  if (!status || status.kind !== 'waiting_for_human') {
    return false
  }
  if (status.activeResumeId) {
    return true
  }
  if (status.pendingIntervention) {
    return true
  }
  return status.persisted !== true
}

