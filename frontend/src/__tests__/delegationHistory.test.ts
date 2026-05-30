import { describe, expect, it } from 'vitest'
import type { ConversationTurn } from '../types'
import { buildDelegationHistoryFromTurns, buildHistoryMessagesFromTurns } from '../utils/delegationHistory'

describe('delegationHistory utils', () => {
  it('keeps receiver session id when duplicate waiting status is deduplicated', () => {
    const turns: ConversationTurn[] = [
      {
        id: 'turn-1',
        session_id: 'session-1',
        role: 'agent',
        content: 'Final delegated result',
        token_count: null,
        created_at: '2026-05-29T10:00:00Z',
        tool_calls: [
          {
            id: 'tc-1',
            turn_id: 'turn-1',
            tool_name: 'chat_status',
            tool_input: null,
            tool_output: {
              status: 'waiting',
              agent_type: 'research-agent',
            },
            error: null,
            duration_ms: null,
            created_at: '2026-05-29T10:00:01Z',
          },
          {
            id: 'tc-2',
            turn_id: 'turn-1',
            tool_name: 'chat_status',
            tool_input: null,
            tool_output: {
              status: 'waiting',
              agent_type: 'research-agent',
              receiver_session_id: 'delegated-session-123',
            },
            error: null,
            duration_ms: null,
            created_at: '2026-05-29T10:00:02Z',
          },
        ],
      },
    ]

    const hydration = buildDelegationHistoryFromTurns(turns)

    expect(hydration.cycles).toHaveLength(1)
    expect(hydration.cycles[0]?.snippets).toHaveLength(1)
    expect(hydration.cycles[0]?.executionSessionId).toBe('delegated-session-123')
  })

  it('does not inject synthetic delegation message before final conductor agent message', () => {
    const turns: ConversationTurn[] = [
      {
        id: 'turn-user-1',
        session_id: 'session-1',
        role: 'user',
        content: 'Please delegate this task',
        token_count: null,
        created_at: '2026-05-29T10:00:00Z',
        tool_calls: [],
      },
      {
        id: 'turn-agent-1',
        session_id: 'session-1',
        role: 'agent',
        content: 'Delegated result is complete',
        token_count: null,
        created_at: '2026-05-29T10:00:05Z',
        tool_calls: [
          {
            id: 'tc-1',
            turn_id: 'turn-agent-1',
            tool_name: 'chat_status',
            tool_input: null,
            tool_output: {
              status: 'delegating',
              agent_type: 'research-agent',
            },
            error: null,
            duration_ms: null,
            created_at: '2026-05-29T10:00:01Z',
          },
        ],
      },
    ]

    const history = buildHistoryMessagesFromTurns(
      turns,
      (agentType) => `Delegating to agent ${agentType}`,
    )

    expect(history).toHaveLength(2)
    expect(history[1]?.content).toBe('Delegated result is complete')
  })

  it('drops delegation-status-only agent turns represented by cycle bubble', () => {
    const turns: ConversationTurn[] = [
      {
        id: 'turn-user-1',
        session_id: 'session-1',
        role: 'user',
        content: 'Please delegate this task',
        token_count: null,
        created_at: '2026-05-29T10:00:00Z',
        tool_calls: [],
      },
      {
        id: 'turn-agent-status-1',
        session_id: 'session-1',
        role: 'agent',
        content: 'Delegating to agent research-agent',
        token_count: null,
        created_at: '2026-05-29T10:00:01Z',
        tool_calls: [
          {
            id: 'tc-status-1',
            turn_id: 'turn-agent-status-1',
            tool_name: 'chat_status',
            tool_input: null,
            tool_output: {
              status: 'delegating',
              agent_type: 'research-agent',
            },
            error: null,
            duration_ms: null,
            created_at: '2026-05-29T10:00:01Z',
          },
        ],
      },
      {
        id: 'turn-agent-2',
        session_id: 'session-1',
        role: 'agent',
        content: 'Delegated result is complete',
        token_count: null,
        created_at: '2026-05-29T10:00:05Z',
        tool_calls: [],
      },
    ]

    const history = buildHistoryMessagesFromTurns(
      turns,
      (agentType) => `Delegating to agent ${agentType}`,
    )

    expect(history).toHaveLength(2)
    expect(history[0]?.content).toBe('Please delegate this task')
    expect(history[1]?.content).toBe('Delegated result is complete')
  })

  it('merges delegating and waiting across two separate agent turns into one cycle', () => {
    // Regression test: backend can persist a status-only agent turn for the delegating event
    // and a separate response agent turn that carries the waiting status. Before the fix,
    // the end-of-turn activeCycle reset caused the waiting snippet to start a SECOND cycle,
    // producing a duplicate "Delegation Progress / No delegation snippets yet" bubble on resume.
    const turns: ConversationTurn[] = [
      {
        id: 'turn-user-1',
        session_id: 'session-1',
        role: 'user',
        content: 'can you help find supabase project name',
        token_count: null,
        created_at: '2026-05-30T12:14:24Z',
        tool_calls: [],
      },
      {
        id: 'turn-agent-status',
        session_id: 'session-1',
        role: 'agent',
        content: 'Delegating to agent supabase-agent',
        token_count: null,
        created_at: '2026-05-30T12:14:29Z',
        tool_calls: [
          {
            id: 'tc-delegating',
            turn_id: 'turn-agent-status',
            tool_name: 'chat_status',
            tool_input: null,
            tool_output: {
              status: 'delegating',
              agent_type: 'supabase-agent',
              timestamp: '2026-05-30T12:14:29Z',
            },
            error: null,
            duration_ms: null,
            created_at: '2026-05-30T12:14:29Z',
          },
        ],
      },
      {
        id: 'turn-agent-response',
        session_id: 'session-1',
        role: 'agent',
        content: 'The supabase project name is example-project',
        token_count: null,
        created_at: '2026-05-30T12:14:35Z',
        tool_calls: [
          {
            id: 'tc-waiting',
            turn_id: 'turn-agent-response',
            tool_name: 'chat_status',
            tool_input: null,
            tool_output: {
              status: 'waiting',
              agent_type: 'supabase-agent',
              receiver_session_id: 'delegated-exec-session-abc',
              timestamp: '2026-05-30T12:14:34Z',
            },
            error: null,
            duration_ms: null,
            created_at: '2026-05-30T12:14:34Z',
          },
        ],
      },
    ]

    const hydration = buildDelegationHistoryFromTurns(turns)

    // Must produce exactly ONE cycle, not two
    expect(hydration.cycles).toHaveLength(1)
    const cycle = hydration.cycles[0]!
    expect(cycle.snippets.map((s) => s.kind)).toEqual(['delegating', 'waiting'])
    expect(cycle.executionSessionId).toBe('delegated-exec-session-abc')
    expect(cycle.completed).toBe(true)
  })
})
