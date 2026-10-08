/**
 * Canonical tool-name helpers shared by tool pickers and permission UIs.
 *
 * Tool names use the canonical `server____tool` format (four underscores).
 * Reserved server slugs cannot be used for custom MCP servers:
 * - `system`   — built-in system tools (`system____save_data`, …)
 * - `decision` — user-defined decision tools (`decision____<name>`)
 */
export const TOOL_SEPARATOR = '____'

export const RESERVED_SERVER_NAMES: readonly string[] = ['system', 'decision']

export const DECISION_SERVER_SLUG = 'decision'

export function buildToolName(server: string, tool: string): string {
  return `${server}${TOOL_SEPARATOR}${tool}`
}

export function isReservedServerName(name: string): boolean {
  return RESERVED_SERVER_NAMES.includes(name)
}

export function canonicalizeToolName(name: string): string {
  if (!name) return name

  if (name === 'save_result' || name === 'send_notification' || name === 'get_recipient_group') {
    return `system____${name}`
  }

  if (name.includes(TOOL_SEPARATOR)) {
    return name
  }

  if (name.includes('/')) {
    const [server, tool] = name.split('/', 2)
    if (server && tool) {
      return `${server}${TOOL_SEPARATOR}${tool}`
    }
  }

  return name
}
