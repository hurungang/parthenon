/**
 * Assistant session lifecycle flags (FIX-20261031-091657, Defect B.2).
 *
 * After an explicit END the user expects a NEW session on next open for that
 * agent type — not an auto-resume of some older stale ACTIVE session. A
 * per-agent-type flag in localStorage records "this agent type's session was
 * explicitly ended"; AppShell consumes (clears) it on next open and skips the
 * resume-latest-active resolution. Plain exit never sets the flag, keeping
 * the existing resume behaviour.
 */

const FORCE_NEW_FLAG_PREFIX = 'parthenon_assistant_force_new_'

export function markAssistantSessionEnded(agentTypeId: string): void {
  if (!agentTypeId || typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(FORCE_NEW_FLAG_PREFIX + agentTypeId, '1')
  } catch {
    // storage unavailable — fall back to resume behaviour
  }
}

/** True when the previous explicit END requested a fresh session; clears the flag. */
export function consumeForceNewSessionFlag(agentTypeId: string): boolean {
  if (!agentTypeId || typeof localStorage === 'undefined') return false
  const key = FORCE_NEW_FLAG_PREFIX + agentTypeId
  try {
    if (localStorage.getItem(key) === '1') {
      localStorage.removeItem(key)
      return true
    }
  } catch {
    return false
  }
  return false
}
