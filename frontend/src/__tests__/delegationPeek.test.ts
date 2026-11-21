import { describe, it, expect } from 'vitest'
import {
  DELEGATION_LIFECYCLE_EVENT_TYPES,
  DIRECT_CHILD_PEEK_EVENT_TYPES,
  filterDirectChildPeekEntries,
  isDelegationToolEntry,
  isDelegationToolName,
  isDirectChildPeekEntry,
} from '../services/delegationPeek'
import type { ExecutionLogEntry } from '../types'

function makeEntry(overrides: Partial<ExecutionLogEntry> = {}): ExecutionLogEntry {
  return {
    id: 'entry-1',
    timestamp: '2026-01-01T00:00:00Z',
    event_type: 'observe',
    log_level: 'INFO',
    message: 'entry',
    data: {},
    ...overrides,
  }
}

describe('delegationPeek', () => {
  describe('isDelegationToolName', () => {
    it('recognises the canonical agent____<slug> prefix', () => {
      expect(isDelegationToolName('agent____research-helper')).toBe(true)
    })

    it('recognises the legacy agent__<slug> prefix', () => {
      expect(isDelegationToolName('agent__research-helper')).toBe(true)
    })

    it('recognises sanitized variants (invalid chars replaced by underscores)', () => {
      expect(isDelegationToolName('agent____research_helper')).toBe(true)
      expect(isDelegationToolName('agent__research_helper')).toBe(true)
    })

    it('rejects non-delegation tool names and empty values', () => {
      expect(isDelegationToolName('server____search')).toBe(false)
      expect(isDelegationToolName('agent_tool')).toBe(false)
      expect(isDelegationToolName('')).toBe(false)
      expect(isDelegationToolName(null)).toBe(false)
      expect(isDelegationToolName(undefined)).toBe(false)
    })
  })

  describe('isDelegationToolEntry', () => {
    it('detects delegation tool calls by tool name in data.tool', () => {
      const entry = makeEntry({
        event_type: 'tool_call',
        data: { tool: 'agent____research-helper' },
      })
      expect(isDelegationToolEntry(entry)).toBe(true)
    })

    it('detects delegation tool calls by legacy tool name in data.tool_name', () => {
      const entry = makeEntry({
        event_type: 'tool_call',
        data: { tool_name: 'agent__research-helper' },
      })
      expect(isDelegationToolEntry(entry)).toBe(true)
    })

    it('detects delegation tool calls via the raw tool name when canonicalisation missed', () => {
      const entry = makeEntry({
        event_type: 'tool_call',
        data: { tool: 'unknown_tool', tool_raw: 'agent__research-helper' },
      })
      expect(isDelegationToolEntry(entry)).toBe(true)
    })

    it('detects delegation tool responses via data.delegation_target', () => {
      const entry = makeEntry({
        event_type: 'tool_response',
        data: { delegation_target: 'research-helper', response_preview: '{}' },
      })
      expect(isDelegationToolEntry(entry)).toBe(true)
    })

    it('detects delegation tool responses by tool name', () => {
      const entry = makeEntry({
        event_type: 'tool_response',
        data: { tool: 'agent____research-helper' },
      })
      expect(isDelegationToolEntry(entry)).toBe(true)
    })

    it('does not treat non-tool events as delegation tool entries', () => {
      const entry = makeEntry({
        event_type: 'llm_request',
        data: { tool: 'agent____research-helper' },
      })
      expect(isDelegationToolEntry(entry)).toBe(false)
    })

    it('does not treat ordinary MCP tool calls as delegation', () => {
      const entry = makeEntry({
        event_type: 'tool_call',
        data: { tool: 'server____search' },
      })
      expect(isDelegationToolEntry(entry)).toBe(false)
    })
  })

  describe('allow-list', () => {
    it('keeps every allow-listed non-delegation event type', () => {
      const expected = [
        'agent_initialized',
        'tool_call',
        'tool_response',
        'llm_request',
        'llm_response',
        'observe',
        'session_completed',
      ]
      expect([...DIRECT_CHILD_PEEK_EVENT_TYPES].sort()).toEqual([...expected].sort())
      for (const eventType of expected) {
        expect(isDirectChildPeekEntry(makeEntry({ event_type: eventType }))).toBe(true)
      }
    })

    it('excludes delegation lifecycle event types', () => {
      for (const eventType of DELEGATION_LIFECYCLE_EVENT_TYPES) {
        expect(isDirectChildPeekEntry(makeEntry({ event_type: eventType }))).toBe(false)
      }
    })

    it('excludes unlisted (non-peek) event types', () => {
      expect(isDirectChildPeekEntry(makeEntry({ event_type: 'tool_error' }))).toBe(false)
      expect(isDirectChildPeekEntry(makeEntry({ event_type: 'plan_injected' }))).toBe(false)
    })
  })

  describe('filterDirectChildPeekEntries', () => {
    it('returns only allow-listed, non-delegation entries in input order', () => {
      const entries = [
        makeEntry({ id: '1', event_type: 'agent_initialized', message: 'initialised' }),
        makeEntry({
          id: '2',
          event_type: 'tool_call',
          message: 'canonical delegation',
          data: { tool: 'agent____child-agent' },
        }),
        makeEntry({ id: '3', event_type: 'llm_request', message: 'model request' }),
        makeEntry({
          id: '4',
          event_type: 'tool_call',
          message: 'legacy delegation',
          data: { tool: 'agent__legacy-agent' },
        }),
        makeEntry({
          id: '5',
          event_type: 'tool_response',
          message: 'delegation response',
          data: { delegation_target: 'child-agent' },
        }),
        makeEntry({ id: '6', event_type: 'delegation_started', message: 'child delegated onward' }),
        makeEntry({
          id: '7',
          event_type: 'tool_call',
          message: 'mcp search',
          data: { tool: 'server____search' },
        }),
        makeEntry({ id: '8', event_type: 'session_completed', message: 'completed' }),
      ]
      const snapshot = JSON.parse(JSON.stringify(entries))

      const filtered = filterDirectChildPeekEntries(entries)

      expect(filtered.map((entry) => entry.id)).toEqual(['1', '3', '7', '8'])
      // No mutation of the input.
      expect(JSON.parse(JSON.stringify(entries))).toEqual(snapshot)
    })

    it('returns a new array (never the input reference)', () => {
      const entries = [makeEntry()]
      const filtered = filterDirectChildPeekEntries(entries)
      expect(filtered).not.toBe(entries)
    })

    it('returns an empty list when every entry is delegation activity', () => {
      const entries = [
        makeEntry({ event_type: 'delegation_started' }),
        makeEntry({ event_type: 'tool_call', data: { tool: 'agent____a' } }),
      ]
      expect(filterDirectChildPeekEntries(entries)).toEqual([])
    })
  })
})
