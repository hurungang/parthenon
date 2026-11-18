import React from 'react'
import { Alert, Divider, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { AgentPlan, TopologyNode } from '../../types'
import TopologyDiagramRenderer from './TopologyDiagramRenderer'
import { withCommunicationHub } from './topologyHub'
import { PlanStepTree } from './PlanStepTree'

interface AgentPlanContentProps {
  plan: AgentPlan | null | undefined
  noPlanMessage?: string
  onNodeClick?: (node: TopologyNode) => void
  /**
   * Open the owning agent type's Scripts tab (E4a) — invoked when the user
   * clicks a script link on a script-backed plan step.
   */
  onOpenScript?: () => void
  /**
   * Hide the internal plan-based topology diagram. Used by dialogs that render
   * the unified PanelTopologyCanvas instead (PlanPreviewModal keeps its own
   * plan topology and does NOT set this).
   */
  hideTopology?: boolean
}

/**
 * Presentational component rendering agent plan steps and topology diagram.
 * Used by AgentTypeDetailsDialog's plan tab (PlanPreviewModal renders its own
 * plan layout and applies the same hub helper to its topology).
 */
const AgentPlanContent: React.FC<AgentPlanContentProps> = ({
  plan,
  noPlanMessage,
  onNodeClick,
  onOpenScript,
  hideTopology = false,
}) => {
  const { t } = useTranslation()

  if (!plan) {
    return (
      <Typography variant="body2" color="text.secondary">
        {noPlanMessage ?? t('agents.types.noPlan')}
      </Typography>
    )
  }

  const isFailed =
    plan.generation_status === 'failed' || plan.generation_status === 'pending'

  if (isFailed) {
    return (
      <Alert severity="warning">
        <Typography variant="subtitle2" gutterBottom>
          {t('agents.plan.generationFailed')}
        </Typography>
        {plan.generation_error && (
          <Typography variant="body2">{plan.generation_error}</Typography>
        )}
      </Alert>
    )
  }

  // Append the Communication Hub platform node client-side at render time —
  // the helper is idempotent, so regenerated plans never duplicate the node
  // and no backend/plan-schema change is needed.
  const withHub = withCommunicationHub(
    plan.topology_nodes,
    plan.topology_edges,
    t('agents.plan.nodeTypes.communication_hub'),
    t('agents.plan.hubEdgeLabel'),
  )

  return (
    <>
      <Typography variant="h6" gutterBottom>
        {t('agents.plan.steps')}
      </Typography>

      {plan.plan_steps.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {t('agents.plan.noSteps')}
        </Typography>
      ) : (
        <PlanStepTree
          steps={[...plan.plan_steps].sort((a, b) => a.order - b.order)}
          showType
          hasScriptAction={(step) => Boolean(step.script_version_id)}
          onViewScript={onOpenScript ? () => onOpenScript() : undefined}
          viewScriptLabel={t('agents.scripts.scriptLink')}
          testIdPrefix="base-plan"
        />
      )}

      {!hideTopology &&
        (plan.topology_nodes.length > 0 || plan.topology_edges.length > 0) && (
        <>
          <Divider sx={{ my: 2 }} />
          <Typography variant="h6" gutterBottom>
            {t('agents.plan.topology')}
          </Typography>
          <TopologyDiagramRenderer
            nodes={withHub.nodes}
            edges={withHub.edges}
            onNodeClick={onNodeClick}
          />
        </>
      )}
    </>
  )
}

export default AgentPlanContent
