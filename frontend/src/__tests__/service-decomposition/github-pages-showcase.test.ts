import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const currentDir = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(currentDir, '../../../../')

describe('GitHub Pages showcase static content', () => {
  it('contains architecture and walkthrough sections in site/index.html', () => {
    const html = readFileSync(resolve(repoRoot, 'site/index.html'), 'utf-8')

    expect(html).toContain('High-Level Architecture')
    expect(html).toContain('Architecture Diagram')
    expect(html).toContain('Security Deep Dive')
    expect(html).toContain('Demo Walkthroughs')
    expect(html).toContain('Integrate MCP Server')
    expect(html).toContain('Create Skill &amp; SOP')
    expect(html).toContain('Create Agent Roles')
    expect(html).toContain('Agent Types &amp; Trigger')
    expect(html).toContain('Execution Logs')
  })

  it('references all five screenshot placeholders', () => {
    const html = readFileSync(resolve(repoRoot, 'site/index.html'), 'utf-8')

    expect(html).toContain('/images/placeholder-mcp.svg')
    expect(html).toContain('/images/placeholder-skill-sop.svg')
    expect(html).toContain('/images/placeholder-agent-roles.svg')
    expect(html).toContain('/images/placeholder-agent-trigger.svg')
    expect(html).toContain('/images/placeholder-exec-logs.svg')
  })
})
