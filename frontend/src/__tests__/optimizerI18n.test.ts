import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import en from '../i18n/locales/en.json'

/**
 * i18n regression for the optimizer surface (7.6).
 *
 * Every new operator-facing string must resolve from `en.json` through `t()` —
 * no hardcoded copy and no untranslated fallback. This scans the optimizer
 * components/hooks for literal `t('…')` keys and resolves each one against the
 * English catalogue.
 */

const here = path.dirname(fileURLToPath(import.meta.url))
const src = path.resolve(here, '..')

const FILES = [
  path.join(src, 'components/optimizer/OptimizationSessionBar.tsx'),
  path.join(src, 'components/optimizer/LiveTestApprovalCard.tsx'),
  path.join(src, 'components/optimizer/OptimizerAskCard.tsx'),
  path.join(src, 'components/optimizer/OptimizerActivityBlock.tsx'),
  path.join(src, 'components/optimizer/OptimizerAuditBlock.tsx'),
  path.join(src, 'components/optimizer/OptimizerModelAlert.tsx'),
  path.join(src, 'components/agents/AgentOptimizedPlanTab.tsx'),
  path.join(src, 'components/agents/ConversationDialog.tsx'),
  path.join(src, 'pages/system/SystemConfigPage.tsx'),
  path.join(src, 'hooks/useOptimizationGate.ts'),
]

/** Only the optimizer-owned namespaces are asserted here. */
const OPTIMIZER_PREFIXES = [
  'agents.optimizer.',
  'agents.optimizedPlan.talkToOptimizer',
  'systemConfig.optimizer',
]

function lookup(key: string): unknown {
  return key.split('.').reduce<unknown>((node, part) => {
    if (node && typeof node === 'object' && part in (node as Record<string, unknown>)) {
      return (node as Record<string, unknown>)[part]
    }
    return undefined
  }, en as unknown)
}

function collectKeys(): string[] {
  const keys = new Set<string>()
  for (const file of FILES) {
    const source = fs.readFileSync(file, 'utf8')
    const pattern = /\bt\(\s*'([a-zA-Z0-9_.]+)'/g
    let match: RegExpExecArray | null
    while ((match = pattern.exec(source)) !== null) {
      const key = match[1]
      if (OPTIMIZER_PREFIXES.some((prefix) => key.startsWith(prefix))) {
        keys.add(key)
      }
    }
  }
  return [...keys].sort()
}

describe('optimizer i18n catalogue', () => {
  it('resolves every literal t() key used by the optimizer surface', () => {
    const keys = collectKeys()
    // Guard against the scanner silently finding nothing.
    expect(keys.length).toBeGreaterThan(20)

    const missing = keys.filter((key) => typeof lookup(key) !== 'string')
    expect(missing).toEqual([])
  })

  it('has non-empty English copy (never an untranslated key echo)', () => {
    const keys = collectKeys()
    const empty = keys.filter((key) => {
      const value = lookup(key)
      return typeof value === 'string' && (value.trim() === '' || value === key)
    })
    expect(empty).toEqual([])
  })

  it('interpolates the subject/agent names the components pass in', () => {
    // The strings that take a `name`/`modelId`/`count` parameter must declare it.
    expect(lookup('agents.optimizer.modeOnAgent')).toContain('{{name}}')
    expect(lookup('agents.optimizer.scopePlan')).toContain('{{name}}')
    expect(lookup('agents.optimizer.scopeConversational')).toContain('{{name}}')
    expect(lookup('agents.optimizer.liveUsed')).toContain('{{count}}')
    expect(lookup('agents.optimizer.modelAlertBodyNotEnabled')).toContain('{{modelId}}')
    expect(lookup('agents.optimizer.approval.scriptSubtitle')).toContain('{{name}}')
    expect(lookup('agents.optimizer.approval.runningOneScript')).toContain('{{name}}')
    expect(lookup('agents.optimizer.approval.itWillCall')).toContain('{{tools}}')
    expect(lookup('agents.optimizer.approval.expiryWindowMinutes')).toContain('{{minutes}}')
    expect(lookup('agents.optimizer.audit.replay')).toContain('{{count}}')
    expect(lookup('systemConfig.optimizerReminderUnavailable')).toContain('{{modelId}}')
  })

  it('provides copy for every optimizer-model reason code and every optimizer chat_error code', () => {
    for (const code of ['optimizer_model_not_configured', 'optimizer_model_not_enabled']) {
      expect(typeof lookup(`agents.optimizer.modelReasons.${code}`)).toBe('string')
      expect(typeof lookup(`agents.optimizer.chatErrors.${code}`)).toBe('string')
    }
    for (const code of ['optimization_out_of_scope', 'optimization_permission_denied']) {
      expect(typeof lookup(`agents.optimizer.chatErrors.${code}`)).toBe('string')
    }
  })

  it('states the safety-critical guarantees in the approval copy', () => {
    const note = lookup('agents.optimizer.approval.runsOnceNote') as string
    // Single use, once, never remembered.
    expect(note).toMatch(/once/i)
    expect(note).toMatch(/not remembered/i)

    const expired = lookup('agents.optimizer.approval.noteExpired') as string
    expect(expired).toMatch(/never executed/i)

    const usedOnce = lookup('agents.optimizer.approval.usedOnce') as string
    expect(usedOnce).toMatch(/not remembered/i)

    // The script — not the tools — is the unit of approval.
    const preview = lookup('agents.optimizer.approval.previewNote') as string
    expect(preview).toMatch(/whole script/i)

    // The chat's compact audit bar exists and is the only header chrome.
    expect(lookup('agents.optimizer.sessionBar.title')).toBe(
      'What ran in this session',
    )
  })

  it('covers every optimized-plan conversation entry string', () => {
    for (const key of [
      'agents.optimizedPlan.talkToOptimizer',
      'agents.optimizedPlan.talkToOptimizerScope',
      'agents.optimizedPlan.talkToOptimizerModelLabel',
      'agents.optimizedPlan.talkToOptimizerModelInherited',
      'agents.optimizedPlan.talkToOptimizerModelMissing',
      'agents.optimizedPlan.talkToOptimizerPermission',
      'agents.optimizedPlan.talkToOptimizerEmptyTitle',
      'agents.optimizedPlan.talkToOptimizerEmptyBody',
      'agents.optimizedPlan.talkToOptimizerEmptyConversational',
    ]) {
      expect(typeof lookup(key)).toBe('string')
    }
  })
})
