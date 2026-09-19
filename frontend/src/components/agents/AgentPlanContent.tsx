import React from 'react'
import {
  Alert,
  Box,
  Chip,
  Divider,
  List,
  ListItem,
  ListItemText,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { AgentPlan, TopologyNode } from '../../types'
import TopologyDiagramRenderer from './TopologyDiagramRenderer'
import { withCommunicationHub } from './topologyHub'

function getStepTypeChipColor(
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

interface AgentPlanContentProps {
  plan: AgentPlan | null | undefined
  noPlanMessage?: string
  onNodeClick?: (node: TopologyNode) => void
}

/**
 * Presentational component rendering agent plan steps and topology diagram.
 * Used by AgentTypeDetailsDialog's plan tab (PlanPreviewModal renders its own
 * plan layout and applies the same hub helper to its topology).
 */
const AgentPlanContent: React.FC<AgentPlanContentProps> = ({ plan, noPlanMessage, onNodeClick }) => {
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
        <List dense disablePadding>
          {[...plan.plan_steps]
            .sort((a, b) => a.order - b.order)
            .map((step) => (
              <ListItem
                key={step.order}
                alignItems="flex-start"
                disableGutters
                sx={{ py: 0.5 }}
              >
                <ListItemText
                  primary={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography
                        variant="caption"
                        sx={{ minWidth: 22, fontWeight: 700, color: 'text.secondary' }}
                      >
                        {step.order}.
                      </Typography>
                      <Chip
                        label={t(`agents.plan.stepTypes.${step.type}`)}
                        size="small"
                        color={getStepTypeChipColor(step.type)}
                        variant="outlined"
                        sx={{ fontSize: 10, height: 20 }}
                      />
                      <Typography variant="body2" fontWeight={500}>
                        {step.name}
                      </Typography>
                    </Box>
                  }
                  secondary={
                    step.description ? (
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{ ml: 4, display: 'block' }}
                      >
                        {step.description}
                      </Typography>
                    ) : undefined
                  }
                />
              </ListItem>
            ))}
        </List>
      )}

      {(plan.topology_nodes.length > 0 || plan.topology_edges.length > 0) && (
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
