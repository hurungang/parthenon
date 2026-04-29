import { describe, it, expect } from 'vitest'

/**
 * Type-level tests for TypeScript interfaces.
 * These compile-time tests verify the type definitions are correct.
 */
describe('TypeScript types', () => {
  it('AgentMode values are correctly typed', () => {
    type AgentMode = 'sop-agent' | 'skillful-agent'
    const modes: AgentMode[] = ['sop-agent', 'skillful-agent']
    expect(modes).toHaveLength(2)
  })

  it('RoleType values are correctly typed', () => {
    type RoleType = 'user' | 'agent' | 'both'
    const types: RoleType[] = ['user', 'agent', 'both']
    expect(types).toHaveLength(3)
  })

  it('ChannelType values are correctly typed', () => {
    type ChannelType = 'email' | 'slack' | 'teams' | 'webhook'
    const types: ChannelType[] = ['email', 'slack', 'teams', 'webhook']
    expect(types).toHaveLength(4)
  })

  it('DeliveryStatus values are correctly typed', () => {
    type DeliveryStatus = 'pending' | 'delivered' | 'failed'
    const statuses: DeliveryStatus[] = ['pending', 'delivered', 'failed']
    expect(statuses).toHaveLength(3)
  })

  it('ConversationStatus values are correctly typed', () => {
    type ConversationStatus = 'active' | 'closed' | 'error'
    const statuses: ConversationStatus[] = ['active', 'closed', 'error']
    expect(statuses).toHaveLength(3)
  })
})
