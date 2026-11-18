import React, { useMemo } from 'react'
import { Box, Button, Chip, Typography } from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import { useTranslation } from 'react-i18next'

/**
 * One flat plan step. ``parent_order`` is optional: when it points at another
 * step's ``order`` the step renders as a child in the tree. The flat ``order``
 * remains the source of truth (and the fallback when a parent is missing).
 */
export interface PlanTreeStep {
  order: number
  parent_order?: number | null
  type?: string | null
  name?: string | null
  description?: string | null
  python_source?: string | null
  scriptable?: boolean
  script_version_id?: string | null
}

interface PlanStepTreeProps {
  steps: PlanTreeStep[]
  /** Show the action button for script-backed steps. */
  onViewScript?: (step: PlanTreeStep) => void
  /** Localized label for that action. */
  viewScriptLabel?: string
  /** Render the step-type chip (base plan semantics). */
  showType?: boolean
  /** Which steps get the action button (defaults to Python/scriptable steps). */
  hasScriptAction?: (step: PlanTreeStep) => boolean
  /** Prefix for stable test ids (``${prefix}-step-${order}``). */
  testIdPrefix?: string
}

function stepTypeColor(
  type: string,
): 'primary' | 'secondary' | 'success' | 'warning' | 'default' {
  switch (type) {
    case 'sop_invocation':
      return 'primary'
    case 'skill_invocation':
      return 'secondary'
    case 'agent_delegation':
      return 'warning'
    case 'tool_call':
      return 'success'
    default:
      return 'default'
  }
}

/** Build the forest from flat steps, tolerating missing/self/cyclic parents. */
function buildForest(steps: PlanTreeStep[]): {
  roots: PlanTreeStep[]
  children: Map<number, PlanTreeStep[]>
} {
  const byOrder = new Map<number, PlanTreeStep>()
  for (const step of steps) byOrder.set(step.order, step)

  const children = new Map<number, PlanTreeStep[]>()
  const roots: PlanTreeStep[] = []

  for (const step of steps) {
    const parentOrder = step.parent_order
    const hasParent =
      parentOrder != null &&
      parentOrder !== step.order &&
      byOrder.has(parentOrder)
    if (!hasParent) {
      roots.push(step)
      continue
    }
    const siblings = children.get(parentOrder as number) ?? []
    siblings.push(step)
    children.set(parentOrder as number, siblings)
  }

  const byOrderAsc = (a: PlanTreeStep, b: PlanTreeStep) => a.order - b.order
  roots.sort(byOrderAsc)
  for (const list of children.values()) list.sort(byOrderAsc)
  return { roots, children }
}

/**
 * Renders a flat implementation plan as a tree (indentation + connectors) and
 * puts the script action in a normal button beside the step, so it can never
 * overlap the description. Used by the base-plan preview and the Optimized
 * Plan tab.
 */
export const PlanStepTree: React.FC<PlanStepTreeProps> = ({
  steps,
  onViewScript,
  viewScriptLabel,
  showType = false,
  hasScriptAction,
  testIdPrefix = 'plan',
}) => {
  const { t } = useTranslation()
  const { roots, children } = useMemo(() => buildForest(steps), [steps])
  const visited = new Set<number>()

  const renderStep = (step: PlanTreeStep, depth: number): React.ReactNode => {
    if (visited.has(step.order)) return null
    visited.add(step.order)
    const kids = children.get(step.order) ?? []
    const isScriptStep = hasScriptAction
      ? hasScriptAction(step)
      : Boolean(step.python_source || step.scriptable)

    return (
      <Box key={step.order} data-testid={`${testIdPrefix}-step-${step.order}`}>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 1,
            pl: depth * 3,
            py: 0.75,
            borderLeft: depth > 0 ? 2 : 0,
            borderColor: 'divider',
            ml: depth > 0 ? 2 : 0,
          }}
        >
          {/* An action marker, not a number — numbers get confusing once the
              plan has sub-steps. Children use a slightly different color. */}
          <PlayArrowIcon
            data-testid={`${testIdPrefix}-step-icon-${step.order}`}
            aria-hidden
            sx={{
              fontSize: 18,
              mt: 0.25,
              flexShrink: 0,
              color: depth > 0 ? 'primary.light' : 'primary.main',
            }}
          />
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
              {showType && step.type && (
                <Chip
                  label={t(`agents.plan.stepTypes.${step.type}`)}
                  size="small"
                  color={stepTypeColor(step.type)}
                  variant="outlined"
                  sx={{ fontSize: 10, height: 20 }}
                />
              )}
              <Typography variant="body2" fontWeight={600}>
                {step.name ||
                  `${t('agents.optimizedPlan.stepFallback', {
                    defaultValue: 'Step',
                  })} ${step.order}`}
              </Typography>
            </Box>
            {step.description && (
              <Typography
                variant="caption"
                color="text.secondary"
                component="div"
                sx={{ mt: 0.25, whiteSpace: 'pre-wrap' }}
              >
                {step.description}
              </Typography>
            )}
          </Box>
          {onViewScript && isScriptStep && (
            <Button
              size="small"
              variant="outlined"
              onClick={() => onViewScript(step)}
              data-testid={`view-script-${step.order}`}
              sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}
            >
              {viewScriptLabel ??
                t('agents.optimizedPlan.viewScript', {
                  defaultValue: 'View script',
                })}
            </Button>
          )}
        </Box>
        {kids.map((child) => renderStep(child, depth + 1))}
      </Box>
    )
  }

  if (steps.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        {t('agents.optimizedPlan.noSteps', { defaultValue: 'No steps yet.' })}
      </Typography>
    )
  }

  return <Box data-testid={`${testIdPrefix}-tree`}>{roots.map((step) => renderStep(step, 0))}</Box>
}

export default PlanStepTree
