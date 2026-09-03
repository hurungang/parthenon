import type { RuntimeTopologyNode } from '../../types'

/**
 * Shared presentation helpers for the Agent Runtime Monitor.
 *
 * These map a runtime node's (kind, status) pair onto i18n keys and
 * colours.  They replace the inline helpers that lived in the retired
 * ``RuntimeTopologyDiagram`` component so the map canvas and the detail
 * bubble render the same labels/colours.
 */

/** Resolve a node's effective kind (defaults to "agent" for old payloads). */
export function nodeKind(node: RuntimeTopologyNode): 'agent' | 'conversation' | 'instance' {
  return node.kind ?? 'agent'
}

/** i18n key for the node's kind label. */
export function kindLabelKey(kind: 'agent' | 'conversation' | 'instance'): string {
  if (kind === 'conversation') return 'agents.sessions.runtimeKindConversation'
  if (kind === 'instance') return 'agents.sessions.runtimeKindInstance'
  return 'agents.sessions.runtimeKindAgent'
}

/** i18n key for the node's (kind, status) status label. */
export function statusLabelKey(
  status: string,
  kind: 'agent' | 'conversation' | 'instance',
): string {
  if (kind === 'conversation') {
    if (status === 'active') return 'agents.sessions.runtimeStatusActive'
    if (status === 'sleep') return 'agents.sessions.runtimeStatusSleep'
    if (status === 'closed') return 'agents.sessions.runtimeStatusClosed'
    if (status === 'archived') return 'agents.sessions.runtimeStatusArchived'
    if (status === 'error') return 'agents.sessions.runtimeStatusError'
  }
  if (kind === 'instance') {
    if (status === 'active') return 'agents.sessions.runtimeStatusActive'
    if (status === 'created') return 'agents.sessions.statusCreated'
    if (status === 'closed') return 'agents.sessions.runtimeStatusClosed'
    if (status === 'error') return 'agents.sessions.runtimeStatusError'
  }
  return `agents.sessions.status${status.charAt(0).toUpperCase()}${status.slice(1)}`
}

/** MUI Chip colour for a node's (kind, status). */
export function statusChipColor(
  status: string,
  kind: 'agent' | 'conversation' | 'instance',
): 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning' {
  if (kind === 'instance') {
    if (status === 'active') return 'secondary'
    if (status === 'created') return 'secondary'
    if (status === 'closed') return 'default'
    if (status === 'error') return 'error'
    return 'default'
  }
  if (kind === 'conversation') {
    if (status === 'active') return 'primary'
    if (status === 'sleep') return 'warning'
    if (status === 'closed' || status === 'archived') return 'success'
    if (status === 'error') return 'error'
    return 'default'
  }
  if (status === 'running') return 'info'
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'error'
  if (status === 'terminated') return 'warning'
  if (status === 'queued') return 'warning'
  return 'default'
}

/** Hex colour for a node's status dot (matches the legacy diagram palette). */
export function statusDotColor(
  status: string,
  kind: 'agent' | 'conversation' | 'instance',
): string {
  if (kind === 'instance') {
    if (status === 'active') return '#4527A0'
    if (status === 'created') return '#6A1B9A'
    if (status === 'closed') return '#283593'
    if (status === 'error') return '#B71C1C'
    return '#90A4AE'
  }
  if (kind === 'conversation') {
    if (status === 'active') return '#00695C'
    if (status === 'sleep') return '#F57F17'
    if (status === 'closed' || status === 'archived') return '#33691E'
    if (status === 'error') return '#B71C1C'
    return '#90A4AE'
  }
  if (status === 'running') return '#1565C0'
  if (status === 'completed') return '#2E7D32'
  if (status === 'failed') return '#C62828'
  if (status === 'terminated') return '#E65100'
  if (status === 'queued') return '#F57F17'
  return '#B0BEC5'
}
