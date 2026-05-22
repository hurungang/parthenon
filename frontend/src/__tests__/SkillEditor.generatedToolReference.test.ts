import { describe, expect, it } from 'vitest'
import {
  buildGeneratedToolSectionFromSelection,
  extractGeneratedToolSection,
} from '../pages/skills/SkillEditor'

describe('SkillEditor generated tool reference extraction', () => {
  it('uses the last generated Tools section when instructions also contain Tools headers', () => {
    const payload = [
      '# Agent Instructions',
      '',
      '## Tools',
      '### `docs____search`',
      'User-authored tools notes.',
      '',
      '## Behavior',
      'Be concise.',
      '',
      '## Tools',
      '### `system____save_result`',
      'Save final output.',
      '### `system____send_notification`',
      'Send notifications.',
    ].join('\n')

    const section = extractGeneratedToolSection(payload)

    expect(section).toContain('system____save_result')
    expect(section).toContain('system____send_notification')
    expect(section).not.toContain('docs____search')
  })

  it('returns full payload when tools section starts at file beginning', () => {
    const payload = '## Tools\n### `system____save_result`\nSave final output.'
    expect(extractGeneratedToolSection(payload)).toBe(payload)
  })

  it('returns null when no Tools section exists', () => {
    expect(extractGeneratedToolSection('No tool reference here.')).toBeNull()
  })

  it('builds tool reference directly from selected tools with schema', () => {
    const selectedToolIds = ['system-send', 'mcp-search']
    const tools = [
      {
        id: 'system-send',
        name: 'system____send_notification',
        description: 'Send a notification to specified channels',
        input_schema: {
          type: 'object',
          properties: {
            recipient_group_id: { type: 'string' },
            subject: { type: 'string' },
            body: { type: 'string' },
          },
          required: ['recipient_group_id', 'subject', 'body'],
        },
      },
      {
        id: 'mcp-search',
        name: 'docs____search',
        description: 'Search docs',
        input_schema: {
          type: 'object',
          properties: { query: { type: 'string' } },
          required: ['query'],
        },
      },
    ]

    const section = buildGeneratedToolSectionFromSelection(selectedToolIds, tools)

    expect(section).toContain('## Tools')
    expect(section).toContain('system____send_notification')
    expect(section).toContain('recipient_group_id')
    expect(section).toContain('docs____search')
    expect(section).toContain('query')
  })

  it('returns null when no selected tools can be resolved', () => {
    const section = buildGeneratedToolSectionFromSelection(['unknown-id'], [
      {
        id: 'known-id',
        name: 'docs____search',
        description: 'Search docs',
        input_schema: null,
      },
    ])

    expect(section).toBeNull()
  })
})
