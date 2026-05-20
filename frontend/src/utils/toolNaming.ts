export function canonicalizeToolName(name: string): string {
  if (!name) return name

  if (name === 'save_result' || name === 'send_notification' || name === 'get_recipient_group') {
    return `system____${name}`
  }

  if (name.includes('____')) {
    return name
  }

  if (name.includes('/')) {
    const [server, tool] = name.split('/', 2)
    if (server && tool) {
      return `${server}____${tool}`
    }
  }

  return name
}
